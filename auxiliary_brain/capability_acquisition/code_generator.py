from __future__ import annotations

import ast
import json
import re
import sys
import time
import threading
from datetime import datetime, timezone
from typing import Any

try:
    from ai_core.runtime.state import runtime_state_manager
except Exception:  # pragma: no cover - optional runtime integration
    runtime_state_manager = None
try:
    from auxiliary_brain.runtime.observability.runtime_console import emit_console_event
except Exception:  # pragma: no cover - optional runtime integration
    emit_console_event = None

from ai_core.model_orchestration import LiteLLMBrainClient
from auxiliary_brain.capability_acquisition.specification_contract_compiler import CapabilitySpecificationContractCompiler
from auxiliary_brain.capability_acquisition.schema_boundary import CapabilitySchemaBoundary


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
                "mode": "llm_or_supplied_files_only",
                "status": generation_status,
                "route": generation_route,
                "error": generation_error,
            },
            "generated_at": self._now_iso(),
        }

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
        base_complexity = self._generation_complexity(blueprint=blueprint, identity_contract=identity_contract)
        attempts: list[dict[str, Any]] = []
        for attempt in self._generation_attempts(base_complexity):
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
                continue
            parsed = self._parse_json_object(result.content)
            if not isinstance(parsed, dict):
                record["status"] = "invalid_llm_json"
                record["error"] = "LLM did not return a JSON object."
                attempts.append(record)
                continue
            if not self._valid_generated_artifact(parsed):
                record["status"] = "invalid_generated_artifact"
                record["error"] = "LLM JSON did not contain executable artifact files."
                attempts.append(record)
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
                continue
            parsed["generation_status"] = "completed"
            parsed["generation_route"] = route
            parsed["generation_attempts"] = attempts + [record]
            return parsed
        last = attempts[-1] if attempts else {}
        return {
            "generation_status": str(last.get("status") or "llm_generation_failed"),
            "generation_route": last.get("route") if isinstance(last.get("route"), dict) else {},
            "generation_error": str(last.get("error") or "LLM did not produce a registerable runtime artifact."),
            "generation_attempts": attempts,
        }

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
        """Build a compact, contract-only code generation prompt.

        Code generation must not re-interpret the original user request.  The
        planner/specification stages have already made the authoritative
        decisions.  Keeping this prompt small reduces local-model latency and
        avoids repeated intent/planning work during capability acquisition.
        """
        required_return_shape = {
            "files": [
                {"path": "tool.py", "content": "Python source code"},
                {"path": "test_tool.py", "content": "plain Python test source code"},
            ],
            "input_schema": "JSON schema object",
            "output_schema": "JSON schema object",
            "connection_schema": "JSON schema object",
            "secret_schema": "JSON schema object",
            "dependencies": [
                {"package": "pip package name", "import_name": "python import name", "auto_install": True}
            ],
            "verification_input": "JSON object used by sandbox validation",
            "verification_expectations": "JSON object",
            "capability_match_contract": "JSON object",
        }
        # Only pass normalized execution contracts.  Description is truncated and
        # used as background text, not as a source for re-planning.
        contract = {
            "tool_id": tool_id,
            "entrypoint": entrypoint,
            "capability_summary": str(blueprint.get("description") or "")[:1200 if compact else 2000],
            "identity_contract": identity_contract,
            "input_schema": input_schema,
            "output_schema": output_schema,
            "connection_schema": connection_schema,
            "secret_schema": secret_schema,
            "verification_input": verification_input,
            "runtime_execution_policy": blueprint.get("runtime_execution_policy") if isinstance(blueprint.get("runtime_execution_policy"), dict) else {},
            "approval_policy": blueprint.get("approval_policy") if isinstance(blueprint.get("approval_policy"), dict) else {},
            "capability_match_contract": blueprint.get("capability_match_contract") if isinstance(blueprint.get("capability_match_contract"), dict) else {},
            "required_return_shape": required_return_shape,
        }
        if not compact:
            compact_spec = self._compact_specification_contract(specification_contract)
            if compact_spec:
                contract["specification_contract"] = compact_spec
        system = (
            "You are a runtime artifact generator. Use only the supplied artifact contract. "
            "Do not reinterpret the original user request. Do not perform intent recognition, planning, research, or explanation. "
            "Return only one JSON object matching required_return_shape. "
            "Generate real executable Python code for the entrypoint. The entrypoint accepts one optional dict payload and returns a JSON-serializable dict. "
            "Payload sections are strict: input fields from payload['input'], connection fields from payload['connection'], secret fields from payload['secrets'], runtime flags from payload['_runtime']. "
            "Do not duplicate connection or secret fields into input. Do not store secrets in code, manifests, tests, logs, or ordinary input fields. "
            "Prefer Python standard library. Declare dependencies only when required by the supplied contract. "
            "Sandbox tests must not perform external network calls or live side effects; use dry_run or mocks when side effects require external services. "
            "Do not hardcode dynamic output values except fake values used inside tests or dry-run mock branches. "
            "No markdown. No prose. JSON only."
        )
        user = json.dumps(contract, ensure_ascii=False, separators=(",", ":"), default=str)
        return [{"role": "system", "content": system}, {"role": "user", "content": user}]

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
        stop = threading.Event()
        started = time.time()

        def beat() -> None:
            while not stop.wait(15.0):
                self._emit_generation_progress(
                    run_id=run_id,
                    tool_id=tool_id,
                    status="running",
                    phase="llm_request_waiting",
                    attempt=attempt,
                    elapsed_seconds=round(time.time() - started, 1),
                )

        thread = threading.Thread(target=beat, name=f"capability-codegen-heartbeat-{tool_id}", daemon=True)
        thread.start()
        try:
            return self.llm_client.complete_sync(**kwargs)
        finally:
            stop.set()

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

    def _parse_json_object(self, content: str) -> dict[str, Any] | None:
        text = str(content or "").strip()
        if not text:
            return None
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
            text = re.sub(r"\s*```$", "", text)
        try:
            data = json.loads(text)
            return data if isinstance(data, dict) else None
        except Exception:
            pass
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                data = json.loads(text[start : end + 1])
                return data if isinstance(data, dict) else None
            except Exception:
                return None
        return None

    def _valid_generated_artifact(self, artifact: dict[str, Any]) -> bool:
        if not isinstance(artifact, dict):
            return False
        files = artifact.get("files")
        if not self._valid_files(files) or self._files_look_like_stub(files):
            return False
        if not self._generated_tests_have_defined_names(files):
            return False
        text = "\n".join(str(item.get("content") or "") for item in files if isinstance(item, dict))
        if "def " not in text or "return" not in text:
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
            return ["generated source is not parseable for lifecycle validation"]
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
            return [f"{scope}: generated source is not parseable for contract validation"]
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
        order = ["basic", "medium", "high", "critical"]
        base = str(base_complexity or "default").strip().lower()
        if base not in order:
            base = "medium" if base == "default" else "high"
        start = order.index(base)
        complexities = order[start:]
        attempts: list[dict[str, Any]] = []
        for complexity in complexities:
            attempts.append({"complexity": complexity, "force_json": True, "compact": True})
            attempts.append({"complexity": complexity, "force_json": False, "compact": True})
        return attempts

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
