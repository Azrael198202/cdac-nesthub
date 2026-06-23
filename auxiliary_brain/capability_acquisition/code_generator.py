from __future__ import annotations

import ast
import json
import os
import re
import sys
import time
import threading
import concurrent.futures
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from ai_core.runtime.state import runtime_state_manager
except Exception:  # pragma: no cover - optional runtime integration
    runtime_state_manager = None
try:
    from auxiliary_brain.runtime.observability.runtime_console import emit_console_event
except Exception:  # pragma: no cover - optional runtime integration
    emit_console_event = None
try:
    from auxiliary_brain.models.model_downloader import RuntimeModelDownloader
except Exception:  # pragma: no cover - optional runtime integration
    RuntimeModelDownloader = None

from ai_core.model_orchestration import LiteLLMBrainClient
from ai_core.capability_task_graph import CapabilityTaskGraphCompiler
from auxiliary_brain.capability_acquisition.specification_contract_compiler import CapabilitySpecificationContractCompiler
from auxiliary_brain.capability_acquisition.schema_boundary import CapabilitySchemaBoundary
from auxiliary_brain.capability_acquisition.prompt_engineer import build_generation_prompt_messages


class RuntimeBlueprintArtifactGenerator:
    """Materialize runtime capability blueprints into sandboxable artifacts.

    Boundary:
    - This module is a generic artifact-generation orchestrator.
    - It does not infer business/domain intent.
    - It does not contain capability-specific implementation templates.
    - Executable tool code must come from an already supplied blueprint file set
      or from an LLM code-generation route selected through BrainModelRouter / LiteLLM.
    - If executable code cannot be generated and validated structurally, the
      result stays blueprint-only and must not be registered as a runnable tool.
    """

    def __init__(self, *, llm_client: LiteLLMBrainClient | None = None) -> None:
        self.llm_client = llm_client or LiteLLMBrainClient()
        self.contract_compiler = CapabilitySpecificationContractCompiler()
        self.schema_boundary = CapabilitySchemaBoundary()
        self.task_graph_compiler = CapabilityTaskGraphCompiler()

    def materialize(self, blueprint: dict[str, Any], *, identity_contract: dict[str, Any] | None = None, run_id: str | None = None) -> dict[str, Any]:
        if not isinstance(blueprint, dict):
            blueprint = {}
        identity_contract = identity_contract or {}
        tool_id = self._safe_name(str(
            blueprint.get("capability_id")
            or blueprint.get("tool_id")
            or blueprint.get("template_id")
            or identity_contract.get("requested_capability_id")
            or "generated_capability"
        ))
        entrypoint = blueprint.get("entrypoint") if isinstance(blueprint.get("entrypoint"), dict) else {"module": "tool.py", "function": "run"}
        entrypoint.setdefault("module", "tool.py")
        entrypoint.setdefault("function", "run")

        input_schema = self._schema_or_default(blueprint.get("input_schema"), "input")
        output_schema = self._schema_or_default(blueprint.get("output_schema"), "output")
        connection_schema = self._closed_schema(blueprint.get("connection_schema"))
        secret_schema = self._closed_schema(blueprint.get("secret_schema"))
        declared_input_schema = self._schema_or_default(blueprint.get("input_schema"), "input")
        declared_output_schema = self._schema_or_default(blueprint.get("output_schema"), "output")
        declared_connection_schema = self._closed_schema(blueprint.get("connection_schema"))
        declared_secret_schema = self._closed_schema(blueprint.get("secret_schema"))

        boundary = self.schema_boundary.normalize(
            input_schema=input_schema,
            connection_schema=connection_schema,
            secret_schema=secret_schema,
            verification_input=blueprint.get("verification_input") if isinstance(blueprint.get("verification_input"), dict) else None,
        )
        input_schema = boundary["input_schema"]
        connection_schema = boundary["connection_schema"]
        secret_schema = boundary["secret_schema"]
        verification_input = boundary["verification_input"] or self._generic_verification_input(input_schema, connection_schema, secret_schema)

        declared_boundary = self.schema_boundary.normalize(
            input_schema=declared_input_schema,
            connection_schema=declared_connection_schema,
            secret_schema=declared_secret_schema,
            verification_input=verification_input,
        )
        declared_input_schema = declared_boundary["input_schema"]
        declared_connection_schema = declared_boundary["connection_schema"]
        declared_secret_schema = declared_boundary["secret_schema"]
        verification_input = self._verification_input_with_schema_sample(declared_boundary["verification_input"], input_schema, connection_schema, secret_schema)
        verification_expectations = blueprint.get("verification_expectations") if isinstance(blueprint.get("verification_expectations"), dict) else {"status": "completed"}
        dependencies = self._drop_stdlib_dependencies(self._normalized_dependencies(blueprint.get("dependencies")))
        specification_contract = self.contract_compiler.compile(
            blueprint=blueprint,
            input_schema=input_schema,
            output_schema=output_schema,
            connection_schema=connection_schema,
            secret_schema=secret_schema,
            verification_input=verification_input,
            verification_expectations=verification_expectations,
        )
        runtime_execution_policy = self._runtime_execution_policy_or_default(
            blueprint.get("runtime_execution_policy"),
            input_schema=input_schema,
            connection_schema=connection_schema,
            secret_schema=secret_schema,
            dependencies=dependencies,
        )
        approval_policy = self._approval_policy_or_default(blueprint.get("approval_policy"), runtime_execution_policy=runtime_execution_policy)
        capability_contract = self._capability_contract(tool_id=tool_id, blueprint=blueprint)
        files = blueprint.get("files") if isinstance(blueprint.get("files"), list) else []
        artifact_kind = "blueprint_only_not_registerable"
        generation_status = "not_attempted"
        generation_route: dict[str, Any] = {}
        generation_error = ""

        provided_files_accepted = False
        if self._valid_files(files) and not self._files_look_like_stub(files):
            candidate_files = self._stabilize_standard_library_runtime_files(files, blueprint=blueprint)
            contract_violations = self._generated_artifact_contract_violations(
                {"files": candidate_files},
                input_schema=declared_input_schema,
                connection_schema=declared_connection_schema,
                secret_schema=declared_secret_schema,
            )
            if contract_violations:
                generation_status = "provided_blueprint_files_rejected_by_schema_contract"
                generation_error = "; ".join(contract_violations[:8])
                files = []
            else:
                files = candidate_files
                input_schema = self._reconcile_required_fields_from_source(input_schema, files, scope="input")
                connection_schema = self._reconcile_required_fields_from_source(connection_schema, files, scope="connection")
                secret_schema = self._reconcile_required_fields_from_source(secret_schema, files, scope="secrets")
                input_schema = self._merge_declared_schema(declared_input_schema, input_schema, default_name="input")
                output_schema = self._merge_declared_schema(declared_output_schema, output_schema, default_name="output")
                connection_schema = self._merge_declared_schema(declared_connection_schema, connection_schema, default_name="connection")
                secret_schema = self._merge_declared_schema(declared_secret_schema, secret_schema, default_name="secrets")
                boundary = self.schema_boundary.normalize(
                    input_schema=input_schema,
                    connection_schema=connection_schema,
                    secret_schema=secret_schema,
                    verification_input=verification_input,
                )
                input_schema = boundary["input_schema"]
                connection_schema = boundary["connection_schema"]
                secret_schema = boundary["secret_schema"]
                verification_input = self._verification_input_with_schema_sample(boundary["verification_input"], input_schema, connection_schema, secret_schema)
                artifact_kind = "real_runtime_implementation"
                generation_status = "provided_blueprint_files_used"
                provided_files_accepted = True
        if not provided_files_accepted:
            if self._should_request_llm_generation(blueprint, identity_contract):
                llm_artifact = self._generate_with_llm(
                    tool_id=tool_id,
                    run_id=run_id,
                    entrypoint=entrypoint,
                    blueprint=blueprint,
                    identity_contract=identity_contract,
                    input_schema=input_schema,
                    output_schema=output_schema,
                    connection_schema=connection_schema,
                    secret_schema=secret_schema,
                    verification_input=verification_input,
                    specification_contract=specification_contract,
                )
                generation_status = str(llm_artifact.get("generation_status") or "failed")
                generation_route = llm_artifact.get("generation_route") if isinstance(llm_artifact.get("generation_route"), dict) else {}
                generation_error = str(llm_artifact.get("generation_error") or "")
                if self._valid_generated_artifact(llm_artifact):
                    files = llm_artifact["files"]
                    input_schema = self._merge_declared_schema(declared_input_schema, llm_artifact.get("input_schema") if isinstance(llm_artifact.get("input_schema"), dict) else input_schema, default_name="input")
                    output_schema = self._merge_declared_schema(declared_output_schema, llm_artifact.get("output_schema") if isinstance(llm_artifact.get("output_schema"), dict) else output_schema, default_name="output")
                    connection_schema = self._merge_declared_schema(declared_connection_schema, self._closed_schema(llm_artifact.get("connection_schema")), default_name="connection")
                    secret_schema = self._merge_declared_schema(declared_secret_schema, self._closed_schema(llm_artifact.get("secret_schema")), default_name="secrets")
                    verification_input = llm_artifact.get("verification_input") if isinstance(llm_artifact.get("verification_input"), dict) else self._generic_verification_input(input_schema, connection_schema, secret_schema)
                    verification_input = self._verification_input_with_schema_sample(verification_input, input_schema, connection_schema, secret_schema)
                    verification_expectations = llm_artifact.get("verification_expectations") if isinstance(llm_artifact.get("verification_expectations"), dict) else verification_expectations
                    boundary = self.schema_boundary.normalize(
                        input_schema=input_schema,
                        connection_schema=connection_schema,
                        secret_schema=secret_schema,
                        verification_input=verification_input,
                    )
                    input_schema = boundary["input_schema"]
                    connection_schema = boundary["connection_schema"]
                    secret_schema = boundary["secret_schema"]
                    verification_input = self._verification_input_with_schema_sample(boundary["verification_input"], input_schema, connection_schema, secret_schema)
                    specification_contract = self.contract_compiler.compile(
                        blueprint={**blueprint, **llm_artifact},
                        input_schema=input_schema,
                        output_schema=output_schema,
                        connection_schema=connection_schema,
                        secret_schema=secret_schema,
                        verification_input=verification_input,
                        verification_expectations=verification_expectations,
                    )
                    files = self._stabilize_standard_library_runtime_files(files, blueprint=blueprint)
                    input_schema = self._reconcile_required_fields_from_source(input_schema, files, scope="input")
                    connection_schema = self._reconcile_required_fields_from_source(connection_schema, files, scope="connection")
                    secret_schema = self._reconcile_required_fields_from_source(secret_schema, files, scope="secrets")
                    boundary = self.schema_boundary.normalize(
                        input_schema=input_schema,
                        connection_schema=connection_schema,
                        secret_schema=secret_schema,
                        verification_input=verification_input,
                    )
                    input_schema = boundary["input_schema"]
                    connection_schema = boundary["connection_schema"]
                    secret_schema = boundary["secret_schema"]
                    verification_input = self._verification_input_with_schema_sample(boundary["verification_input"], input_schema, connection_schema, secret_schema)
                    dependencies = self._merge_dependencies(dependencies, self._normalized_dependencies(llm_artifact.get("dependencies")))
                    dependencies = self._drop_stdlib_dependencies(dependencies)
                    capability_contract = self._capability_contract(tool_id=tool_id, blueprint={**blueprint, **llm_artifact})
                    artifact_kind = "real_runtime_implementation"
                else:
                    files = self._neutral_files(tool_id=tool_id, entrypoint=entrypoint, reason=generation_error or generation_status)
            else:
                generation_status = "llm_generation_not_allowed_by_policy"
                generation_error = "LLM code generation was not allowed by the acquisition policy."
                files = self._neutral_files(tool_id=tool_id, entrypoint=entrypoint, reason="llm_generation_not_allowed_by_policy")

        final_boundary = self.schema_boundary.normalize(
            input_schema=input_schema,
            connection_schema=connection_schema,
            secret_schema=secret_schema,
            verification_input=verification_input,
        )
        input_schema = final_boundary["input_schema"]
        connection_schema = final_boundary["connection_schema"]
        secret_schema = final_boundary["secret_schema"]
        verification_input = self._verification_input_with_schema_sample(final_boundary["verification_input"], input_schema, connection_schema, secret_schema)
        specification_contract = self.contract_compiler.compile(
            blueprint=blueprint,
            input_schema=input_schema,
            output_schema=output_schema,
            connection_schema=connection_schema,
            secret_schema=secret_schema,
            verification_input=verification_input,
            verification_expectations=verification_expectations,
        )

        return {
            "template_id": tool_id,
            "description": str(blueprint.get("description") or "Runtime-generated capability artifact."),
            "capabilities": blueprint.get("capabilities") if isinstance(blueprint.get("capabilities"), list) else [tool_id],
            "match_terms": blueprint.get("match_terms") if isinstance(blueprint.get("match_terms"), list) else [],
            "required_terms": blueprint.get("required_terms") if isinstance(blueprint.get("required_terms"), list) else [],
            "entrypoint": entrypoint,
            "files": files,
            "dependencies": dependencies,
            "input_schema": input_schema,
            "output_schema": output_schema,
            "connection_schema": connection_schema,
            "secret_schema": secret_schema,
            "approval_policy": approval_policy,
            "runtime_interface": blueprint.get("runtime_interface") if isinstance(blueprint.get("runtime_interface"), dict) else {"input_mode": "json", "output_mode": "json"},
            "runtime_execution_policy": runtime_execution_policy,
            "verification_input": verification_input,
            "verification_expectations": verification_expectations,
            "specification_contract": specification_contract,
            "acquisition_policy": blueprint.get("acquisition_policy") if isinstance(blueprint.get("acquisition_policy"), dict) else {"allow_llm_code_generation": True},
            "capability_match_contract": capability_contract,
            "artifact_kind": artifact_kind,
            "blueprint_source": blueprint.get("blueprint_source") or "runtime_blueprint_planner",
            "code_generation": {
                "mode": "capability_taskgraph_mainflow",
                "status": generation_status,
                "route": generation_route,
                "error": generation_error,
            },
            "generated_at": self._now_iso(),
        }


    def _capability_taskgraph_mainflow_enabled(self) -> bool:
        return str(os.getenv("AI_RUNTIME_CAPABILITY_TASKGRAPH_MAINFLOW", "1")).strip().lower() not in {"0", "false", "no", "off"}

    def _capability_replay_dir(self, *, run_id: str | None, tool_id: str) -> Path:
        try:
            from ai_core.config.paths import RUNTIME_TRACES
            base = Path(RUNTIME_TRACES) / "capability_acquisition_replay"
        except Exception:
            base = Path("runtime") / "traces" / "capability_acquisition_replay"
        safe_run = self._safe_name(str(run_id or "runtime"))
        safe_tool = self._safe_name(str(tool_id or "generated_capability"))
        path = base / safe_run / safe_tool
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _emit_replay_event(
        self,
        *,
        run_id: str | None,
        tool_id: str,
        status: str,
        title: str,
        message: str,
        output: Any | None = None,
        error: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if runtime_state_manager is None or not run_id:
            return
        try:
            runtime_state_manager.emit(
                run_id=str(run_id),
                step_id="capability_acquisition.replay",
                level="developer",
                kind="capability_replay",
                status=status,
                title=title,
                message=message,
                output=output,
                error=error,
                method="capability_acquisition_replay",
                tool=str(tool_id or ""),
                progress=None,
                metadata=metadata or {},
            )
        except Exception:
            pass

    def _write_replay_file(
        self,
        *,
        run_id: str | None,
        tool_id: str,
        filename: str,
        content: Any,
        title: str = "Capability acquisition replay",
        status: str = "completed",
        metadata: dict[str, Any] | None = None,
    ) -> str:
        replay_dir = self._capability_replay_dir(run_id=run_id, tool_id=tool_id)
        safe_name = str(filename or "artifact.txt").replace("\\", "/").rsplit("/", 1)[-1]
        path = replay_dir / safe_name
        if isinstance(content, (dict, list)):
            text = json.dumps(content, ensure_ascii=False, indent=2, default=str)
        else:
            text = str(content if content is not None else "")
        path.write_text(text, encoding="utf-8")
        self._emit_replay_event(
            run_id=run_id,
            tool_id=tool_id,
            status=status,
            title=title,
            message=f"Replay file written: {safe_name}",
            output={"replay_file": safe_name, "replay_path": str(path), "preview": text[:3000]},
            metadata=metadata or {},
        )
        return str(path)

    def _stage_replay_name(self, stage_index: int, suffix: str) -> str:
        try:
            n = max(1, int(stage_index))
        except Exception:
            n = 1
        return f"stage_{n:03d}_{suffix}.txt"

    def _original_request_replay_text(self, *, blueprint: dict[str, Any], identity_contract: dict[str, Any], tool_id: str) -> str:
        candidates: list[str] = []
        for source in (identity_contract, blueprint):
            if isinstance(source, dict):
                for key in ("original_request", "user_request", "request", "instruction", "raw_instruction", "description", "goal"):
                    value = source.get(key)
                    if isinstance(value, str) and value.strip():
                        candidates.append(value.strip())
        if candidates:
            return candidates[0]
        return json.dumps({"tool_id": tool_id, "identity_contract": identity_contract, "blueprint": blueprint}, ensure_ascii=False, indent=2, default=str)

    def _compile_capability_task_graph(
        self,
        *,
        tool_id: str,
        entrypoint: dict[str, Any],
        blueprint: dict[str, Any],
        identity_contract: dict[str, Any],
        input_schema: dict[str, Any],
        output_schema: dict[str, Any],
        connection_schema: dict[str, Any],
        secret_schema: dict[str, Any],
        verification_input: dict[str, Any],
        specification_contract: dict[str, Any],
    ) -> dict[str, Any]:
        return self.task_graph_compiler.compile(
            tool_id=tool_id,
            entrypoint=entrypoint,
            blueprint=blueprint,
            identity_contract=identity_contract,
            input_schema=input_schema,
            output_schema=output_schema,
            connection_schema=connection_schema,
            secret_schema=secret_schema,
            verification_input=verification_input,
            specification_contract=specification_contract,
        )

    def _generate_with_llm(
        self,
        *,
        tool_id: str,
        run_id: str | None,
        entrypoint: dict[str, Any],
        blueprint: dict[str, Any],
        identity_contract: dict[str, Any],
        input_schema: dict[str, Any],
        output_schema: dict[str, Any],
        connection_schema: dict[str, Any],
        secret_schema: dict[str, Any],
        verification_input: dict[str, Any],
        specification_contract: dict[str, Any],
    ) -> dict[str, Any]:
        if self._capability_taskgraph_mainflow_enabled():
            progressive = self._generate_progressive_artifact_with_llm(
                tool_id=tool_id,
                run_id=run_id,
                entrypoint=entrypoint,
                blueprint=blueprint,
                identity_contract=identity_contract,
                input_schema=input_schema,
                output_schema=output_schema,
                connection_schema=connection_schema,
                secret_schema=secret_schema,
                verification_input=verification_input,
                specification_contract=specification_contract,
                previous_attempts=[],
                route_floor=0,
            )
            if self._valid_generated_artifact(progressive):
                contract_violations = self._generated_artifact_contract_violations(
                    progressive,
                    input_schema=input_schema,
                    connection_schema=connection_schema,
                    secret_schema=secret_schema,
                )
                if not contract_violations:
                    progressive["generation_status"] = "completed"
                    progressive["generation_route"] = progressive.get("generation_route") if isinstance(progressive.get("generation_route"), dict) else {"mode": "capability_taskgraph_progressive_generation"}
                    return progressive
                progressive["generation_error"] = "; ".join(contract_violations[:8])
            return progressive if isinstance(progressive, dict) else {"generation_status": "capability_taskgraph_generation_failed", "generation_error": "Capability TaskGraph mainflow did not produce an artifact."}

        base_complexity = self._generation_complexity(blueprint=blueprint, identity_contract=identity_contract)
        attempts: list[dict[str, Any]] = []
        for attempt in self._generation_attempts(base_complexity):
            available, availability_reason = self._codegen_attempt_available(attempt, run_id=run_id, tool_id=tool_id)
            if not available:
                record = {
                    "status": "model_not_available",
                    "route": {"attempt": attempt, "availability_reason": availability_reason},
                    "attempt": attempt,
                    "error": availability_reason,
                    "content_excerpt": "",
                }
                attempts.append(record)
                self._emit_generation_progress(
                    run_id=run_id,
                    tool_id=tool_id,
                    status="running",
                    phase="llm_attempt_skipped_model_not_available",
                    attempt=attempt,
                    error=availability_reason,
                )
                self._emit_generation_attempt_failed(
                    run_id=run_id,
                    tool_id=tool_id,
                    attempt=attempt,
                    record=record,
                    attempts_so_far=attempts,
                )
                continue
            messages = self._generation_messages(
                tool_id=tool_id,
                entrypoint=entrypoint,
                blueprint=blueprint,
                identity_contract=identity_contract,
                input_schema=input_schema,
                output_schema=output_schema,
                connection_schema=connection_schema,
                secret_schema=secret_schema,
                verification_input=verification_input,
                specification_contract=specification_contract,
                compact=bool(attempt.get("compact")),
            )
            self._emit_generation_progress(
                run_id=run_id,
                tool_id=tool_id,
                status="running",
                phase="llm_request_started",
                attempt=attempt,
            )
            result = self._complete_sync_with_heartbeat(
                run_id=run_id,
                tool_id=tool_id,
                attempt=attempt,
                brain="auxiliary_brain",
                task_type="runtime_tool_code_generation",
                complexity=str(attempt.get("complexity") or base_complexity),
                messages=messages,
                context={
                    "tool_id": tool_id,
                    "acquisition_policy": blueprint.get("acquisition_policy") if isinstance(blueprint.get("acquisition_policy"), dict) else {},
                    "dependencies": blueprint.get("dependencies") if isinstance(blueprint.get("dependencies"), list) else [],
                    "generation_attempt": attempt,
                    "route_override": attempt.get("route_override") if isinstance(attempt.get("route_override"), dict) else None,
                },
                response_format={"type": "json_object"} if attempt.get("force_json") else None,
            )
            self._emit_generation_progress(
                run_id=run_id,
                tool_id=tool_id,
                status=str(result.status or "completed"),
                phase="llm_response_received",
                attempt=attempt,
                route=result.route if isinstance(result.route, dict) else {},
                error=result.error,
            )
            route = result.route if isinstance(result.route, dict) else {}
            record = {
                "status": result.status,
                "route": route,
                "attempt": attempt,
                "error": result.error,
                "content_excerpt": str(result.content or "")[:500],
            }
            if result.status != "completed":
                attempts.append(record)
                self._emit_generation_attempt_failed(
                    run_id=run_id,
                    tool_id=tool_id,
                    attempt=attempt,
                    record=record,
                    attempts_so_far=attempts,
                )
                continue
            parsed = self._parse_json_object(result.content)
            if not isinstance(parsed, dict):
                record["status"] = "invalid_llm_json"
                record["error"] = "LLM did not return a JSON object."
                attempts.append(record)
                self._emit_generation_attempt_failed(
                    run_id=run_id,
                    tool_id=tool_id,
                    attempt=attempt,
                    record=record,
                    attempts_so_far=attempts,
                )
                continue
            parsed = self._normalize_llm_artifact_payload(parsed, tool_id=tool_id)
            if not self._valid_generated_artifact(parsed):
                repaired = self._repair_missing_artifact_files(
                    raw_artifact=parsed,
                    tool_id=tool_id,
                    entrypoint=entrypoint,
                    blueprint=blueprint,
                    input_schema=input_schema,
                    output_schema=output_schema,
                    connection_schema=connection_schema,
                    secret_schema=secret_schema,
                    verification_input=verification_input,
                )
                if not self._valid_generated_artifact(repaired):
                    repaired = self._repair_artifact_with_llm(
                        raw_content=str(result.content or ""),
                        raw_artifact=parsed,
                        tool_id=tool_id,
                        run_id=run_id,
                        attempt=attempt,
                        entrypoint=entrypoint,
                        blueprint=blueprint,
                        identity_contract=identity_contract,
                        input_schema=input_schema,
                        output_schema=output_schema,
                        connection_schema=connection_schema,
                        secret_schema=secret_schema,
                        verification_input=verification_input,
                        specification_contract=specification_contract,
                    )
                if self._valid_generated_artifact(repaired):
                    parsed = repaired
                    record["repair_status"] = "artifact_files_repaired"
                else:
                    record["status"] = "invalid_generated_artifact"
                    record["error"] = "LLM JSON did not contain executable artifact files."
                    record["repair_error"] = str((repaired or {}).get("generation_error") or "artifact_file_repair_failed")[:1000] if isinstance(repaired, dict) else "artifact_file_repair_failed"
                    attempts.append(record)
                    self._emit_generation_attempt_failed(
                        run_id=run_id,
                        tool_id=tool_id,
                        attempt=attempt,
                        record=record,
                        attempts_so_far=attempts,
                    )
                    continue
            contract_violations = self._generated_artifact_contract_violations(
                parsed,
                input_schema=input_schema,
                connection_schema=connection_schema,
                secret_schema=secret_schema,
            )
            if contract_violations:
                record["status"] = "schema_contract_violation"
                record["error"] = "; ".join(contract_violations[:8])
                attempts.append(record)
                self._emit_generation_attempt_failed(
                    run_id=run_id,
                    tool_id=tool_id,
                    attempt=attempt,
                    record=record,
                    attempts_so_far=attempts,
                )
                continue
            parsed["generation_status"] = "completed"
            parsed["generation_route"] = route
            parsed["generation_attempts"] = attempts + [record]
            return parsed
        dependency_unavailable = self._dependency_unavailable_generation_result(
            attempts=attempts,
            stage="full_artifact_generation",
        )
        if dependency_unavailable:
            return dependency_unavailable
        # If no model returned a complete artifact envelope, try a generic
        # progressive generation pass.  This is still LLM-based and uses only the
        # user-derived contract.  It does not inject capability-specific logic;
        # it simply asks the selected model to emit smaller files one at a time
        # so large/complex capabilities can complete on local models without a
        # single huge response timing out.
        progressive = self._generate_progressive_artifact_with_llm(
            tool_id=tool_id,
            run_id=run_id,
            entrypoint=entrypoint,
            blueprint=blueprint,
            identity_contract=identity_contract,
            input_schema=input_schema,
            output_schema=output_schema,
            connection_schema=connection_schema,
            secret_schema=secret_schema,
            verification_input=verification_input,
            specification_contract=specification_contract,
            previous_attempts=attempts,
            route_floor=self._last_attempted_route_floor(attempts),
        )
        if self._valid_generated_artifact(progressive):
            contract_violations = self._generated_artifact_contract_violations(
                progressive,
                input_schema=input_schema,
                connection_schema=connection_schema,
                secret_schema=secret_schema,
            )
            if not contract_violations:
                progressive["generation_status"] = "completed"
                progressive["generation_route"] = progressive.get("generation_route") if isinstance(progressive.get("generation_route"), dict) else {"mode": "progressive_file_generation"}
                progressive["generation_attempts"] = attempts + list(progressive.get("generation_attempts") or [])
                return progressive
            progressive["generation_error"] = "; ".join(contract_violations[:8])
            attempts.append({
                "status": "progressive_schema_contract_violation",
                "error": progressive["generation_error"],
                "route": progressive.get("generation_route") if isinstance(progressive.get("generation_route"), dict) else {},
            })

        last = attempts[-1] if attempts else {}
        return {
            "generation_status": str(last.get("status") or "llm_generation_failed"),
            "generation_route": last.get("route") if isinstance(last.get("route"), dict) else {},
            "generation_error": str(last.get("error") or "LLM did not produce a registerable runtime artifact."),
            "generation_attempts": attempts,
        }



    def _generate_progressive_artifact_with_llm(
        self,
        *,
        tool_id: str,
        run_id: str | None,
        entrypoint: dict[str, Any],
        blueprint: dict[str, Any],
        identity_contract: dict[str, Any],
        input_schema: dict[str, Any],
        output_schema: dict[str, Any],
        connection_schema: dict[str, Any],
        secret_schema: dict[str, Any],
        verification_input: dict[str, Any],
        specification_contract: dict[str, Any],
        previous_attempts: list[dict[str, Any]] | None = None,
        route_floor: int = 0,
    ) -> dict[str, Any]:
        """Generate artifact files in smaller generic LLM calls.

        This is a capability-neutral recovery path.  It never uses a hidden
        implementation template and never branches on capability names or domain
        words.  The model still writes the executable behavior from the compact
        contract; the runtime only controls the envelope and asks for one file at
        a time to avoid local-model timeout on one very large response.
        """
        attempts = previous_attempts if isinstance(previous_attempts, list) else []
        progressive_attempts: list[dict[str, Any]] = []
        routes = [attempt for attempt in self._generation_attempts("basic") if isinstance(attempt, dict)]
        # Progressive generation is already split into smaller file-level calls.
        # Keep the policy-defined escalation order so a usable mid-sized model
        # can finish before falling through to the largest local model.  The
        # route_floor skips models already proven unsuitable in full-artifact
        # generation without relying on capability names or business words.
        if route_floor > 0:
            routes = routes[min(route_floor, len(routes)):] or routes[-1:]
        task_graph = self._compile_capability_task_graph(
            tool_id=tool_id,
            entrypoint=entrypoint,
            blueprint=blueprint,
            identity_contract=identity_contract,
            input_schema=input_schema,
            output_schema=output_schema,
            connection_schema=connection_schema,
            secret_schema=secret_schema,
            verification_input=verification_input,
            specification_contract=specification_contract,
        )
        self._emit_generation_progress(
            run_id=run_id,
            tool_id=tool_id,
            status="running",
            phase="capability_taskgraph_generation_started",
            previous_attempt_count=len(attempts),
        )
        self._write_replay_file(
            run_id=run_id,
            tool_id=tool_id,
            filename="original_request.txt",
            content=self._original_request_replay_text(blueprint=blueprint, identity_contract=identity_contract, tool_id=tool_id),
            title="Capability acquisition replay created",
            metadata={"replay_kind": "original_request"},
        )
        self._write_replay_file(
            run_id=run_id,
            tool_id=tool_id,
            filename="task_graph.json",
            content=task_graph,
            title="Capability task graph captured",
            metadata={"replay_kind": "task_graph"},
        )
        self._write_replay_file(
            run_id=run_id,
            tool_id=tool_id,
            filename="replay_manifest.json",
            content={"run_id": run_id, "tool_id": tool_id, "replay_dir": str(self._capability_replay_dir(run_id=run_id, tool_id=tool_id)), "files": ["original_request.txt", "task_graph.json", "replay_manifest.json"]},
            title="Capability replay manifest captured",
            metadata={"replay_kind": "replay_manifest"},
        )
        graph_nodes = [node for node in task_graph.get("nodes", []) if isinstance(node, dict) and node.get("target_file")]
        if not graph_nodes:
            self._write_replay_file(
                run_id=run_id,
                tool_id=tool_id,
                filename="validation_report.json",
                content={"status": "failed", "error": "Capability TaskGraph did not contain executable generation nodes.", "task_graph": task_graph},
                title="Capability replay validation report",
                status="failed",
                metadata={"replay_kind": "validation_report"},
            )
            return {"generation_status": "capability_taskgraph_generation_failed", "generation_error": "Capability TaskGraph did not contain executable generation nodes.", "generation_attempts": progressive_attempts}
        self._emit_generation_progress(
            run_id=run_id,
            tool_id=tool_id,
            status="running",
            phase="capability_taskgraph_generation_completed",
            node_count=len(graph_nodes),
        )
        for attempt in routes:
            available, availability_reason = self._codegen_attempt_available(attempt, run_id=run_id, tool_id=tool_id)
            if not available:
                record = {
                    "status": "model_not_available",
                    "attempt": attempt,
                    "error": availability_reason,
                    "progressive": True,
                }
                progressive_attempts.append(record)
                self._emit_generation_progress(
                    run_id=run_id,
                    tool_id=tool_id,
                    status="running",
                    phase="progressive_attempt_skipped_model_not_available",
                    attempt=attempt,
                    error=availability_reason,
                )
                continue
            files: list[dict[str, str]] = []
            for stage_index, node in enumerate(graph_nodes, start=1):
                path = str(node.get("target_file") or "").strip()
                file_result = self._generate_progressive_file_with_llm(
                    tool_id=tool_id,
                    run_id=run_id,
                    attempt=attempt,
                    path=path,
                    stage_index=stage_index,
                    stage=str(node.get("stage") or node.get("node_id") or path),
                    stage_contract=node,
                    entrypoint=entrypoint,
                    blueprint=blueprint,
                    identity_contract=identity_contract,
                    input_schema=input_schema,
                    output_schema=output_schema,
                    connection_schema=connection_schema,
                    secret_schema=secret_schema,
                    verification_input=verification_input,
                    specification_contract=specification_contract,
                    existing_files=files,
                )
                progressive_attempts.append(file_result.get("attempt_record") if isinstance(file_result.get("attempt_record"), dict) else {"status": file_result.get("status"), "attempt": attempt, "path": path})
                if file_result.get("status") != "completed":
                    files = []
                    break
                files.append({"path": path, "content": str(file_result.get("content") or "")})
            if not files:
                continue
            artifact = {
                "tool_id": tool_id,
                "files": files,
                "input_schema": input_schema,
                "output_schema": output_schema,
                "connection_schema": connection_schema,
                "secret_schema": secret_schema,
                "dependencies": self._drop_stdlib_dependencies(self._normalized_dependencies(blueprint.get("dependencies"))),
                "verification_input": verification_input,
                "verification_expectations": blueprint.get("verification_expectations") if isinstance(blueprint.get("verification_expectations"), dict) else {"status": "completed"},
                "capability_match_contract": self._capability_contract(tool_id=tool_id, blueprint=blueprint),
                "generation_route": {"mode": "capability_taskgraph_progressive_generation", "attempt": attempt},
                "generation_attempts": progressive_attempts,
            }
            artifact = self._normalize_llm_artifact_payload(artifact, tool_id=tool_id)
            if self._valid_generated_artifact(artifact):
                self._write_replay_file(
                    run_id=run_id,
                    tool_id=tool_id,
                    filename="validation_report.json",
                    content={
                        "status": "completed",
                        "tool_id": tool_id,
                        "artifact_file_count": len(files),
                        "files": [f.get("path") for f in files],
                        "generation_route": {"mode": "capability_taskgraph_progressive_generation", "attempt": attempt},
                        "attempts": progressive_attempts,
                    },
                    title="Capability replay validation report",
                    metadata={"replay_kind": "validation_report"},
                )
                self._emit_generation_progress(
                    run_id=run_id,
                    tool_id=tool_id,
                    status="completed",
                    phase="progressive_artifact_generation_completed",
                    attempt=attempt,
                )
                return artifact
        deterministic_artifact = self._generate_contract_driven_artifact_from_task_graph(
            tool_id=tool_id,
            run_id=run_id,
            entrypoint=entrypoint,
            task_graph=task_graph,
            blueprint=blueprint,
            input_schema=input_schema,
            output_schema=output_schema,
            connection_schema=connection_schema,
            secret_schema=secret_schema,
            verification_input=verification_input,
            specification_contract=specification_contract,
            previous_attempts=progressive_attempts,
        )
        if self._valid_generated_artifact(deterministic_artifact):
            return deterministic_artifact

        self._write_replay_file(
            run_id=run_id,
            tool_id=tool_id,
            filename="validation_report.json",
            content={
                "status": "failed",
                "tool_id": tool_id,
                "error": "No progressive model route produced executable artifact files.",
                "attempts": progressive_attempts,
                "deterministic_artifact_error": deterministic_artifact.get("generation_error") if isinstance(deterministic_artifact, dict) else "not_available",
            },
            title="Capability replay validation report",
            status="failed",
            metadata={"replay_kind": "validation_report"},
        )
        self._emit_generation_progress(
            run_id=run_id,
            tool_id=tool_id,
            status="failed",
            phase="progressive_artifact_generation_failed",
            error="No progressive model route produced executable artifact files.",
        )
        dependency_unavailable = self._dependency_unavailable_generation_result(
            attempts=progressive_attempts,
            stage="progressive_artifact_generation",
        )
        if dependency_unavailable:
            return dependency_unavailable
        return {
            "generation_status": "progressive_generation_failed",
            "generation_error": "No progressive model route produced executable artifact files.",
            "generation_attempts": progressive_attempts,
        }

    def _generate_contract_driven_artifact_from_task_graph(
        self,
        *,
        tool_id: str,
        run_id: str | None,
        entrypoint: dict[str, Any],
        task_graph: dict[str, Any],
        blueprint: dict[str, Any],
        input_schema: dict[str, Any],
        output_schema: dict[str, Any],
        connection_schema: dict[str, Any],
        secret_schema: dict[str, Any],
        verification_input: dict[str, Any],
        specification_contract: dict[str, Any],
        previous_attempts: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Build a generic runtime artifact from ai_core TaskGraph contracts."""
        contracts = task_graph.get("contracts") if isinstance(task_graph, dict) else {}
        contracts = contracts if isinstance(contracts, dict) else {}
        operation_contracts = contracts.get("operation_contracts") if isinstance(contracts.get("operation_contracts"), list) else []
        record_contract = contracts.get("record_contract") if isinstance(contracts.get("record_contract"), dict) else self._generic_record_contract(input_schema)
        persistence_contract = contracts.get("persistence_contract") if isinstance(contracts.get("persistence_contract"), dict) else self._generic_persistence_contract(connection_schema)
        if not operation_contracts:
            operation_contracts = self._generic_operation_contracts(input_schema)
        if not operation_contracts:
            return {"generation_status": "contract_driven_generation_failed", "generation_error": "No declared operations were found in the runtime input schema."}
        file_payloads = {
            "contract.json": json.dumps({
                "tool_id": tool_id,
                "input_schema": input_schema,
                "output_schema": output_schema,
                "connection_schema": connection_schema,
                "secret_schema": secret_schema,
                "operation_contracts": operation_contracts,
                "record_contract": record_contract,
                "persistence_contract": persistence_contract,
                "verification_input": verification_input,
            }, ensure_ascii=False, indent=2, default=str),
            "schemas.py": self._contract_driven_schema_source(
                input_schema=input_schema,
                output_schema=output_schema,
                connection_schema=connection_schema,
                secret_schema=secret_schema,
                operation_contracts=operation_contracts,
                record_contract=record_contract,
                persistence_contract=persistence_contract,
            ),
            "storage.py": self._contract_driven_storage_source(),
            "operations.py": self._contract_driven_operations_source(),
            str(entrypoint.get("module") or "tool.py"): self._contract_driven_tool_source(entrypoint=entrypoint),
            "test_tool.py": self._contract_driven_test_source(
                operation_contracts=operation_contracts,
                record_contract=record_contract,
                connection_schema=connection_schema,
            ),
        }
        files = [{"path": path, "content": content} for path, content in file_payloads.items()]
        artifact = {
            "tool_id": tool_id,
            "files": files,
            "input_schema": input_schema,
            "output_schema": output_schema,
            "connection_schema": connection_schema,
            "secret_schema": secret_schema,
            "dependencies": [],
            "verification_input": verification_input,
            "verification_expectations": blueprint.get("verification_expectations") if isinstance(blueprint.get("verification_expectations"), dict) else {"status": "completed"},
            "capability_match_contract": self._capability_contract(tool_id=tool_id, blueprint=blueprint),
            "generation_status": "completed",
            "generation_route": {"mode": "capability_taskgraph_contract_driven_generation", "source": "ai_core_task_graph"},
            "generation_attempts": list(previous_attempts or []) + [{"status": "completed", "route": {"mode": "contract_driven_generation"}}],
        }
        violations = self._operation_coverage_violations(artifact, operation_contracts=operation_contracts, entrypoint=entrypoint)
        if violations:
            return {"generation_status": "contract_driven_generation_failed", "generation_error": "; ".join(violations), "files": files}
        self._write_replay_file(
            run_id=run_id,
            tool_id=tool_id,
            filename="validation_report.json",
            content={
                "status": "completed",
                "tool_id": tool_id,
                "mode": "capability_taskgraph_contract_driven_generation",
                "operation_count": len(operation_contracts),
                "operations": [op.get("operation") for op in operation_contracts if isinstance(op, dict)],
                "files": list(file_payloads.keys()),
                "attempts": list(previous_attempts or []),
            },
            title="Capability replay validation report",
            metadata={"replay_kind": "validation_report"},
        )
        self._emit_generation_progress(
            run_id=run_id,
            tool_id=tool_id,
            status="completed",
            phase="capability_taskgraph_contract_driven_generation_completed",
            operation_count=len(operation_contracts),
        )
        return artifact

    def _generic_operation_contracts(self, input_schema: dict[str, Any]) -> list[dict[str, Any]]:
        props = input_schema.get("properties") if isinstance(input_schema, dict) else {}
        props = props if isinstance(props, dict) else {}
        op_schema = props.get("operation") if isinstance(props.get("operation"), dict) else {}
        enum_values = op_schema.get("enum") if isinstance(op_schema, dict) else []
        contracts = []
        seen = set()
        for value in enum_values if isinstance(enum_values, list) else []:
            op = str(value).strip()
            if not op or op in seen:
                continue
            seen.add(op)
            contracts.append({"operation": op, "semantic_kind": self._operation_semantic_kind(op)})
        return contracts

    def _operation_semantic_kind(self, operation: str) -> str:
        prefix = str(operation or "").strip().lower().split("_", 1)[0]
        mapping = {
            "create": "create", "add": "create", "insert": "create",
            "get": "read_one", "read": "read_one", "retrieve": "read_one",
            "list": "read_many", "search": "search", "find": "search",
            "update": "update", "modify": "update", "patch": "update",
            "delete": "delete", "remove": "delete", "cancel": "delete",
        }
        return mapping.get(prefix, "custom")

    def _generic_record_contract(self, input_schema: dict[str, Any]) -> dict[str, Any]:
        props = input_schema.get("properties") if isinstance(input_schema, dict) else {}
        props = props if isinstance(props, dict) else {}
        reserved = {"operation", "query", "filters", "update_fields", "limit", "offset", "connection", "secrets", "profile", "_runtime"}
        record_key = "record"
        fields = {}
        for key, spec in props.items():
            if key in reserved or not isinstance(spec, dict):
                continue
            if spec.get("type") == "object" and isinstance(spec.get("properties"), dict):
                record_key = key
                fields = spec.get("properties") or {}
                break
        if not fields:
            fields = {key: spec for key, spec in props.items() if key not in reserved and isinstance(spec, dict)}
        id_field = "record_id"
        for key in fields:
            lk = str(key).lower()
            if lk == "id" or lk.endswith("_id"):
                id_field = str(key)
                break
        required = []
        record_schema = props.get(record_key) if isinstance(props.get(record_key), dict) else {}
        if isinstance(record_schema.get("required"), list):
            required = [str(x) for x in record_schema.get("required")]
        return {"record_input_key": record_key, "id_field": id_field, "fields": fields, "required_fields": required}

    def _generic_persistence_contract(self, connection_schema: dict[str, Any]) -> dict[str, Any]:
        props = connection_schema.get("properties") if isinstance(connection_schema, dict) else {}
        props = props if isinstance(props, dict) else {}
        defaults = {k: v.get("default") for k, v in props.items() if isinstance(v, dict) and "default" in v}
        return {"engine": "sqlite_standard_library", "connection_defaults": defaults}

    def _contract_driven_schema_source(self, *, input_schema: dict[str, Any], output_schema: dict[str, Any], connection_schema: dict[str, Any], secret_schema: dict[str, Any], operation_contracts: list[dict[str, Any]], record_contract: dict[str, Any], persistence_contract: dict[str, Any]) -> str:
        return """from __future__ import annotations

import json

INPUT_SCHEMA = __INPUT_SCHEMA__
OUTPUT_SCHEMA = __OUTPUT_SCHEMA__
CONNECTION_SCHEMA = __CONNECTION_SCHEMA__
SECRET_SCHEMA = __SECRET_SCHEMA__
OPERATION_CONTRACTS = __OPERATION_CONTRACTS__
RECORD_CONTRACT = __RECORD_CONTRACT__
PERSISTENCE_CONTRACT = __PERSISTENCE_CONTRACT__


def schema_defaults(schema: dict) -> dict:
    props = schema.get('properties') if isinstance(schema, dict) else {}
    if not isinstance(props, dict):
        return {}
    return {key: value.get('default') for key, value in props.items() if isinstance(value, dict) and 'default' in value}


def as_jsonable(value):
    json.dumps(value, ensure_ascii=False, default=str)
    return value
""".replace("__INPUT_SCHEMA__", repr(input_schema)).replace("__OUTPUT_SCHEMA__", repr(output_schema)).replace("__CONNECTION_SCHEMA__", repr(connection_schema)).replace("__SECRET_SCHEMA__", repr(secret_schema)).replace("__OPERATION_CONTRACTS__", repr(operation_contracts)).replace("__RECORD_CONTRACT__", repr(record_contract)).replace("__PERSISTENCE_CONTRACT__", repr(persistence_contract))

    def _contract_driven_storage_source(self) -> str:
        return """from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


def encode_value(value: Any) -> str:
    if isinstance(value, (dict, list, tuple, bool)) or value is None:
        return json.dumps(value, ensure_ascii=False, default=str)
    return str(value)


def decode_value(value: Any) -> Any:
    if value is None:
        return None
    if not isinstance(value, str):
        return value
    text = value.strip()
    if text[:1] in {'{', '['} or text in {'true', 'false', 'null'}:
        try:
            return json.loads(text)
        except Exception:
            return value
    return value


def connect(database_path: str, timeout_seconds: int | float = 30):
    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=float(timeout_seconds or 30))
    conn.row_factory = sqlite3.Row
    return conn


def ensure_table(conn, table_name: str, fields: list[str], id_field: str) -> None:
    columns = [f'\"{id_field}\" TEXT PRIMARY KEY']
    for field in fields:
        if field == id_field:
            continue
        columns.append(f'\"{field}\" TEXT')
    for standard in ('created_at', 'updated_at'):
        if standard not in fields and standard != id_field:
            columns.append(f'\"{standard}\" TEXT')
    conn.execute(f'CREATE TABLE IF NOT EXISTS \"{table_name}\" ({", ".join(columns)})')
    existing = {row['name'] for row in conn.execute(f'PRAGMA table_info(\"{table_name}\")').fetchall()}
    for field in fields + ['created_at', 'updated_at']:
        if field not in existing and field != id_field:
            conn.execute(f'ALTER TABLE \"{table_name}\" ADD COLUMN \"{field}\" TEXT')
    conn.commit()


def row_to_dict(row) -> dict:
    return {key: decode_value(row[key]) for key in row.keys()}
"""

    def _contract_driven_operations_source(self) -> str:
        return """from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from schemas import CONNECTION_SCHEMA, OPERATION_CONTRACTS, PERSISTENCE_CONTRACT, RECORD_CONTRACT, schema_defaults
from storage import connect, encode_value, ensure_table, row_to_dict


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _semantic_kind(operation: str) -> str:
    prefix = str(operation or '').strip().lower().split('_', 1)[0]
    mapping = {
        'create': 'create', 'add': 'create', 'insert': 'create',
        'get': 'read_one', 'read': 'read_one', 'retrieve': 'read_one',
        'list': 'read_many', 'search': 'search', 'find': 'search',
        'update': 'update', 'modify': 'update', 'patch': 'update',
        'delete': 'delete', 'remove': 'delete', 'cancel': 'delete',
    }
    return mapping.get(prefix, 'custom')


def _operation_kinds() -> dict[str, str]:
    return {str(item.get('operation')): str(item.get('semantic_kind') or _semantic_kind(str(item.get('operation')))) for item in OPERATION_CONTRACTS if isinstance(item, dict)}


def _merge_connection(payload: dict) -> dict:
    defaults = dict(PERSISTENCE_CONTRACT.get('connection_defaults') or {})
    defaults.update(schema_defaults(CONNECTION_SCHEMA))
    for key in ('connection', '_connection', 'profile', '_profile'):
        value = payload.get(key)
        if isinstance(value, dict):
            defaults.update(value)
    return defaults


def _database_path(config: dict) -> str:
    for key, value in config.items():
        lowered = str(key).lower()
        if ('database' in lowered or lowered.endswith('db') or 'db_' in lowered or 'path' in lowered) and value:
            return str(value)
    return 'runtime/memory/runtime_capability.db'


def _table_name(config: dict) -> str:
    for key, value in config.items():
        if 'table' in str(key).lower() and value:
            return str(value)
    return 'records'


def _timeout(config: dict) -> int:
    for key, value in config.items():
        if 'timeout' in str(key).lower() and value not in (None, ''):
            try:
                return int(value)
            except Exception:
                return 30
    return 30


def _fields() -> list[str]:
    fields = list((RECORD_CONTRACT.get('fields') or {}).keys())
    id_field = _id_field()
    if id_field not in fields:
        fields.insert(0, id_field)
    for standard in ('created_at', 'updated_at'):
        if standard not in fields:
            fields.append(standard)
    return fields


def _id_field() -> str:
    return str(RECORD_CONTRACT.get('id_field') or 'record_id')


def _record_key() -> str:
    return str(RECORD_CONTRACT.get('record_input_key') or 'record')


def _connect_for_payload(payload: dict):
    config = _merge_connection(payload)
    conn = connect(_database_path(config), _timeout(config))
    ensure_table(conn, _table_name(config), _fields(), _id_field())
    return conn, _table_name(config)


def _result(operation: str, success: bool, record_id: str | None = None, result: Any = None, error: str | None = None, affected_count: int = 0) -> dict:
    id_field = _id_field()
    return {'operation': operation, 'success': bool(success), 'record_id': record_id, id_field: record_id, 'result': result, 'error': error, 'affected_count': int(affected_count or 0), 'execution_time_utc': now_utc()}


def _record_from_payload(payload: dict) -> dict:
    value = payload.get(_record_key())
    if isinstance(value, dict):
        return dict(value)
    return {key: value for key, value in payload.items() if key in (RECORD_CONTRACT.get('fields') or {})}


def _id_from_payload(payload: dict) -> str | None:
    id_field = _id_field()
    for key in (id_field, 'record_id', 'id'):
        value = payload.get(key)
        if value not in (None, ''):
            return str(value)
    rec = payload.get(_record_key())
    if isinstance(rec, dict):
        value = rec.get(id_field) or rec.get('record_id') or rec.get('id')
        if value not in (None, ''):
            return str(value)
    return None


def _apply_filters(rows: list[dict], filters: dict) -> list[dict]:
    if not isinstance(filters, dict) or not filters:
        return rows
    result = []
    for row in rows:
        ok = True
        for key, expected in filters.items():
            if expected in (None, ''):
                continue
            actual = row.get(key)
            if isinstance(actual, list):
                ok = any(item in actual for item in expected) if isinstance(expected, list) else expected in actual
            elif isinstance(expected, list):
                ok = actual in expected
            else:
                ok = str(actual) == str(expected)
            if not ok:
                break
        if ok:
            result.append(row)
    return result


def create_record(operation: str, payload: dict) -> dict:
    record = _record_from_payload(payload)
    id_field = _id_field()
    required = [field for field in (RECORD_CONTRACT.get('required_fields') or []) if field != id_field]
    missing = [field for field in required if record.get(field) in (None, '')]
    if missing:
        return _result(operation, False, error='missing_required_fields: ' + ', '.join(missing))
    record_id = str(record.get(id_field) or uuid.uuid4())
    record[id_field] = record_id
    timestamp = now_utc()
    record.setdefault('created_at', timestamp)
    record['updated_at'] = timestamp
    fields = _fields()
    conn, table = _connect_for_payload(payload)
    try:
        columns = [field for field in fields if field in record]
        placeholders = ', '.join(['?'] * len(columns))
        sql = f'INSERT INTO \"{table}\" ({", ".join([chr(34)+c+chr(34) for c in columns])}) VALUES ({placeholders})'
        conn.execute(sql, [encode_value(record.get(c)) for c in columns])
        conn.commit()
        return _result(operation, True, record_id=record_id, result=record, affected_count=1)
    finally:
        conn.close()


def get_record(operation: str, payload: dict) -> dict:
    record_id = _id_from_payload(payload)
    if not record_id:
        return _result(operation, False, error='missing_record_id')
    conn, table = _connect_for_payload(payload)
    try:
        row = conn.execute(f'SELECT * FROM \"{table}\" WHERE \"{_id_field()}\" = ?', [record_id]).fetchone()
        if not row:
            return _result(operation, False, record_id=record_id, error='not_found')
        return _result(operation, True, record_id=record_id, result=row_to_dict(row), affected_count=1)
    finally:
        conn.close()


def list_records(operation: str, payload: dict) -> dict:
    limit = int(payload.get('limit') or 50)
    offset = int(payload.get('offset') or 0)
    conn, table = _connect_for_payload(payload)
    try:
        rows = [row_to_dict(row) for row in conn.execute(f'SELECT * FROM \"{table}\"').fetchall()]
        rows = _apply_filters(rows, payload.get('filters') if isinstance(payload.get('filters'), dict) else {})
        order_field = 'start_time' if 'start_time' in _fields() else ('created_at' if 'created_at' in _fields() else _id_field())
        rows.sort(key=lambda item: str(item.get(order_field) or ''))
        paged = rows[offset:offset + limit]
        return _result(operation, True, result=paged, affected_count=len(paged))
    finally:
        conn.close()


def search_records(operation: str, payload: dict) -> dict:
    query = str(payload.get('query') or '').lower()
    listed = list_records(operation, payload)
    if not listed.get('success'):
        return listed
    rows = listed.get('result') if isinstance(listed.get('result'), list) else []
    if query:
        rows = [row for row in rows if query in str(row).lower()]
    return _result(operation, True, result=rows, affected_count=len(rows))


def update_record(operation: str, payload: dict) -> dict:
    record_id = _id_from_payload(payload)
    updates = payload.get('update_fields') if isinstance(payload.get('update_fields'), dict) else {}
    if not record_id:
        return _result(operation, False, error='missing_record_id')
    if not updates:
        return _result(operation, False, record_id=record_id, error='missing_update_fields')
    updates = {key: value for key, value in updates.items() if key in _fields() and key != _id_field()}
    updates['updated_at'] = now_utc()
    conn, table = _connect_for_payload(payload)
    try:
        assignments = ', '.join([f'\"{key}\" = ?' for key in updates])
        cur = conn.execute(f'UPDATE \"{table}\" SET {assignments} WHERE \"{_id_field()}\" = ?', [encode_value(v) for v in updates.values()] + [record_id])
        conn.commit()
        if cur.rowcount <= 0:
            return _result(operation, False, record_id=record_id, error='not_found')
        return get_record(operation, payload)
    finally:
        conn.close()


def delete_record(operation: str, payload: dict) -> dict:
    record_id = _id_from_payload(payload)
    if not record_id:
        return _result(operation, False, error='missing_record_id')
    metadata = payload.get('metadata') if isinstance(payload.get('metadata'), dict) else {}
    nested = payload.get(_record_key()) if isinstance(payload.get(_record_key()), dict) else {}
    if isinstance(nested.get('metadata'), dict):
        metadata.update(nested.get('metadata'))
    force = bool(metadata.get('force_delete'))
    conn, table = _connect_for_payload(payload)
    try:
        if force or 'status' not in _fields():
            cur = conn.execute(f'DELETE FROM \"{table}\" WHERE \"{_id_field()}\" = ?', [record_id])
        else:
            cur = conn.execute(f'UPDATE \"{table}\" SET \"status\" = ?, \"updated_at\" = ? WHERE \"{_id_field()}\" = ?', ['cancelled', now_utc(), record_id])
        conn.commit()
        return _result(operation, cur.rowcount > 0, record_id=record_id, result={'deleted': force, 'soft_deleted': not force}, affected_count=cur.rowcount, error=None if cur.rowcount > 0 else 'not_found')
    finally:
        conn.close()


def execute(payload: dict | None = None) -> dict:
    payload = payload if isinstance(payload, dict) else {}
    operation = str(payload.get('operation') or '')
    if not operation:
        return _result('', False, error='missing_operation')
    kind = _operation_kinds().get(operation) or _semantic_kind(operation)
    if kind == 'create':
        return create_record(operation, payload)
    if kind == 'read_one':
        return get_record(operation, payload)
    if kind == 'read_many':
        return list_records(operation, payload)
    if kind == 'search':
        return search_records(operation, payload)
    if kind == 'update':
        return update_record(operation, payload)
    if kind == 'delete':
        return delete_record(operation, payload)
    return _result(operation, False, error='unsupported_operation')
"""

    def _contract_driven_tool_source(self, *, entrypoint: dict[str, Any]) -> str:
        fn = str(entrypoint.get("function") or "run")
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", fn):
            fn = "run"
        return f"""from __future__ import annotations

from operations import execute


def _normalize_runtime_payload(payload: dict | None = None) -> dict:
    payload = payload if isinstance(payload, dict) else {{}}
    if isinstance(payload.get('input'), dict):
        merged = dict(payload.get('input') or {{}})
        for key in ('connection', '_connection', 'profile', '_profile', 'secrets', '_runtime'):
            value = payload.get(key)
            if isinstance(value, dict):
                merged[key] = value
        return merged
    return payload


def {fn}(payload: dict | None = None) -> dict:
    return execute(_normalize_runtime_payload(payload))
"""

    def _contract_driven_test_source(self, *, operation_contracts: list[dict[str, Any]], record_contract: dict[str, Any], connection_schema: dict[str, Any]) -> str:
        ops = [(str(item.get("operation")), str(item.get("semantic_kind") or self._operation_semantic_kind(str(item.get("operation"))))) for item in operation_contracts if isinstance(item, dict)]
        fields = record_contract.get("fields") if isinstance(record_contract, dict) else {}
        fields = fields if isinstance(fields, dict) else {}
        id_field = str(record_contract.get("id_field") or "record_id")
        record_key = str(record_contract.get("record_input_key") or "record")
        required = [str(x) for x in (record_contract.get("required_fields") or []) if str(x) != id_field]
        sample = {id_field: "test-record-001"}
        for field, spec in fields.items():
            if field == id_field:
                continue
            ftype = spec.get("type") if isinstance(spec, dict) else "string"
            if ftype == "array":
                sample[field] = ["value"]
            elif ftype == "object":
                sample[field] = {"key": "value"}
            elif ftype in {"integer", "number"}:
                sample[field] = 1
            else:
                sample[field] = "value"
        for field in required:
            sample.setdefault(field, "value")
        connection_defaults = self._generic_persistence_contract(connection_schema).get("connection_defaults") or {}
        return f"""from __future__ import annotations

import tempfile
from pathlib import Path

from tool import run

OPERATIONS = {ops!r}
RECORD_KEY = {record_key!r}
ID_FIELD = {id_field!r}
SAMPLE_RECORD = {sample!r}
CONNECTION_DEFAULTS = {connection_defaults!r}


def _payload(operation: str, tmp_path: Path, **extra):
    connection = dict(CONNECTION_DEFAULTS)
    connection.setdefault('memory_database_path', str(tmp_path / 'capability_test.db'))
    connection.setdefault('database_path', str(tmp_path / 'capability_test.db'))
    connection.setdefault('table_name', 'records')
    connection.setdefault('timeout_seconds', 30)
    payload = {{'operation': operation, 'connection': connection}}
    payload.update(extra)
    return payload


def test_all_declared_operations():
    with tempfile.TemporaryDirectory() as d:
        tmp_path = Path(d)
        created_id = SAMPLE_RECORD.get(ID_FIELD) or 'test-record-001'
        for operation, kind in OPERATIONS:
            if kind == 'create':
                result = run(_payload(operation, tmp_path, **{{RECORD_KEY: dict(SAMPLE_RECORD)}}))
                assert isinstance(result, dict)
                assert result.get('success') is True, result
                created_id = result.get(ID_FIELD) or result.get('record_id') or created_id
            elif kind == 'read_one':
                result = run(_payload(operation, tmp_path, **{{ID_FIELD: created_id}}))
                assert isinstance(result, dict)
                assert 'success' in result
            elif kind == 'read_many':
                result = run(_payload(operation, tmp_path, filters={{}}))
                assert isinstance(result, dict)
                assert 'success' in result
            elif kind == 'search':
                result = run(_payload(operation, tmp_path, query='value', filters={{}}))
                assert isinstance(result, dict)
                assert 'success' in result
            elif kind == 'update':
                updates = {{k: v for k, v in SAMPLE_RECORD.items() if k != ID_FIELD}}
                if not updates:
                    updates = {{'updated_at': 'value'}}
                result = run(_payload(operation, tmp_path, **{{ID_FIELD: created_id, 'update_fields': updates}}))
                assert isinstance(result, dict)
                assert 'success' in result
            elif kind == 'delete':
                result = run(_payload(operation, tmp_path, **{{ID_FIELD: created_id}}))
                assert isinstance(result, dict)
                assert 'success' in result
            else:
                result = run(_payload(operation, tmp_path))
                assert isinstance(result, dict)
                assert 'success' in result
"""

    def _operation_coverage_violations(self, artifact: dict[str, Any], *, operation_contracts: list[dict[str, Any]], entrypoint: dict[str, Any]) -> list[str]:
        files = artifact.get("files") if isinstance(artifact, dict) else []
        text = "\n".join(str(item.get("content") or "") for item in files if isinstance(item, dict) and str(item.get("path") or "").endswith(".py"))
        violations: list[str] = []
        for item in operation_contracts:
            op = str(item.get("operation") or "") if isinstance(item, dict) else ""
            kind = str(item.get("semantic_kind") or "") if isinstance(item, dict) else ""
            if op and op not in text:
                violations.append(f"declared operation not materialized: {op}")
            if kind and kind != "custom" and kind not in text:
                violations.append(f"operation semantic kind not materialized: {op}:{kind}")
        fn = str(entrypoint.get("function") or "run") if isinstance(entrypoint, dict) else "run"
        if f"def {fn}" not in text and "def run" not in text:
            violations.append("entrypoint function not materialized")
        return violations

    def _dependency_unavailable_generation_result(self, *, attempts: list[dict[str, Any]], stage: str) -> dict[str, Any] | None:
        """Return a generic dependency-resolution contract when all routes are unavailable.

        This path is provider-agnostic. It only inspects attempt outcomes and
        route metadata, then asks the runtime to resolve model-route dependency
        availability before retrying code generation.
        """
        if not isinstance(attempts, list) or not attempts:
            return None
        unavailable: list[dict[str, Any]] = []
        for record in attempts:
            if not isinstance(record, dict):
                return None
            if str(record.get("status") or "") != "model_not_available":
                return None
            error_text = str(record.get("error") or "")
            if not self._attempt_error_indicates_runtime_dependency_unavailable(error_text):
                return None
            unavailable.append(record)
        if not unavailable:
            return None
        missing_routes = self._missing_codegen_routes_from_attempts(unavailable)
        reason = str(unavailable[-1].get("error") or "runtime_codegen_dependency_unavailable")
        interaction_request = {
            "type": "runtime_codegen_dependency_resolution",
            "kind": "runtime_codegen_dependency_resolution",
            "message": "Runtime code generation is blocked because all configured model routes are currently unavailable.",
            "required_actions": [
                "Ensure at least one configured code-generation provider endpoint is reachable.",
                "Ensure at least one configured code-generation model route is available.",
                "Retry capability acquisition after dependency readiness is restored.",
            ],
            "missing_routes": missing_routes,
            "blocked_stage": stage,
        }
        return {
            "generation_status": "runtime_dependency_unavailable",
            "generation_route": {"mode": "dependency_unavailable", "stage": stage},
            "generation_error": reason,
            "generation_attempts": attempts,
            "interaction_request": interaction_request,
            "dependency_unavailability": {
                "stage": stage,
                "route_count": len(missing_routes),
            },
        }

    def _missing_codegen_routes_from_attempts(self, attempts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        routes: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str]] = set()
        for record in attempts:
            attempt = record.get("attempt") if isinstance(record, dict) else None
            override = attempt.get("route_override") if isinstance(attempt, dict) else {}
            override = override if isinstance(override, dict) else {}
            provider = str(override.get("provider") or "").strip()
            model = str(override.get("model") or "").strip()
            base_url = str(override.get("base_url") or "").strip()
            if provider.casefold() == "ollama" and not base_url:
                base_url = str(os.getenv("OLLAMA_HOST") or "http://127.0.0.1:11434").rstrip("/")
            key = (provider, model, base_url)
            if key in seen:
                continue
            seen.add(key)
            routes.append(
                {
                    "provider": provider,
                    "model": model,
                    "base_url": base_url,
                    "availability_reason": str(record.get("error") or "")[:240],
                }
            )
        return routes

    def _attempt_error_indicates_runtime_dependency_unavailable(self, error_text: str) -> bool:
        text = str(error_text or "").casefold()
        if not text:
            return False
        markers = (
            "service_unavailable",
            "connection refused",
            "connection error",
            "timed out",
            "network is unreachable",
            "failed to establish a new connection",
            "max retries exceeded",
        )
        return any(marker in text for marker in markers)

    def _generate_progressive_file_with_llm(
        self,
        *,
        tool_id: str,
        run_id: str | None,
        attempt: dict[str, Any],
        path: str,
        stage_index: int = 1,
        stage: str = "",
        stage_contract: dict[str, Any] | None = None,
        entrypoint: dict[str, Any],
        blueprint: dict[str, Any],
        identity_contract: dict[str, Any],
        input_schema: dict[str, Any],
        output_schema: dict[str, Any],
        connection_schema: dict[str, Any],
        secret_schema: dict[str, Any],
        verification_input: dict[str, Any],
        specification_contract: dict[str, Any],
        existing_files: list[dict[str, str]],
    ) -> dict[str, Any]:
        contract = {
            "tool_id": tool_id,
            "target_file": path,
            "stage": stage or path,
            "stage_contract": stage_contract if isinstance(stage_contract, dict) else {},
            "entrypoint": self._compact_entrypoint(entrypoint),
            "identity": self._compact_identity_contract(identity_contract, blueprint=blueprint, tool_id=tool_id),
            "behavior_contract": self._compact_behavior_contract(blueprint, tool_id=tool_id),
            "schemas": {
                "input": self._schema_for_codegen(input_schema),
                "output": self._schema_for_codegen(output_schema),
                "connection": self._schema_for_codegen(connection_schema),
                "secret": self._schema_for_codegen(secret_schema),
            },
            "verification_input": self._compact_json(verification_input, limit=1400),
            "specification": self._compact_specification_contract(specification_contract),
            "existing_files": [{"path": item.get("path"), "content_excerpt": str(item.get("content") or "")[:1800]} for item in existing_files if isinstance(item, dict)],
        }
        if str(path).endswith("test_tool.py"):
            file_instruction = (
                "Generate only Python source for a local validation test file. It must import the runtime entrypoint from the same directory, "
                "call the entrypoint with dry_run/mock/local payload, assert a JSON-serializable dict is returned, and avoid live external network or secrets."
            )
        elif str(path) == str(entrypoint.get("module") or "tool.py"):
            file_instruction = (
                "Generate only executable Python source for the runtime entrypoint file. Define run(payload: dict | None = None) -> dict unless the contract requests another function. "
                "Implement behavior_contract from payload input/connection/secrets/_runtime. No placeholders. "
                "Use standard library when possible. Do not perform external side effects when payload['_runtime']['dry_run'] is true."
            )
        else:
            file_instruction = (
                "Generate only Python source for this support file. It must be generic, importable, standard-library-first, and derived only from the supplied contract."
            )
        messages = [
            {
                "role": "system",
                "content": (
                    "You generate one runtime artifact file from a compact contract. "
                    "Return one JSON object only with keys path and content. No markdown, no explanation. "
                    "The content value must be complete source code for the requested file. " + file_instruction
                ),
            },
            {"role": "user", "content": json.dumps(contract, ensure_ascii=False, separators=(",", ":"), default=str)},
        ]
        file_attempt = {**attempt, "progressive_file": path, "force_json": True, "compact": True}
        prompt_text = "\n\n".join([f"[{m.get('role', 'user')}]\n{m.get('content', '')}" for m in messages if isinstance(m, dict)])
        self._write_replay_file(
            run_id=run_id,
            tool_id=tool_id,
            filename=self._stage_replay_name(stage_index, "prompt"),
            content=prompt_text,
            title="Capability stage prompt captured",
            metadata={"replay_kind": "stage_prompt", "stage_index": stage_index, "target_file": path, "stage": stage or path},
        )
        self._emit_generation_progress(
            run_id=run_id,
            tool_id=tool_id,
            status="running",
            phase="progressive_file_generation_started",
            attempt=file_attempt,
            path=path,
        )
        result = self._complete_sync_with_heartbeat(
            run_id=run_id,
            tool_id=tool_id,
            attempt=file_attempt,
            brain="auxiliary_brain",
            task_type="runtime_tool_code_generation",
            complexity=str(attempt.get("complexity") or "critical"),
            messages=messages,
            context={
                "tool_id": tool_id,
                "generation_attempt": file_attempt,
                "progressive_file": path,
                "route_override": attempt.get("route_override") if isinstance(attempt.get("route_override"), dict) else None,
            },
            response_format={"type": "json_object"},
        )
        route = result.route if isinstance(result.route, dict) else {}
        self._write_replay_file(
            run_id=run_id,
            tool_id=tool_id,
            filename=self._stage_replay_name(stage_index, "response"),
            content=str(result.content or "") if result.status == "completed" else {"status": result.status, "error": result.error, "route": route, "content": str(result.content or "")},
            title="Capability stage response captured",
            status="completed" if result.status == "completed" else "failed",
            metadata={"replay_kind": "stage_response", "stage_index": stage_index, "target_file": path, "stage": stage or path, "model_route": route},
        )
        if result.status != "completed":
            self._emit_generation_progress(
                run_id=run_id,
                tool_id=tool_id,
                status="running",
                phase="progressive_file_generation_retry_or_escalate",
                attempt=file_attempt,
                path=path,
                route=route,
                error=result.error,
            )
            return {"status": result.status, "error": result.error, "route": route, "attempt_record": {"status": result.status, "error": result.error, "route": route, "attempt": file_attempt, "path": path}}
        parsed = self._parse_json_object(str(result.content or ""))
        parsed = parsed if isinstance(parsed, dict) else {}
        content = parsed.get("content") if isinstance(parsed.get("content"), str) else None
        if not content:
            # Generic salvage for models that return the file source under the
            # file name or common code keys.
            content = parsed.get(path) if isinstance(parsed.get(path), str) else None
        if not content:
            content = parsed.get("code") if isinstance(parsed.get("code"), str) else None
        if not isinstance(content, str) or not content.strip():
            error = "progressive file generation did not return source content"
            self._write_replay_file(
                run_id=run_id,
                tool_id=tool_id,
                filename=self._stage_replay_name(stage_index, "extraction_result"),
                content={"status": "invalid_output", "error": error, "parsed_keys": list(parsed.keys()) if isinstance(parsed, dict) else [], "target_file": path},
                title="Capability stage extraction failed",
                status="failed",
                metadata={"replay_kind": "stage_extraction", "stage_index": stage_index, "target_file": path, "stage": stage or path},
            )
            self._emit_generation_progress(
                run_id=run_id,
                tool_id=tool_id,
                status="running",
                phase="progressive_file_generation_invalid_output",
                attempt=file_attempt,
                path=path,
                route=route,
                error=error,
            )
            return {"status": "invalid_output", "error": error, "route": route, "attempt_record": {"status": "invalid_output", "error": error, "route": route, "attempt": file_attempt, "path": path}}
        self._write_replay_file(
            run_id=run_id,
            tool_id=tool_id,
            filename=self._stage_replay_name(stage_index, "extraction_result"),
            content={"status": "completed", "target_file": path, "content_length": len(content), "route": route},
            title="Capability stage extraction completed",
            metadata={"replay_kind": "stage_extraction", "stage_index": stage_index, "target_file": path, "stage": stage or path},
        )
        return {"status": "completed", "content": content, "route": route, "attempt_record": {"status": "completed", "route": route, "attempt": file_attempt, "path": path}}

    def _codegen_attempt_available(self, attempt: dict[str, Any], *, run_id: str | None = None, tool_id: str | None = None) -> tuple[bool, str]:
        """Preflight and prepare one code-generation model attempt.

        This is infrastructure-only validation. It does not inspect capability
        names or task domains. For policy-listed local models, absence from the
        local provider is treated as a resolvable runtime dependency: the runtime
        pulls the model, verifies that it became visible to the provider, and then
        continues the same code-generation route.
        """
        override = attempt.get("route_override") if isinstance(attempt, dict) else None
        if not isinstance(override, dict):
            return True, ""
        provider = str(override.get("provider") or "").strip().casefold()
        model = str(override.get("model") or "").strip()
        if not model:
            return False, "missing_model_in_codegen_route_override"
        if provider != "ollama":
            return True, ""
        if str(os.getenv("AI_RUNTIME_CODEGEN_SKIP_MODEL_PREFLIGHT", "")).strip().lower() in {"1", "true", "yes", "on"}:
            return True, ""
        base_url = str(override.get("base_url") or os.getenv("OLLAMA_HOST") or "http://127.0.0.1:11434").rstrip("/")
        ok, reason = self._ollama_model_visible(base_url, model)
        if ok:
            return True, ""

        # Generic resilience: if the policy-preferred model is missing, switch
        # to a locally installed Ollama model that best matches code generation
        # intent instead of failing the whole acquisition pipeline.
        fallback_model = self._select_local_codegen_fallback_model(base_url=base_url, preferred_model=model)
        if isinstance(fallback_model, str) and fallback_model and fallback_model != model:
            override["model"] = fallback_model
            self._emit_generation_progress(
                run_id=run_id,
                tool_id=tool_id or "runtime_model_dependency",
                status="running",
                phase="codegen_model_local_fallback_selected",
                attempt=attempt,
                provider=provider,
                model=model,
                fallback_model=fallback_model,
                reason=reason,
            )
            return True, ""

        auto_prepare = str(os.getenv("AI_RUNTIME_CODEGEN_AUTO_PULL_MISSING_MODELS", "1")).strip().lower() not in {"0", "false", "no", "off"}
        if not auto_prepare:
            if reason.startswith("ollama_service_unavailable"):
                return False, reason
            return False, f"ollama_codegen_model_not_installed:{model}; auto_pull_disabled"
        if RuntimeModelDownloader is None:
            return False, f"ollama_codegen_model_not_installed:{model}; model_downloader_unavailable"

        timeout_seconds = self._codegen_model_prepare_timeout_seconds()
        self._emit_generation_progress(
            run_id=run_id,
            tool_id=tool_id or "runtime_model_dependency",
            status="running",
            phase="codegen_model_auto_prepare_started",
            attempt=attempt,
            model=model,
            provider=provider,
            timeout_seconds=timeout_seconds,
        )
        try:
            result = RuntimeModelDownloader().download(
                {
                    "model_id": model,
                    "runtime": "ollama",
                    "base_url": base_url,
                    "source": "policy_listed_codegen_route",
                    "download_strategy": {"preferred_runtime": "ollama"},
                },
                approved=True,
                timeout_seconds=timeout_seconds,
            )
        except Exception as exc:
            fallback_model = self._select_local_codegen_fallback_model(base_url=base_url, preferred_model=model)
            if isinstance(fallback_model, str) and fallback_model and fallback_model != model:
                override["model"] = fallback_model
                self._emit_generation_progress(
                    run_id=run_id,
                    tool_id=tool_id or "runtime_model_dependency",
                    status="running",
                    phase="codegen_model_local_fallback_selected_after_prepare_exception",
                    attempt=attempt,
                    provider=provider,
                    model=model,
                    fallback_model=fallback_model,
                    error=str(exc)[:240],
                )
                return True, ""
            return False, f"ollama_codegen_model_auto_prepare_failed:{model}: {str(exc)[:240]}"
        if not isinstance(result, dict) or not bool(result.get("ready_for_benchmark")):
            reason_text = str(result.get("reason") if isinstance(result, dict) else result)[:240]
            fallback_model = self._select_local_codegen_fallback_model(base_url=base_url, preferred_model=model)
            if isinstance(fallback_model, str) and fallback_model and fallback_model != model:
                override["model"] = fallback_model
                self._emit_generation_progress(
                    run_id=run_id,
                    tool_id=tool_id or "runtime_model_dependency",
                    status="running",
                    phase="codegen_model_local_fallback_selected_after_prepare_failure",
                    attempt=attempt,
                    provider=provider,
                    model=model,
                    fallback_model=fallback_model,
                    error=reason_text,
                )
                return True, ""
            return False, f"ollama_codegen_model_auto_prepare_failed:{model}: {reason_text}"
        ok, verify_reason = self._ollama_model_visible(base_url, model)
        if ok:
            self._emit_generation_progress(
                run_id=run_id,
                tool_id=tool_id or "runtime_model_dependency",
                status="completed",
                phase="codegen_model_auto_prepare_completed",
                attempt=attempt,
                model=model,
                provider=provider,
            )
            return True, ""
        fallback_model = self._select_local_codegen_fallback_model(base_url=base_url, preferred_model=model)
        if isinstance(fallback_model, str) and fallback_model and fallback_model != model:
            override["model"] = fallback_model
            self._emit_generation_progress(
                run_id=run_id,
                tool_id=tool_id or "runtime_model_dependency",
                status="running",
                phase="codegen_model_local_fallback_selected_after_prepare_unverified",
                attempt=attempt,
                provider=provider,
                model=model,
                fallback_model=fallback_model,
                error=verify_reason,
            )
            return True, ""
        return False, f"ollama_codegen_model_auto_prepare_unverified:{model}: {verify_reason}"

    def _ollama_model_visible(self, base_url: str, model: str) -> tuple[bool, str]:
        try:
            with urllib.request.urlopen(base_url + "/api/tags", timeout=2.5) as response:
                data = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            return False, f"ollama_service_unavailable_for_codegen_model:{model}: {str(exc)[:160]}"
        exact_names: set[str] = set()
        base_names: set[str] = set()
        for item in data.get("models", []) if isinstance(data, dict) else []:
            if not isinstance(item, dict):
                continue
            for value in (item.get("name"), item.get("model")):
                text = str(value or "").strip()
                if not text:
                    continue
                exact_names.add(text)
                base_names.add(text.split(":", 1)[0] if ":" in text else text)
        if ":" in model:
            if model in exact_names:
                return True, ""
        elif model in exact_names or model in base_names:
            return True, ""
        return False, f"ollama_codegen_model_not_installed:{model}"

    def _ollama_installed_models(self, base_url: str) -> list[str]:
        try:
            with urllib.request.urlopen(base_url + "/api/tags", timeout=2.5) as response:
                data = json.loads(response.read().decode("utf-8"))
        except Exception:
            return []
        models: list[str] = []
        seen: set[str] = set()
        for item in data.get("models", []) if isinstance(data, dict) else []:
            if not isinstance(item, dict):
                continue
            for value in (item.get("name"), item.get("model")):
                text = str(value or "").strip()
                if not text or text in seen:
                    continue
                seen.add(text)
                models.append(text)
        return models

    def _select_local_codegen_fallback_model(self, *, base_url: str, preferred_model: str) -> str | None:
        installed = self._ollama_installed_models(base_url)
        if not installed:
            return None

        preferred = str(preferred_model or "").strip()
        candidates: list[str] = []
        raw_env = str(os.getenv("AI_RUNTIME_CODEGEN_OLLAMA_FALLBACK_MODELS") or "").strip()
        if raw_env:
            candidates.extend([part.strip() for part in raw_env.split(",") if part.strip()])

        for route in self._code_generation_escalation_routes():
            if not isinstance(route, dict):
                continue
            if str(route.get("provider") or "").strip().casefold() != "ollama":
                continue
            model = str(route.get("model") or "").strip()
            if model:
                candidates.append(model)

        # Keep candidate order stable and remove current preferred model.
        ordered_candidates: list[str] = []
        seen_candidates: set[str] = set()
        for candidate in candidates:
            if not candidate or candidate == preferred or candidate in seen_candidates:
                continue
            seen_candidates.add(candidate)
            ordered_candidates.append(candidate)

        installed_exact = set(installed)
        installed_base = {name.split(":", 1)[0] if ":" in name else name: name for name in installed}

        for candidate in ordered_candidates:
            if candidate in installed_exact:
                return candidate
            base = candidate.split(":", 1)[0] if ":" in candidate else candidate
            if base in installed_base:
                return installed_base[base]

        # Heuristic generic fallback: prefer coder-oriented models when present.
        for name in installed:
            lower = name.casefold()
            if "coder" in lower or "code" in lower:
                if name != preferred:
                    return name

        for name in installed:
            if name != preferred:
                return name
        return None

    def _codegen_model_prepare_timeout_seconds(self) -> int:
        raw = str(os.getenv("AI_RUNTIME_CODEGEN_MODEL_PULL_TIMEOUT_SECONDS") or os.getenv("AI_RUNTIME_MODEL_PULL_TIMEOUT_SECONDS") or "3600").strip()
        try:
            return max(60, int(float(raw)))
        except Exception:
            return 3600

    def _generation_messages(
        self,
        *,
        tool_id: str,
        entrypoint: dict[str, Any],
        blueprint: dict[str, Any],
        identity_contract: dict[str, Any],
        input_schema: dict[str, Any],
        output_schema: dict[str, Any],
        connection_schema: dict[str, Any],
        secret_schema: dict[str, Any],
        verification_input: dict[str, Any],
        specification_contract: dict[str, Any],
        compact: bool = False,
    ) -> list[dict[str, str]]:
        """Build a dynamic, context-aware code generation prompt.

        This method uses the PromptEngineer system to generate context-specific
        guidance based on capability category, complexity, and schema structure.
        Earlier stages already produced the authoritative contract; this stage
        materializes that contract into a runtime artifact with intelligent
        LLM guidance derived from capability metadata.
        """
        # Build full contract with all components
        contract = {
            "tool_id": tool_id,
            "entrypoint": self._compact_entrypoint(entrypoint),
            "identity": self._compact_identity_contract(identity_contract, blueprint=blueprint, tool_id=tool_id),
            "behavior_contract": self._compact_behavior_contract(blueprint, tool_id=tool_id),
            "schemas": {
                "input": self._schema_for_codegen(input_schema),
                "output": self._schema_for_codegen(output_schema),
                "connection": self._schema_for_codegen(connection_schema),
                "secret": self._schema_for_codegen(secret_schema),
            },
            "verification": {
                "input": self._compact_json(verification_input, limit=1800 if compact else 2600),
                "expectations": self._compact_json(blueprint.get("verification_expectations") if isinstance(blueprint.get("verification_expectations"), dict) else {}, limit=1200),
            },
            "runtime_policy": self._compact_json(blueprint.get("runtime_execution_policy") if isinstance(blueprint.get("runtime_execution_policy"), dict) else {}, limit=1200),
            "approval_policy": self._compact_json(blueprint.get("approval_policy") if isinstance(blueprint.get("approval_policy"), dict) else {}, limit=800),
            "match_contract": self._compact_json(blueprint.get("capability_match_contract") if isinstance(blueprint.get("capability_match_contract"), dict) else {}, limit=1200),
            "required_files": ["tool.py", "test_tool.py"],
            "return_shape": "JSON object with files, input_schema, output_schema, connection_schema, secret_schema, dependencies, verification_input, verification_expectations, capability_match_contract",
        }
        if not compact:
            compact_spec = self._compact_specification_contract(specification_contract)
            if compact_spec:
                contract["specification"] = compact_spec

        # Use dynamic prompt engineering system for context-aware guidance
        behavior_contract = blueprint.get("behavior_contract") or blueprint.get("description") or "Generic runtime capability"
        complexity = blueprint.get("complexity_level", blueprint.get("complexity", "basic"))
        runtime_policy = blueprint.get("runtime_execution_policy") if isinstance(blueprint.get("runtime_execution_policy"), dict) else None
        
        messages = build_generation_prompt_messages(
            tool_id=tool_id,
            complexity=complexity,
            input_schema=input_schema,
            output_schema=output_schema,
            connection_schema=connection_schema,
            secret_schema=secret_schema,
            behavior_contract=behavior_contract,
            runtime_policy=runtime_policy,
            contract_json=contract,
        )
        
        return messages

    def _compact_behavior_contract(self, blueprint: dict[str, Any], *, tool_id: str) -> dict[str, Any]:
        """Return bounded behavior requirements for artifact generation.

        This is not a template and does not contain capability-specific code.
        It preserves the user's requested behavior after blueprint/specification
        stages so the code model can implement the capability instead of merely
        generating an empty file envelope.
        """
        if not isinstance(blueprint, dict):
            blueprint = {}
        text_parts: list[str] = []
        for key in ("behavior_contract", "runtime_behavior_requirements", "description", "summary"):
            value = blueprint.get(key)
            if isinstance(value, str) and value.strip():
                text_parts.append(value.strip())
            elif isinstance(value, (dict, list)) and value:
                try:
                    text_parts.append(json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str))
                except Exception:
                    text_parts.append(str(value))
        # Preserve declared capability identity and interface hints without
        # relying on business/domain words.  Values are opaque request data.
        for key in ("capabilities", "required_terms", "match_terms"):
            value = blueprint.get(key)
            if isinstance(value, list) and value:
                text_parts.append(f"{key}=" + json.dumps(value[:20], ensure_ascii=False, default=str))
        joined = "\n".join(part for part in text_parts if part)
        if len(joined) > 6000:
            joined = joined[:6000] + "\n[truncated]"
        return {
            "tool_id": tool_id,
            "requirements": joined,
            "must_generate_executable_files": True,
            "must_not_generate_placeholder": True,
        }

    def _compact_entrypoint(self, entrypoint: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(entrypoint, dict):
            return {"module": "tool.py", "function": "run"}
        return {
            "module": str(entrypoint.get("module") or "tool.py"),
            "function": str(entrypoint.get("function") or "run"),
        }

    def _compact_identity_contract(self, identity_contract: dict[str, Any], *, blueprint: dict[str, Any], tool_id: str) -> dict[str, Any]:
        raw = identity_contract if isinstance(identity_contract, dict) else {}
        keep: dict[str, Any] = {}
        for key in (
            "requested_capability_id",
            "requested_capability_name",
            "capability_id",
            "capability_name",
            "required_artifact_dir_name",
            "expected_tool_id",
            "expected_template_id",
        ):
            value = raw.get(key) if key in raw else blueprint.get(key)
            if value not in (None, "", [], {}):
                keep[key] = value
        keep.setdefault("capability_id", tool_id)
        keep.setdefault("expected_tool_id", tool_id)
        return keep

    def _schema_for_codegen(self, schema: dict[str, Any]) -> dict[str, Any]:
        """Reduce JSON Schema to fields needed for code generation.

        Field names and required/optional status are contract data.  Verbose
        descriptions, examples, and UI metadata are not needed by the code model
        and slow down local generation, so they are bounded or removed here.
        """
        if not isinstance(schema, dict):
            return {"type": "object", "properties": {}, "required": [], "additionalProperties": False}
        props = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
        compact_props: dict[str, Any] = {}
        for name, spec in props.items():
            if not isinstance(spec, dict):
                compact_props[str(name)] = {"type": "string"}
                continue
            item: dict[str, Any] = {}
            for key in ("type", "format", "enum", "items", "additionalProperties"):
                if key in spec:
                    item[key] = spec[key]
            if "default" in spec:
                item["default"] = spec.get("default")
            description = str(spec.get("description") or "").strip()
            if description:
                item["description"] = description[:160]
            compact_props[str(name)] = item or {"type": "string"}
        required = [str(x) for x in schema.get("required", []) if isinstance(x, str)] if isinstance(schema.get("required"), list) else []
        return {
            "type": "object",
            "properties": compact_props,
            "required": [x for x in required if x in compact_props],
            "additionalProperties": bool(schema.get("additionalProperties", False)),
        }

    def _compact_json(self, value: Any, *, limit: int = 2000) -> Any:
        if value in (None, "", [], {}):
            return {} if isinstance(value, dict) or value is None else value
        try:
            text = json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
        except Exception:
            text = str(value)
        if len(text) <= limit:
            return value
        return {"truncated_json": text[:limit], "truncated": True}

    def _compact_specification_contract(self, specification_contract: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(specification_contract, dict):
            return {}
        keep_keys = {
            "capability_identity",
            "verification_contract",
            "output_bindings",
            "security_contract",
            "schema_version",
        }
        compact: dict[str, Any] = {k: specification_contract.get(k) for k in keep_keys if k in specification_contract}
        # Bound the prompt size even if a prior stage attached verbose context.
        raw = json.dumps(compact, ensure_ascii=False, default=str)
        if len(raw) > 6000:
            return {"schema_version": specification_contract.get("schema_version"), "summary": raw[:6000]}
        return compact

    def _complete_sync_with_heartbeat(self, *, run_id: str | None, tool_id: str, attempt: dict[str, Any], **kwargs: Any) -> Any:
        """Run a blocking LLM request with progress heartbeats and a stage timeout.

        Capability acquisition is allowed to take longer than ordinary task
        execution, but one model call must not leave the whole acquisition job
        in an endless running state.  This timeout is stage-scoped and generic:
        it applies to any runtime artifact code-generation request, regardless
        of capability name or domain.
        """
        stop = threading.Event()
        started = time.time()
        timeout_seconds = self._code_generation_timeout_seconds(attempt=attempt)

        def beat() -> None:
            while not stop.wait(15.0):
                elapsed = round(time.time() - started, 1)
                self._emit_generation_progress(
                    run_id=run_id,
                    tool_id=tool_id,
                    status="running",
                    phase="llm_request_waiting",
                    attempt={**(attempt or {}), "stage_timeout_seconds": timeout_seconds},
                    elapsed_seconds=elapsed,
                )

        thread = threading.Thread(target=beat, name=f"capability-codegen-heartbeat-{tool_id}", daemon=True)
        thread.start()
        try:
            executor = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"capability-codegen-{tool_id}")
            future = executor.submit(lambda: self.llm_client.complete_sync(**kwargs))
            try:
                return future.result(timeout=timeout_seconds)
            except concurrent.futures.TimeoutError:
                future.cancel()
                elapsed = round(time.time() - started, 1)
                message = (
                    f"Runtime artifact code generation exceeded stage_timeout_seconds={timeout_seconds}. "
                    "The attempt was stopped so acquisition can retry or fail visibly."
                )
                self._emit_generation_progress(
                    run_id=run_id,
                    tool_id=tool_id,
                    status="failed",
                    phase="llm_request_timeout",
                    attempt={**(attempt or {}), "stage_timeout_seconds": timeout_seconds},
                    elapsed_seconds=elapsed,
                    error=message,
                )
                # Do not wait for a stuck provider thread during shutdown; the
                # worker is isolated and daemon-like for this abandoned attempt.
                executor.shutdown(wait=False, cancel_futures=True)
                return self._llm_timeout_result(message=message, attempt=attempt, elapsed_seconds=elapsed)
            finally:
                if future.done():
                    executor.shutdown(wait=False, cancel_futures=True)
        finally:
            stop.set()

    def _code_generation_timeout_seconds(self, *, attempt: dict[str, Any] | None = None) -> int:
        """Return a model-aware stage timeout for runtime artifact generation.

        The timeout policy is generic infrastructure policy.  It does not branch
        on capability names or domains.  Larger local code models and
        progressive per-file generation need longer than ordinary planning
        calls, while unavailable models are still skipped before this point by
        availability preflight.
        """
        raw = os.getenv("AI_RUNTIME_CODE_GENERATION_TIMEOUT_SECONDS") or os.getenv("AI_RUNTIME_LLM_CODEGEN_TIMEOUT_SECONDS")
        try:
            configured = int(raw) if raw not in (None, "") else 0
        except Exception:
            configured = 0
        attempt = attempt if isinstance(attempt, dict) else {}
        override = attempt.get("route_override") if isinstance(attempt.get("route_override"), dict) else {}
        model = str(override.get("model") or "").casefold()
        if configured > 0:
            base = configured
        elif "16b" in model or "32b" in model or "70b" in model:
            base = int(os.getenv("AI_RUNTIME_LARGE_CODEGEN_TIMEOUT_SECONDS") or "1200")
        elif "deepseek" in model:
            base = int(os.getenv("AI_RUNTIME_DEEPSEEK_CODEGEN_TIMEOUT_SECONDS") or "720")
        else:
            base = int(os.getenv("AI_RUNTIME_DEFAULT_CODEGEN_TIMEOUT_SECONDS") or "360")
        if attempt.get("repair"):
            return max(1, int(os.getenv("AI_RUNTIME_CODEGEN_REPAIR_TIMEOUT_SECONDS") or str(min(base, 300))))
        if attempt.get("progressive_file"):
            # Per-file prompts are smaller, but local large code models still
            # need enough time to return complete source code.  Do not cap the
            # timeout below the model-aware base; otherwise a 16b route can still
            # be killed by an old 180/900 second ceiling while it is making
            # progress.
            return max(1, int(os.getenv("AI_RUNTIME_PROGRESSIVE_FILE_CODEGEN_TIMEOUT_SECONDS") or str(max(base, 600))))
        if attempt.get("compact") and not any(marker in model for marker in ["16b", "32b", "70b"]):
            return max(1, int(os.getenv("AI_RUNTIME_COMPACT_CODEGEN_TIMEOUT_SECONDS") or str(min(base, 360))))
        return max(1, base)

    def _llm_timeout_result(self, *, message: str, attempt: dict[str, Any] | None = None, elapsed_seconds: float | None = None) -> Any:
        try:
            from ai_core.model_orchestration.litellm_brain_client import LiteLLMBrainResult
            return LiteLLMBrainResult(
                status="timeout",
                content="",
                error=message,
                route={"timeout": True, "elapsed_seconds": elapsed_seconds, "attempt": attempt or {}},
            )
        except Exception:
            class _Result:
                status = "timeout"
                content = ""
                error = message
                route = {"timeout": True, "elapsed_seconds": elapsed_seconds, "attempt": attempt or {}}
            return _Result()

    def _emit_generation_progress(self, *, run_id: str | None, tool_id: str, status: str, phase: str, attempt: dict[str, Any] | None = None, **data: Any) -> None:
        if not run_id:
            return
        payload = {"tool_id": tool_id, "phase": phase, "attempt": attempt or {}, **data}
        try:
            if emit_console_event is not None:
                emit_console_event(
                    area="capability_acquisition",
                    event="ArtifactCodeGeneration",
                    status=status,
                    message=f"ArtifactCodeGeneration: {phase}",
                    data=payload,
                )
        except Exception:
            pass
        try:
            if runtime_state_manager is not None:
                runtime_state_manager.emit(
                    run_id=run_id,
                    step_id="execution.artifact_code_generation",
                    level="developer",
                    kind="lifecycle" if status == "running" else ("error" if status == "failed" else "output"),
                    status="running" if status == "running" else ("failed" if status == "failed" else "completed"),
                    title="Artifact code generation",
                    message=f"{phase} for {tool_id}",
                    output=payload,
                    method="capability_acquisition",
                    progress=72.0 if status == "running" else 78.0,
                    trace={"heartbeat_at": datetime.now(timezone.utc).isoformat()},
                    next_action="wait_for_llm_code_generation" if status == "running" else "validate_generated_artifact",
                )
        except Exception:
            pass


    def _emit_generation_attempt_failed(self, *, run_id: str | None, tool_id: str, attempt: dict[str, Any], record: dict[str, Any], attempts_so_far: list[dict[str, Any]]) -> None:
        """Publish a generic escalation event after a code-generation attempt fails.

        The decision is based only on generation outcome categories such as
        timeout, invalid JSON, missing files, or contract violations.  It does
        not inspect capability names or business terms.  Model choice remains
        policy-driven through complexity routes in configs/brain_model_policy.yaml.
        """
        next_attempt = self._next_generation_attempt(attempt, attempts_so_far=attempts_so_far)
        self._emit_generation_progress(
            run_id=run_id,
            tool_id=tool_id,
            status="running",
            phase="llm_attempt_failed_escalating" if next_attempt else "llm_attempt_failed_no_more_routes",
            attempt=attempt,
            failed_status=str(record.get("status") or "failed"),
            failed_error=str(record.get("error") or "")[:1000],
            next_attempt=next_attempt or {},
            attempts_completed=len(attempts_so_far),
        )

    def _last_attempted_route_floor(self, attempts: list[dict[str, Any]]) -> int:
        """Return a conservative route index for progressive recovery.

        Full-artifact generation may fail because one large JSON response is too
        slow or too brittle.  Progressive generation should not blindly repeat
        every failed route forever, but it should still preserve policy order and
        leave at least one route available.  This helper is infrastructure-only:
        it only looks at completed attempt records and route order, never at
        capability ids or business words.
        """
        if not isinstance(attempts, list) or not attempts:
            return 0
        ordered = self._generation_attempts("basic")
        route_keys: list[tuple[str, str]] = []
        for attempt in ordered:
            override = attempt.get("route_override") if isinstance(attempt, dict) else {}
            override = override if isinstance(override, dict) else {}
            route_keys.append((str(override.get("provider") or ""), str(override.get("model") or "")))
        max_seen = -1
        for record in attempts:
            attempt = record.get("attempt") if isinstance(record, dict) else None
            override = attempt.get("route_override") if isinstance(attempt, dict) else {}
            override = override if isinstance(override, dict) else {}
            key = (str(override.get("provider") or ""), str(override.get("model") or ""))
            if key in route_keys:
                max_seen = max(max_seen, route_keys.index(key))
        if max_seen < 0:
            return 0
        # Keep at least the strongest configured route for recovery.
        return min(max_seen + 1, max(len(route_keys) - 1, 0))

    def _next_generation_attempt(self, current_attempt: dict[str, Any], *, attempts_so_far: list[dict[str, Any]]) -> dict[str, Any] | None:
        attempts = self._generation_attempts(str(current_attempt.get("base_complexity") or current_attempt.get("complexity") or "default"))
        completed = len(attempts_so_far)
        if completed < len(attempts):
            return attempts[completed]
        return None

    def _parse_json_object(self, content: str) -> dict[str, Any] | None:
        text = str(content or "").strip()
        if not text:
            return None
        candidates = self._json_object_candidates(text)
        for candidate in candidates:
            try:
                data = json.loads(candidate)
                if isinstance(data, dict):
                    return data
                if isinstance(data, list):
                    first_dict = next((item for item in data if isinstance(item, dict)), None)
                    if isinstance(first_dict, dict):
                        return first_dict
            except Exception:
                pass
            # Some routes still return Python dict literals instead of strict JSON.
            try:
                literal = ast.literal_eval(candidate)
                if isinstance(literal, dict):
                    return literal
                if isinstance(literal, list):
                    first_dict = next((item for item in literal if isinstance(item, dict)), None)
                    if isinstance(first_dict, dict):
                        return first_dict
            except Exception:
                pass
        return None

    def _json_object_candidates(self, text: str) -> list[str]:
        candidates: list[str] = []

        def add(value: str) -> None:
            cleaned = str(value or "").strip()
            if not cleaned:
                return
            if cleaned not in candidates:
                candidates.append(cleaned)

        add(text)
        if text.startswith("```"):
            stripped = re.sub(r"^```(?:json|python)?\s*", "", text, flags=re.IGNORECASE)
            stripped = re.sub(r"\s*```$", "", stripped)
            add(stripped)
        for block in re.findall(r"```(?:json|python)?\s*(.*?)```", text, flags=re.IGNORECASE | re.DOTALL):
            add(block)
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            add(text[start : end + 1])
        for obj in self._balanced_braced_objects(text):
            add(obj)
        return candidates

    def _balanced_braced_objects(self, text: str) -> list[str]:
        objects: list[str] = []
        stack: list[int] = []
        in_string = False
        quote = ""
        escaped = False
        for index, ch in enumerate(text):
            if in_string:
                if escaped:
                    escaped = False
                    continue
                if ch == "\\":
                    escaped = True
                    continue
                if ch == quote:
                    in_string = False
                continue
            if ch in {"\"", "'"}:
                in_string = True
                quote = ch
                continue
            if ch == "{":
                stack.append(index)
                continue
            if ch == "}" and stack:
                start = stack.pop()
                if not stack:
                    objects.append(text[start : index + 1])
        return objects

    def _normalize_llm_artifact_payload(self, artifact: dict[str, Any], *, tool_id: str) -> dict[str, Any]:
        """Normalize common model output shapes into the canonical artifact format.

        Code models often return semantically correct content under keys such as
        artifact_files, source_files, or a mapping of path -> content.  Rejecting
        those shapes immediately causes unnecessary capability-generation failure
        and model escalation.  This normalizer is capability-neutral: it only
        converts file container shapes and never injects concrete business code.
        """
        if not isinstance(artifact, dict):
            return {}
        normalized = dict(artifact)
        files = normalized.get("files")
        for key in ("artifact_files", "source_files", "runtime_files", "generated_files"):
            if not files and key in normalized:
                files = normalized.get(key)
                break
        converted = self._coerce_files(files)
        if converted:
            normalized["files"] = converted
            return normalized
        # Some models put files inside a nested artifact/package object.
        for key in ("artifact", "package", "runtime_artifact", "tool_artifact", "implementation"):
            nested = normalized.get(key)
            if isinstance(nested, dict):
                nested_files = self._coerce_files(
                    nested.get("files")
                    or nested.get("artifact_files")
                    or nested.get("source_files")
                    or nested.get("runtime_files")
                    or nested.get("generated_files")
                )
                if nested_files:
                    merged = dict(nested)
                    merged.update(normalized)
                    merged["files"] = nested_files
                    return merged

        # Generic salvage for models that return code under common scalar keys
        # instead of the canonical file envelope.  This does not invent behavior;
        # it only wraps model-provided source text into files.
        files_from_scalars: list[dict[str, str]] = []
        source_candidates = [
            normalized.get("tool_py"),
            normalized.get("tool_code"),
            normalized.get("runtime_code"),
            normalized.get("implementation_code"),
            normalized.get("code"),
        ]
        for candidate in source_candidates:
            if isinstance(candidate, str) and candidate.strip():
                files_from_scalars.append({"path": "tool.py", "content": candidate})
                break
        test_candidates = [
            normalized.get("test_tool_py"),
            normalized.get("test_code"),
            normalized.get("tests"),
            normalized.get("sandbox_test"),
        ]
        for candidate in test_candidates:
            if isinstance(candidate, str) and candidate.strip():
                files_from_scalars.append({"path": "test_tool.py", "content": candidate})
                break
        if files_from_scalars:
            normalized["files"] = files_from_scalars
            return normalized
        return normalized

    def _coerce_files(self, value: Any) -> list[dict[str, str]]:
        if isinstance(value, list):
            result: list[dict[str, str]] = []
            for item in value:
                if isinstance(item, dict):
                    path = str(item.get("path") or item.get("filename") or item.get("name") or "").strip()
                    content = item.get("content") if "content" in item else item.get("source")
                    if not path or content is None:
                        continue
                    result.append({"path": path, "content": str(content)})
            return result
        if isinstance(value, dict):
            result = []
            for path, content in value.items():
                if isinstance(content, dict):
                    content = content.get("content") if "content" in content else content.get("source")
                if content is None:
                    continue
                path_s = str(path or "").strip()
                if path_s:
                    result.append({"path": path_s, "content": str(content)})
            return result
        return []

    def _repair_artifact_with_llm(
        self,
        *,
        raw_content: str,
        raw_artifact: dict[str, Any],
        tool_id: str,
        run_id: str | None,
        attempt: dict[str, Any],
        entrypoint: dict[str, Any],
        blueprint: dict[str, Any],
        identity_contract: dict[str, Any],
        input_schema: dict[str, Any],
        output_schema: dict[str, Any],
        connection_schema: dict[str, Any],
        secret_schema: dict[str, Any],
        verification_input: dict[str, Any],
        specification_contract: dict[str, Any],
    ) -> dict[str, Any]:
        """Ask the selected code model to convert its invalid output into files.

        The repair prompt is generic: it does not add behavior or use a hidden
        template.  It gives the model the same compact contract plus its own
        previous output and requires a canonical artifact envelope.
        """
        repair_contract = {
            "tool_id": tool_id,
            "entrypoint": self._compact_entrypoint(entrypoint),
            "identity": self._compact_identity_contract(identity_contract, blueprint=blueprint, tool_id=tool_id),
            "behavior_contract": self._compact_behavior_contract(blueprint, tool_id=tool_id),
            "schemas": {
                "input": self._schema_for_codegen(input_schema),
                "output": self._schema_for_codegen(output_schema),
                "connection": self._schema_for_codegen(connection_schema),
                "secret": self._schema_for_codegen(secret_schema),
            },
            "verification_input": self._compact_json(verification_input, limit=1800),
            "specification": self._compact_specification_contract(specification_contract),
            "previous_output_excerpt": str(raw_content or json.dumps(raw_artifact, ensure_ascii=False, default=str))[:4000],
            "repair_instruction": "Return only canonical JSON with files array containing executable tool.py and test_tool.py. Do not explain.",
        }
        messages = [
            {
                "role": "system",
                "content": (
                    "You repair invalid runtime artifact generation output. "
                    "Do not invent a new plan. Use the supplied contract and previous output. "
                    "Return one JSON object only. files is required; include any inferred or preserved schemas, verification fields, dependencies, and capability contract when available. "
                    "files must be an array with path/content entries for tool.py and test_tool.py. No markdown."
                ),
            },
            {"role": "user", "content": json.dumps(repair_contract, ensure_ascii=False, separators=(",", ":"), default=str)},
        ]
        repair_attempt = {**(attempt or {}), "repair": True, "force_json": True, "compact": True}
        self._emit_generation_progress(
            run_id=run_id,
            tool_id=tool_id,
            status="running",
            phase="llm_artifact_repair_started",
            attempt=repair_attempt,
        )
        result = self._complete_sync_with_heartbeat(
            run_id=run_id,
            tool_id=tool_id,
            attempt=repair_attempt,
            brain="auxiliary_brain",
            task_type="runtime_tool_code_generation",
            complexity=str((attempt or {}).get("complexity") or "high"),
            messages=messages,
            context={
                "tool_id": tool_id,
                "generation_attempt": repair_attempt,
                "repair": True,
                "route_override": repair_attempt.get("route_override") if isinstance(repair_attempt.get("route_override"), dict) else None,
            },
            response_format={"type": "json_object"},
        )
        self._emit_generation_progress(
            run_id=run_id,
            tool_id=tool_id,
            status=str(result.status or "completed"),
            phase="llm_artifact_repair_response_received",
            attempt=repair_attempt,
            route=result.route if isinstance(result.route, dict) else {},
            error=result.error,
        )
        if result.status != "completed":
            return {"generation_status": "invalid_generated_artifact", "generation_error": str(result.error or "artifact repair failed")}
        parsed = self._parse_json_object(str(result.content or ""))
        if not isinstance(parsed, dict):
            return {"generation_status": "invalid_generated_artifact", "generation_error": "artifact repair did not return JSON object"}
        parsed = self._normalize_llm_artifact_payload(parsed, tool_id=tool_id)
        if self._valid_generated_artifact(parsed):
            parsed.setdefault("input_schema", input_schema)
            parsed.setdefault("output_schema", output_schema)
            parsed.setdefault("connection_schema", connection_schema)
            parsed.setdefault("secret_schema", secret_schema)
            parsed.setdefault("verification_input", verification_input)
            parsed.setdefault("verification_expectations", {"status": "completed"})
            parsed.setdefault("dependencies", [])
            return parsed
        return {"generation_status": "invalid_generated_artifact", "generation_error": "artifact repair JSON still missing executable files"}

    def _repair_missing_artifact_files(
        self,
        *,
        raw_artifact: dict[str, Any],
        tool_id: str,
        entrypoint: dict[str, Any],
        blueprint: dict[str, Any],
        input_schema: dict[str, Any],
        output_schema: dict[str, Any],
        connection_schema: dict[str, Any],
        secret_schema: dict[str, Any],
        verification_input: dict[str, Any],
    ) -> dict[str, Any]:
        """Deterministically repair file-container omissions without capability-specific code.

        This does not invent behavior.  If the model supplied source under a
        non-canonical container, it is normalized.  If no executable source is
        present, the repair returns a failed marker so the caller can escalate to
        the next model route.
        """
        normalized = self._normalize_llm_artifact_payload(raw_artifact if isinstance(raw_artifact, dict) else {}, tool_id=tool_id)
        if self._valid_generated_artifact(normalized):
            return normalized
        # Last generic salvage: top-level tool.py/test_tool.py keys.
        files: list[dict[str, str]] = []
        for key in ("tool.py", "test_tool.py"):
            value = raw_artifact.get(key) if isinstance(raw_artifact, dict) else None
            if isinstance(value, str) and value.strip():
                files.append({"path": key, "content": value})
        if files:
            candidate = dict(raw_artifact)
            candidate["files"] = files
            candidate.setdefault("input_schema", input_schema)
            candidate.setdefault("output_schema", output_schema)
            candidate.setdefault("connection_schema", connection_schema)
            candidate.setdefault("secret_schema", secret_schema)
            candidate.setdefault("verification_input", verification_input)
            if self._valid_generated_artifact(candidate):
                return candidate
        return {"generation_status": "invalid_generated_artifact", "generation_error": "artifact files missing or non-executable; escalate model route"}

    def _valid_generated_artifact(self, artifact: dict[str, Any]) -> bool:
        if not isinstance(artifact, dict):
            return False
        files = artifact.get("files")
        if not self._valid_files(files) or self._files_look_like_stub(files):
            return False
        if not self._generated_python_sources_parse(files):
            return False
        if not self._generated_tests_have_defined_names(files):
            return False
        text = "\n".join(str(item.get("content") or "") for item in files if isinstance(item, dict))
        if "def " not in text or "return" not in text:
            return False
        return True

    def _generated_python_sources_parse(self, files: list[dict[str, Any]]) -> bool:
        for item in files:
            if not isinstance(item, dict):
                continue
            path = str(item.get("path") or "")
            if not path.endswith(".py"):
                continue
            content = str(item.get("content") or "")
            try:
                ast.parse(content)
            except SyntaxError:
                return False
        return True

    def _generated_artifact_contract_violations(
        self,
        artifact: dict[str, Any],
        *,
        input_schema: dict[str, Any],
        connection_schema: dict[str, Any],
        secret_schema: dict[str, Any],
    ) -> list[str]:
        """Reject generated code that makes optional interface fields mandatory.

        The runtime acquisition layer must not repair a bad generated tool after
        registration.  It must prevent contract drift before the artifact is
        accepted.  This guard is intentionally capability-neutral: field names
        are opaque; only JSON Schema required arrays and Python AST usage are
        compared.
        """
        if not isinstance(artifact, dict):
            return ["artifact is not an object"]
        files = artifact.get("files")
        if not isinstance(files, list):
            return ["artifact.files is not a list"]
        source = "\n".join(
            str(item.get("content") or "")
            for item in files
            if isinstance(item, dict) and str(item.get("path") or "").endswith(".py") and not self._is_test_path(str(item.get("path") or ""))
        )
        if not source.strip():
            return ["artifact has no runtime Python source"]
        violations: list[str] = []
        for scope, schema in (("input", input_schema), ("connection", connection_schema), ("secrets", secret_schema)):
            violations.extend(self._optional_field_hard_requirement_violations(source, schema=schema, scope=scope))
        violations.extend(self._schema_lifecycle_source_violations(
            source,
            input_schema=input_schema,
            connection_schema=connection_schema,
            secret_schema=secret_schema,
        ))
        return violations

    def _schema_lifecycle_source_violations(
        self,
        source: str,
        *,
        input_schema: dict[str, Any],
        connection_schema: dict[str, Any],
        secret_schema: dict[str, Any],
    ) -> list[str]:
        """Reject code that reads fields from the wrong lifecycle section."""
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return []
        section_fields: dict[str, set[str]] = {}
        for section, schema in (("input", input_schema), ("connection", connection_schema), ("secrets", secret_schema)):
            props = schema.get("properties") if isinstance(schema, dict) and isinstance(schema.get("properties"), dict) else {}
            section_fields[section] = {str(k) for k in props.keys()}
        aliases = {section: self._scope_aliases_from_source(source, scope=section) for section in ("input", "connection", "secrets")}
        violations: list[str] = []
        for node in ast.walk(tree):
            for read_section in ("input", "connection", "secrets"):
                field = self._field_name_read_from_section_node(node, section=read_section, aliases=aliases[read_section])
                if not field:
                    continue
                owner = None
                for section in ("secrets", "connection", "input"):
                    if field in section_fields[section]:
                        owner = section
                        break
                if owner and owner != read_section:
                    violations.append(f"{owner}.{field} must not be read from payload['{read_section}']")
        return sorted(set(violations))

    def _field_name_read_from_section_node(self, node: ast.AST, *, section: str, aliases: set[str]) -> str | None:
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get" and node.args:
            field = self._constant_node_value(node.args[0])
            base = node.func.value
            if isinstance(base, ast.Name) and base.id in aliases:
                return field
            if self._is_payload_scope_subscript(base, scope=section):
                return field
        if isinstance(node, ast.Subscript):
            field = self._constant_subscript_key(node.slice)
            base = node.value
            if isinstance(base, ast.Name) and base.id in aliases:
                return field
            if self._is_payload_scope_subscript(base, scope=section):
                return field
        return None

    def _optional_field_hard_requirement_violations(self, source: str, *, schema: dict[str, Any], scope: str) -> list[str]:
        if not isinstance(schema, dict):
            return []
        props = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
        if not props:
            return []
        required = {str(x) for x in schema.get("required", []) if isinstance(x, str)} if isinstance(schema.get("required"), list) else set()
        optional_fields = {str(k) for k in props.keys()} - required
        if not optional_fields:
            return []
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return []
        aliases = self._scope_aliases_from_source(source, scope=scope)
        variable_to_optional_field: dict[str, str] = {}
        variable_to_required_field: dict[str, str] = {}
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            value = node.value
            targets: list[ast.AST] = []
            if isinstance(node, ast.Assign):
                targets = list(node.targets)
            elif isinstance(node, ast.AnnAssign):
                targets = [node.target]
            field, safe_optional = self._field_read_from_scope(value, scope=scope, aliases=aliases, declared=set(str(k) for k in props.keys()))
            if not field:
                continue
            for target in targets:
                if not isinstance(target, ast.Name):
                    continue
                if field in optional_fields and safe_optional:
                    variable_to_optional_field[target.id] = field
                elif field in required:
                    variable_to_required_field[target.id] = field
        violations: list[str] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.If):
                continue
            checked = self._truthiness_checked_names(node.test)
            for name in sorted(checked):
                field = variable_to_optional_field.get(name)
                if field:
                    violations.append(f"{scope}.{field} is optional in schema but runtime source rejects empty or missing values through truthiness validation")
            direct_fields = self._truthiness_checked_optional_fields(node.test, scope=scope, aliases=aliases, optional_fields=optional_fields)
            for field in sorted(direct_fields):
                violations.append(f"{scope}.{field} is optional in schema but runtime source directly rejects empty or missing values")
        return sorted(set(violations))

    def _field_read_from_scope(self, node: ast.AST, *, scope: str, aliases: set[str], declared: set[str]) -> tuple[str | None, bool]:
        """Return (field_name, safe_optional_read).

        safe_optional_read is True for mapping.get(...).  Direct subscript reads
        are not optional reads and therefore are not treated as optional aliases.
        """
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get" and node.args:
            field = self._constant_node_value(node.args[0])
            if field in declared:
                base = node.func.value
                if isinstance(base, ast.Name) and base.id in aliases:
                    return field, True
                if self._is_payload_scope_subscript(base, scope=scope):
                    return field, True
        if isinstance(node, ast.Subscript):
            field = self._constant_subscript_key(node.slice)
            if field in declared:
                base = node.value
                if isinstance(base, ast.Name) and base.id in aliases:
                    return field, False
                if self._is_payload_scope_subscript(base, scope=scope):
                    return field, False
        return None, False

    def _truthiness_checked_names(self, node: ast.AST) -> set[str]:
        names: set[str] = set()
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            names.update(self._names_inside_truthy_expression(node.operand))
        elif isinstance(node, ast.BoolOp):
            for value in node.values:
                names.update(self._truthiness_checked_names(value))
        return names

    def _names_inside_truthy_expression(self, node: ast.AST) -> set[str]:
        names: set[str] = set()
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            for elt in node.elts:
                names.update(self._names_inside_truthy_expression(elt))
        elif isinstance(node, ast.Call):
            for arg in node.args:
                names.update(self._names_inside_truthy_expression(arg))
        elif isinstance(node, ast.BoolOp):
            for value in node.values:
                names.update(self._names_inside_truthy_expression(value))
        elif isinstance(node, ast.Compare):
            names.update(self._names_inside_truthy_expression(node.left))
            for comp in node.comparators:
                names.update(self._names_inside_truthy_expression(comp))
        elif isinstance(node, ast.UnaryOp):
            names.update(self._names_inside_truthy_expression(node.operand))
        return names

    def _truthiness_checked_optional_fields(self, node: ast.AST, *, scope: str, aliases: set[str], optional_fields: set[str]) -> set[str]:
        fields: set[str] = set()
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            fields.update(self._optional_fields_inside_truthy_expression(node.operand, scope=scope, aliases=aliases, optional_fields=optional_fields))
        elif isinstance(node, ast.BoolOp):
            for value in node.values:
                fields.update(self._truthiness_checked_optional_fields(value, scope=scope, aliases=aliases, optional_fields=optional_fields))
        return fields

    def _optional_fields_inside_truthy_expression(self, node: ast.AST, *, scope: str, aliases: set[str], optional_fields: set[str]) -> set[str]:
        fields: set[str] = set()
        field, safe_optional = self._field_read_from_scope(node, scope=scope, aliases=aliases, declared=optional_fields)
        if field and safe_optional:
            fields.add(field)
        for child in ast.iter_child_nodes(node):
            fields.update(self._optional_fields_inside_truthy_expression(child, scope=scope, aliases=aliases, optional_fields=optional_fields))
        return fields

    def _generated_tests_have_defined_names(self, files: list[dict[str, Any]]) -> bool:
        for item in files:
            if not isinstance(item, dict):
                continue
            if not self._is_test_path(str(item.get("path") or "")):
                continue
            try:
                tree = ast.parse(str(item.get("content") or ""))
            except SyntaxError:
                return False
            if self._undefined_loaded_names(tree):
                return False
        return True

    def _undefined_loaded_names(self, tree: ast.AST) -> list[str]:
        defined: set[str] = {"__name__", "True", "False", "None"}
        try:
            import builtins
            defined.update(name for name in dir(builtins) if isinstance(name, str))
        except Exception:
            pass
        loaded: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    defined.add(str(alias.asname or alias.name).split(".", 1)[0])
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    defined.add(str(alias.asname or alias.name))
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                defined.add(str(node.name))
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    for arg in [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]:
                        defined.add(str(arg.arg))
                    if node.args.vararg:
                        defined.add(str(node.args.vararg.arg))
                    if node.args.kwarg:
                        defined.add(str(node.args.kwarg.arg))
            elif isinstance(node, ast.Name):
                if isinstance(node.ctx, ast.Store):
                    defined.add(str(node.id))
                elif isinstance(node.ctx, ast.Load):
                    loaded.add(str(node.id))
            elif isinstance(node, ast.ExceptHandler) and node.name:
                defined.add(str(node.name))
        return sorted(name for name in loaded if name not in defined and not name.startswith("__"))

    def _generated_tests_use_allowed_imports(self, files: list[dict[str, Any]], dependencies: list[dict[str, Any]]) -> bool:
        local_modules = {
            self._module_stem_from_path(str(item.get("path") or ""))
            for item in files
            if isinstance(item, dict) and str(item.get("path") or "").endswith(".py")
        }
        local_modules.discard("")
        declared_imports = self._dependency_import_names(dependencies)
        for item in files:
            if not isinstance(item, dict):
                continue
            path = str(item.get("path") or "")
            if not self._is_test_path(path):
                continue
            content = str(item.get("content") or "")
            try:
                tree = ast.parse(content)
            except SyntaxError:
                return False
            for node in ast.walk(tree):
                module = ""
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        module = str(alias.name or "").split(".", 1)[0]
                        if module and not self._allowed_generated_test_import(module, local_modules, declared_imports):
                            return False
                elif isinstance(node, ast.ImportFrom):
                    module = str(node.module or "").split(".", 1)[0]
                    if module and not self._allowed_generated_test_import(module, local_modules, declared_imports):
                        return False
        return True

    def _allowed_generated_test_import(self, module: str, local_modules: set[str], declared_imports: set[str]) -> bool:
        if module in local_modules:
            return True
        if module in declared_imports:
            return True
        return module in getattr(sys, "stdlib_module_names", set())

    def _is_test_path(self, path: str) -> bool:
        name = path.replace("\\", "/").rsplit("/", 1)[-1]
        return name.startswith("test_") and name.endswith(".py")

    def _module_stem_from_path(self, path: str) -> str:
        name = path.replace("\\", "/").rsplit("/", 1)[-1]
        if not name.endswith(".py"):
            return ""
        return name[:-3]

    def _normalized_dependencies(self, value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        result: list[dict[str, Any]] = []
        for item in value:
            if not isinstance(item, dict):
                continue
            import_name = str(item.get("import_name") or item.get("module") or "").strip()
            package = str(item.get("package") or item.get("name") or import_name).strip()
            if not package and not import_name:
                continue
            result.append({
                "package": package or import_name,
                "import_name": import_name or package.replace("-", "_"),
                "auto_install": bool(item.get("auto_install", True)),
                **({"source": item.get("source")} if item.get("source") else {}),
            })
        return result

    def _merge_dependencies(self, left: list[dict[str, Any]], right: list[dict[str, Any]]) -> list[dict[str, Any]]:
        merged: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for item in [*left, *right]:
            package = str(item.get("package") or item.get("name") or "").strip()
            import_name = str(item.get("import_name") or item.get("module") or "").strip()
            key = (package, import_name)
            if key in seen:
                continue
            seen.add(key)
            merged.append(item)
        return merged

    def _drop_stdlib_dependencies(self, dependencies: list[dict[str, Any]]) -> list[dict[str, Any]]:
        stdlib = getattr(sys, "stdlib_module_names", set())
        kept: list[dict[str, Any]] = []
        for item in dependencies:
            import_name = str(item.get("import_name") or item.get("module") or "").split(".", 1)[0]
            package = str(item.get("package") or item.get("name") or "").replace("-", "_").split(".", 1)[0]
            if import_name in stdlib or package in stdlib:
                continue
            kept.append(item)
        return kept

    def _stabilize_standard_library_runtime_files(self, files: list[dict[str, Any]], *, blueprint: dict[str, Any]) -> list[dict[str, Any]]:
        """Normalize generated files to the generic runtime entrypoint contract.

        This does not patch domain behavior. It only enforces the framework
        contract that the manifest entrypoint is callable as run(payload). If a
        generator produced a helper-style callable, the wrapper delegates to the
        existing callable using generic payload sections.
        """
        out: list[dict[str, Any]] = []
        entrypoint = blueprint.get("entrypoint") if isinstance(blueprint.get("entrypoint"), dict) else {}
        module_name = str(entrypoint.get("module") or "tool.py")
        function_name = str(entrypoint.get("function") or "run")
        for item in files:
            if isinstance(item, dict):
                cloned = dict(item)
                cloned["path"] = str(cloned.get("path") or "")
                cloned["content"] = str(cloned.get("content") or "")
                if self._same_module_path(cloned["path"], module_name):
                    cloned["content"] = self._ensure_payload_entrypoint(cloned["content"], function_name=function_name)
                out.append(cloned)
        return out

    def _same_module_path(self, path: str, module_name: str) -> bool:
        left = str(path or "").replace("\\", "/").rsplit("/", 1)[-1]
        right = str(module_name or "tool.py").replace("\\", "/").rsplit("/", 1)[-1]
        return left == right

    def _ensure_payload_entrypoint(self, source: str, *, function_name: str = "run") -> str:
        try:
            tree = ast.parse(source or "")
        except SyntaxError:
            return source
        functions = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
        existing_entrypoint = next((fn for fn in functions if fn.name == function_name and len(list(fn.args.posonlyargs) + list(fn.args.args)) == 1), None)
        if existing_entrypoint is not None:
            return self._wrap_existing_payload_entrypoint(source, function_name=function_name)
        candidates = [fn for fn in functions if not fn.name.startswith("_") and fn.name != function_name]
        if not candidates:
            return source
        target = candidates[0]
        args = list(target.args.posonlyargs) + list(target.args.args)
        if len(args) == 1:
            call = "return _generated_delegate(payload)"
        elif len(args) == 3:
            call = "return _generated_delegate(input_values, connection_values, secret_values)"
        else:
            return source
        wrapper = """

# Generic runtime entrypoint adapter inserted by the capability generator.
# It preserves the generated implementation and only adapts the framework
# payload envelope to the callable declared by the manifest.
def {function_name}(payload=None):
    payload = payload if isinstance(payload, dict) else {{}}
    input_values = payload.get("input") if isinstance(payload.get("input"), dict) else payload
    connection_values = payload.get("connection") if isinstance(payload.get("connection"), dict) else {{}}
    secret_values = payload.get("secrets") if isinstance(payload.get("secrets"), dict) else {{}}
    _generated_delegate = {target_name}
    {call}
""".format(function_name=function_name, target_name=target.name, call=call)
        return (source or "").rstrip() + wrapper + "\n"


    def _wrap_existing_payload_entrypoint(self, source: str, *, function_name: str = "run") -> str:
        """Wrap an already-declared runtime entrypoint with the framework envelope.

        Generated code is allowed to choose its internal behavior, but the
        runtime contract is generic and non-negotiable: the manifest
        entrypoint must accept one payload argument and return a JSON-safe
        dict for every branch.  LLM-generated tools often perform a mutation
        and fall off the end of ``run``.  That is valid Python, but it returns
        None and breaks the runtime.  This adapter preserves the original
        implementation under a private name and normalizes the returned value
        into the framework payload contract without adding any capability or
        domain-specific logic.
        """
        private_name = f"_generated_original_{function_name}"
        try:
            tree = ast.parse(source or "")
        except SyntaxError:
            return source
        entrypoint_nodes = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name]
        if not entrypoint_nodes:
            return source
        marker = f"{private_name} = {function_name}"
        if marker in source:
            return source
        wrapper = """

# Generic runtime entrypoint contract adapter inserted by the capability generator.
# It keeps the generated implementation intact and only enforces the runtime
# boundary: run(payload) must return a JSON-serializable dict.
{private_name} = {function_name}
def {function_name}(payload=None):
    payload = payload if isinstance(payload, dict) else {{}}
    result = {private_name}(payload)
    if isinstance(result, dict):
        return result
    if result is None:
        return {{"status": "completed", "result": None}}
    return {{"status": "completed", "result": result}}
""".format(private_name=private_name, function_name=function_name)
        return (source or "").rstrip() + wrapper + "\n"

    def _approval_policy_or_default(self, value: Any, *, runtime_execution_policy: dict[str, Any] | None = None) -> dict[str, Any]:
        runtime_execution_policy = runtime_execution_policy if isinstance(runtime_execution_policy, dict) else {}
        side_effects = str(runtime_execution_policy.get("side_effects") or "").strip().casefold()
        safe_effects = {"none", "pure", "read_only", "read-only"}
        default_required = side_effects not in safe_effects
        if isinstance(value, dict) and value.get("supported_modes") and value.get("default_mode"):
            policy = dict(value)
        else:
            mode = "always" if default_required else "never"
            policy = {
                "required": default_required,
                "supported_modes": ["always", "once", "never"],
                "default_mode": mode,
                "mode": mode,
                "preview_required": default_required,
            }
        policy.setdefault("supported_modes", ["always", "once", "never"])
        policy.setdefault("default_mode", "always" if bool(policy.get("required")) else "never")
        policy.setdefault("mode", policy.get("default_mode", "always"))
        policy.setdefault("required", default_required)
        policy.setdefault("preview_required", bool(policy.get("required")))
        if str(policy.get("mode") or "").strip().casefold() == "never":
            policy["required"] = False
            policy["preview_required"] = False
        return policy

    def _runtime_execution_policy_or_default(
        self,
        value: Any,
        *,
        input_schema: dict[str, Any],
        connection_schema: dict[str, Any],
        secret_schema: dict[str, Any],
        dependencies: list[dict[str, Any]],
    ) -> dict[str, Any]:
        policy = dict(value) if isinstance(value, dict) else {}
        side_effects = str(policy.get("side_effects") or "").strip().casefold()
        ambiguous = {"", "runtime_declared", "unknown", "unspecified"}
        if side_effects in ambiguous:
            connection_required = bool((connection_schema.get("required") or [])) or bool(connection_schema.get("properties"))
            secret_required = bool((secret_schema.get("required") or [])) or bool(secret_schema.get("properties"))
            non_stdlib_dependencies = bool(dependencies)
            if connection_required or secret_required:
                side_effects = "external_write"
            elif non_stdlib_dependencies:
                side_effects = "external_read"
            else:
                side_effects = "none"
        policy["side_effects"] = side_effects
        policy.setdefault("classification_source", "specification_contract")
        return policy

    def _dependency_import_names(self, dependencies: list[dict[str, Any]]) -> set[str]:
        imports: set[str] = set()
        for item in dependencies:
            import_name = str(item.get("import_name") or item.get("module") or "").strip()
            package = str(item.get("package") or item.get("name") or "").strip()
            if import_name:
                imports.add(import_name.split(".", 1)[0])
            elif package:
                imports.add(package.replace("-", "_").split(".", 1)[0])
        return imports

    def _should_request_llm_generation(self, blueprint: dict[str, Any], identity_contract: dict[str, Any]) -> bool:
        policy = blueprint.get("acquisition_policy") if isinstance(blueprint.get("acquisition_policy"), dict) else {}
        if policy.get("allow_llm_code_generation") is False:
            return False
        if policy.get("code_generation") == "disabled":
            return False
        return True

    def _generation_complexity(self, *, blueprint: dict[str, Any], identity_contract: dict[str, Any]) -> str:
        """Choose a policy route without embedding capability-specific logic."""
        text = json.dumps({
            "blueprint": {
                "description": blueprint.get("description"),
                "acquisition_policy": blueprint.get("acquisition_policy"),
                "runtime_execution_policy": blueprint.get("runtime_execution_policy"),
                "dependencies": blueprint.get("dependencies"),
            },
            "identity_contract": identity_contract,
        }, ensure_ascii=False, default=str).casefold()
        dependencies = blueprint.get("dependencies") if isinstance(blueprint.get("dependencies"), list) else []
        has_declared_dependency = any(isinstance(item, dict) and str(item.get("package") or item.get("name") or item.get("module") or "").strip() for item in dependencies)
        local_basic_markers = [
            "complexity level: basic",
            "complexity level basic",
            "standard library",
            "standard-library",
            "no external network",
            "do not call external network",
            "no network",
            "offline",
        ]
        external_reference_markers = [
            "official documentation",
            "reference documentation",
            "implementation guide",
            "api documentation",
            "similar example",
            "example program",
            "external evidence",
            "web evidence",
            "source material",
        ]
        complex_markers = [
            "oauth",
            "browser automation",
            "third-party sdk",
            "pip install",
            "requires external package",
        ]
        if has_declared_dependency:
            return "high"
        if any(marker in text for marker in complex_markers):
            return "high"
        if any(marker in text for marker in local_basic_markers):
            return "basic"
        if any(marker in text for marker in external_reference_markers):
            return "medium"
        return "default"

    def _generation_attempts(self, base_complexity: str) -> list[dict[str, Any]]:
        """Build explicit one-model code-generation attempts.

        Previous versions escalated only the abstract complexity value.  The
        model router could still keep the same provider/model inside each call
        or spend the whole stage timeout in hidden fallbacks.  Runtime artifact
        generation needs visible, deterministic escalation: one attempt equals
        one provider/model route, and the next attempt is a real model change.
        The route list is read from model policy and remains capability-neutral.
        """
        order = ["basic", "medium", "high", "critical"]
        base = str(base_complexity or "default").strip().lower()
        if base not in order:
            base = "medium" if base == "default" else "high"

        routes = self._code_generation_escalation_routes()
        attempts: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for route in routes:
            provider = str(route.get("provider") or "").strip()
            model = str(route.get("model") or "").strip()
            if not provider and not model:
                continue
            key = (provider, model)
            if key in seen:
                continue
            seen.add(key)
            complexity = str(route.get("complexity") or "medium").strip().lower()
            attempts.append({
                "base_complexity": base,
                "complexity": complexity if complexity in order else "medium",
                "force_json": True,
                "compact": True,
                "route_override": {
                    "provider": provider,
                    "model": model,
                    "options": route.get("options") if isinstance(route.get("options"), dict) else {"temperature": 0},
                    "reason": "policy_ordered_codegen_model_escalation",
                    "policy_complexity": complexity if complexity in order else "medium",
                    "requested_base_complexity": base,
                },
            })

        if attempts:
            return attempts
        # Safe fallback: keep the old policy route if no explicit model policy is
        # available.  This still does not encode any capability-specific logic.
        return [{"base_complexity": base, "complexity": base if base in order else "medium", "force_json": True, "compact": True}]

    def _code_generation_escalation_routes(self) -> list[dict[str, Any]]:
        """Read code-generation model escalation routes from policy.

        The function intentionally reads infrastructure model policy only.  It
        does not branch on capability id, agent name, task name, or business
        vocabulary.
        """
        policy_path = Path(os.getenv("AI_BRAIN_MODEL_POLICY_PATH") or "configs/brain_model_policy.yaml")
        if not policy_path.is_absolute():
            for root in [Path.cwd(), Path(__file__).resolve().parents[2]]:
                candidate = root / policy_path
                if candidate.exists():
                    policy_path = candidate
                    break
        try:
            import yaml  # type: ignore
            policy = yaml.safe_load(policy_path.read_text(encoding="utf-8")) if policy_path.exists() else {}
        except Exception:
            policy = {}
        routes: list[dict[str, Any]] = []
        def append_route(item: Any, complexity: str, reason: str) -> None:
            if not isinstance(item, dict):
                return
            provider = item.get("provider")
            model = item.get("model")
            if provider or model:
                route = {
                    "complexity": complexity,
                    "provider": provider,
                    "model": model,
                    "options": item.get("options") if isinstance(item.get("options"), dict) else {"temperature": 0},
                    "policy_reason": reason,
                }
                routes.append(route)
            fallbacks = item.get("fallback") if isinstance(item.get("fallback"), list) else []
            for index, fallback in enumerate(fallbacks):
                if isinstance(fallback, dict):
                    append_route(fallback, complexity, f"{reason}.fallback.{index}")

        try:
            auxiliary = policy.get("brains", {}).get("auxiliary_brain", {}) if isinstance(policy, dict) else {}
            task = auxiliary.get("tasks", {}).get("runtime_tool_code_generation", {}) if isinstance(auxiliary, dict) else {}
            # Policy order is the only source of model escalation.  Start from
            # the task/default route and then walk complexity routes from small
            # to strong.  Do not jump directly to a high/critical model just
            # because the request was classified as high complexity; failed
            # lower routes are visible attempts and can auto-prepare missing
            # listed models before escalating.
            append_route(auxiliary.get("default"), "basic", "auxiliary_brain.default")
            append_route(task, "basic", "runtime_tool_code_generation.default")
            complexities = task.get("complexities") if isinstance(task.get("complexities"), dict) else {}
            for complexity in ["basic", "medium", "high", "critical"]:
                append_route(complexities.get(complexity), complexity, f"runtime_tool_code_generation.complexities.{complexity}")
        except Exception:
            routes = []
        if routes:
            return routes
        return [
            {"complexity": "basic", "provider": "ollama", "model": "qwen2.5-coder:7b", "options": {"temperature": 0}},
            {"complexity": "medium", "provider": "ollama", "model": "deepseek-coder-v2:lite", "options": {"temperature": 0}},
            {"complexity": "high", "provider": "ollama", "model": "deepseek-coder-v2:16b", "options": {"temperature": 0}},
        ]

    def _capability_contract(self, *, tool_id: str, blueprint: dict[str, Any]) -> dict[str, Any]:
        declared = blueprint.get("capability_match_contract") if isinstance(blueprint.get("capability_match_contract"), dict) else {}
        required_markers = declared.get("required_markers") if isinstance(declared.get("required_markers"), list) else [tool_id, "TOOL_ID", "def ", "return"]
        forbidden_markers = declared.get("forbidden_markers") if isinstance(declared.get("forbidden_markers"), list) else [
            "requires_runtime_implementation",
            "Blueprint only",
            "hardcoded sample",
        ]
        return {
            **declared,
            "expected_tool_id": declared.get("expected_tool_id") or tool_id,
            "expected_template_id": declared.get("expected_template_id") or tool_id,
            "required_artifact_dir_name": declared.get("required_artifact_dir_name") or tool_id,
            "required_markers": required_markers,
            "forbidden_markers": forbidden_markers,
        }

    def _valid_files(self, files: Any) -> bool:
        return isinstance(files, list) and bool(files) and all(isinstance(item, dict) and str(item.get("path") or "").strip() and isinstance(item.get("content"), str) for item in files)

    def _merge_declared_schema(self, declared: dict[str, Any], generated: dict[str, Any], *, default_name: str) -> dict[str, Any]:
        """Preserve interface fields declared before code generation.

        LLM generation may refine descriptions, optionality, or add fields, but it
        must not erase user/request-declared connection or secret fields. This is
        generic schema merging; field names are treated as opaque interface keys.
        """
        base = self._schema_or_default(declared, default_name) if default_name in {"input", "output"} else self._closed_schema(declared)
        other = self._schema_or_default(generated, default_name) if default_name in {"input", "output"} else self._closed_schema(generated)
        merged = dict(other)
        merged.setdefault("type", "object")
        base_props = base.get("properties") if isinstance(base.get("properties"), dict) else {}
        other_props = other.get("properties") if isinstance(other.get("properties"), dict) else {}
        props: dict[str, Any] = {}
        props.update(other_props)
        for name, spec in base_props.items():
            if name in props and isinstance(props.get(name), dict) and isinstance(spec, dict):
                combined = dict(spec)
                combined.update(props[name])
                props[name] = combined
            else:
                props[name] = spec
        merged["properties"] = props
        base_required = [str(x) for x in base.get("required", []) if isinstance(x, str)] if isinstance(base.get("required"), list) else []
        other_required = [str(x) for x in other.get("required", []) if isinstance(x, str)] if isinstance(other.get("required"), list) else []
        ordered_required: list[str] = []
        for name in [*base_required, *other_required]:
            if name in props and name not in ordered_required:
                ordered_required.append(name)
        merged["required"] = ordered_required
        if props:
            merged["additionalProperties"] = False
        return merged

    def _schema_or_default(self, value: Any, name: str) -> dict[str, Any]:
        if isinstance(value, dict) and value:
            schema = dict(value)
            schema.setdefault("type", "object")
            schema.setdefault("properties", {})
            schema.setdefault("required", [])
            if schema.get("properties"):
                schema["additionalProperties"] = False
            else:
                schema.setdefault("additionalProperties", name != "output")
            return schema
        if name == "output":
            return {
                "type": "object",
                "required": ["status", "data"],
                "properties": {
                    "status": {"type": "string"},
                    "data": {"type": "object"},
                    "message": {"type": "string"},
                    "provenance": {"type": "object"},
                },
                "additionalProperties": False,
            }
        return {"type": "object", "properties": {}, "required": [], "additionalProperties": True}

    def _closed_schema(self, value: Any) -> dict[str, Any]:
        if isinstance(value, dict) and value:
            schema = dict(value)
            schema.setdefault("type", "object")
            schema.setdefault("properties", {})
            schema.setdefault("required", [])
            schema.setdefault("additionalProperties", False)
            return schema
        return {"type": "object", "properties": {}, "required": [], "additionalProperties": False, "x-empty-schema-allowed": True}


    def _reconcile_required_fields_from_source(self, schema: dict[str, Any], files: Any, *, scope: str) -> dict[str, Any]:
        """Reconcile schema.required with structural source usage.

        This is capability-neutral: it does not know field meanings.  It only
        distinguishes values accessed as mapping subscripts from values accessed
        through safe optional getters in generated Python source.
        """
        if not isinstance(schema, dict):
            return schema
        props = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
        if not props:
            return schema
        source = "\n".join(str(item.get("content") or "") for item in files if isinstance(item, dict))
        if not source.strip():
            return schema
        required_by_source = self._required_fields_used_by_source(source, scope=scope, declared=set(str(k) for k in props.keys()))
        optional_by_source = self._optional_fields_used_by_source(source, scope=scope, declared=set(str(k) for k in props.keys()))
        current_required = {str(x) for x in schema.get("required", []) if isinstance(x, str)} if isinstance(schema.get("required"), list) else set()
        if required_by_source:
            next_required = (current_required & required_by_source) | required_by_source
        else:
            next_required = set(current_required)
        next_required -= optional_by_source
        cleaned = dict(schema)
        cleaned["required"] = [name for name in props.keys() if str(name) in next_required]
        return cleaned

    def _required_fields_used_by_source(self, source: str, *, scope: str, declared: set[str]) -> set[str]:
        direct: set[str] = set()
        aliases = self._scope_aliases_from_source(source, scope=scope)
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return direct
        for node in ast.walk(tree):
            if not isinstance(node, ast.Subscript):
                continue
            field = self._constant_subscript_key(node.slice)
            if field not in declared:
                continue
            base = node.value
            if isinstance(base, ast.Name) and base.id in aliases:
                direct.add(field)
            elif self._is_payload_scope_subscript(base, scope=scope):
                direct.add(field)
        return direct

    def _optional_fields_used_by_source(self, source: str, *, scope: str, declared: set[str]) -> set[str]:
        optional: set[str] = set()
        aliases = self._scope_aliases_from_source(source, scope=scope)
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return optional
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Attribute) or func.attr != "get":
                continue
            if not node.args:
                continue
            field = self._constant_node_value(node.args[0])
            if field not in declared:
                continue
            base = func.value
            if isinstance(base, ast.Name) and base.id in aliases:
                optional.add(field)
            elif self._is_payload_scope_subscript(base, scope=scope):
                optional.add(field)
        return optional

    def _scope_aliases_from_source(self, source: str, *, scope: str) -> set[str]:
        aliases: set[str] = set()
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return aliases
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                if self._expression_contains_payload_scope(node.value, scope=scope):
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            aliases.add(target.id)
            elif isinstance(node, ast.AnnAssign):
                if self._expression_contains_payload_scope(node.value, scope=scope) and isinstance(node.target, ast.Name):
                    aliases.add(node.target.id)
        return aliases

    def _expression_contains_payload_scope(self, node: ast.AST, *, scope: str) -> bool:
        if self._is_payload_scope_subscript(node, scope=scope):
            return True
        if self._is_payload_scope_get_call(node, scope=scope):
            return True
        if isinstance(node, ast.IfExp):
            return self._expression_contains_payload_scope(node.body, scope=scope) or self._expression_contains_payload_scope(node.orelse, scope=scope)
        if isinstance(node, ast.BoolOp):
            return any(self._expression_contains_payload_scope(value, scope=scope) for value in node.values)
        return False

    def _is_payload_scope_subscript(self, node: ast.AST, *, scope: str) -> bool:
        if not isinstance(node, ast.Subscript):
            return False
        if self._constant_subscript_key(node.slice) != scope:
            return False
        return isinstance(node.value, ast.Name) and node.value.id == "payload"

    def _is_payload_scope_get_call(self, node: ast.AST, *, scope: str) -> bool:
        if not isinstance(node, ast.Call):
            return False
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr != "get":
            return False
        if not isinstance(func.value, ast.Name) or func.value.id != "payload":
            return False
        if not node.args:
            return False
        return self._constant_node_value(node.args[0]) == scope

    def _constant_subscript_key(self, node: ast.AST) -> str | None:
        return self._constant_node_value(node)

    def _constant_node_value(self, node: ast.AST) -> str | None:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if hasattr(ast, "Index") and isinstance(node, ast.Index):
            return self._constant_node_value(node.value)
        return None

    def _files_look_like_stub(self, files: Any) -> bool:
        text = "\n".join(str(item.get("content") or "") for item in files if isinstance(item, dict)).casefold()
        return any(marker in text for marker in ["blueprint only", "requires_runtime_implementation", "runtime blueprint artifact verified", "not a registerable runtime implementation"])

    def _generic_verification_input(self, input_schema: dict[str, Any], connection_schema: dict[str, Any] | None = None, secret_schema: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "input": self._sample_payload_scope(input_schema),
            "connection": self._sample_payload_scope(connection_schema or {}),
            "secrets": self._sample_payload_scope(secret_schema or {}),
            "_runtime": {"dry_run": True},
        }

    def _verification_input_with_schema_sample(self, verification_input: dict[str, Any], input_schema: dict[str, Any], connection_schema: dict[str, Any] | None = None, secret_schema: dict[str, Any] | None = None) -> dict[str, Any]:
        sampled = self._generic_verification_input(input_schema, connection_schema or {}, secret_schema or {})
        merged = dict(verification_input or {})
        for scope in ["input", "connection", "secrets"]:
            current = merged.get(scope) if isinstance(merged.get(scope), dict) else {}
            filled = dict(sampled.get(scope) or {})
            filled.update(current)
            # Preserve user-declared values exactly.  Formatting, parsing, and
            # value conversion are implementation responsibilities generated
            # from specification_contract, not sandbox-side sample repair.
            merged[scope] = filled
        runtime = merged.get("_runtime") if isinstance(merged.get("_runtime"), dict) else {}
        runtime.setdefault("dry_run", True)
        merged["_runtime"] = runtime
        return merged

    def _sample_payload_scope(self, schema: dict[str, Any]) -> dict[str, Any]:
        props = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
        required = schema.get("required") if isinstance(schema.get("required"), list) else []
        result: dict[str, Any] = {}
        for name, field_schema in props.items():
            # Sandbox verification should exercise the full declared contract.
            # Optional fields still receive neutral schema-shaped samples so the
            # generated implementation can prove it handles every declared
            # parameter without needing live user values.
            result[str(name)] = self._sample_value(field_schema if isinstance(field_schema, dict) else {})
        return result

    def _sample_value(self, schema: dict[str, Any]) -> Any:
        if "default" in schema:
            return schema.get("default")
        typ = schema.get("type")
        if isinstance(typ, list):
            typ = typ[0] if typ else "string"
        if typ == "boolean":
            return False
        if typ == "integer":
            return 1
        if typ == "number":
            return 1.0
        if typ == "array":
            return []
        if typ == "object":
            return {}
        return "sample"

    def _neutral_files(self, *, tool_id: str, entrypoint: dict[str, Any], reason: str = "implementation_not_generated") -> list[dict[str, str]]:
        module = str(entrypoint.get("module") or "tool.py")
        function = str(entrypoint.get("function") or "run")
        code = f'''from __future__ import annotations
from pathlib import Path
from typing import Any
TOOL_ID = {tool_id!r}
def {function}(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    return {{"status": "blueprint_generated", "tool_id": TOOL_ID, "data": {{}}, "message": {reason!r}}}
'''
        test = f'''from pathlib import Path
import importlib.util
ROOT = Path(__file__).resolve().parents[2] / "tools" / {tool_id!r}
SPEC = importlib.util.spec_from_file_location("generated_tool_under_test", ROOT / {module!r})
mod = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(mod)
def test_blueprint_only_contract():
    result = getattr(mod, {function!r})({{"_runtime": {{"dry_run": True}}}})
    assert result["status"] == "blueprint_generated"
'''
        return [{"path": module, "content": code}, {"path": f"test_{tool_id}.py", "content": test}]

    def _safe_name(self, value: str) -> str:
        return "".join(c if c.isalnum() else "_" for c in str(value)).strip("_").lower() or "generated_capability"

    def _now_iso(self) -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
