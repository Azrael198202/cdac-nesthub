from __future__ import annotations

import ast
import json
import os
import re
import sys
import tempfile
import subprocess
import time
import threading
import queue
import importlib.util
from pathlib import Path
from typing import Any

from ai_core.model_orchestration import LiteLLMBrainClient


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

    def materialize(self, blueprint: dict[str, Any], *, identity_contract: dict[str, Any] | None = None) -> dict[str, Any]:
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
        verification_input = blueprint.get("verification_input") if isinstance(blueprint.get("verification_input"), dict) else self._generic_verification_input(input_schema, connection_schema, secret_schema)
        verification_input = self._verification_input_with_schema_sample(verification_input, input_schema, connection_schema, secret_schema)
        verification_expectations = blueprint.get("verification_expectations") if isinstance(blueprint.get("verification_expectations"), dict) else {"status": "completed"}
        capability_contract = self._capability_contract(tool_id=tool_id, blueprint=blueprint)
        files = blueprint.get("files") if isinstance(blueprint.get("files"), list) else []
        artifact_kind = "blueprint_only_not_registerable"
        generation_status = "not_attempted"
        generation_route: dict[str, Any] = {}
        generation_error = ""
        generation_interaction_request: dict[str, Any] = {}
        generation_attempts: list[dict[str, Any]] = []
        generation_preflight: dict[str, Any] = {}
        generation_failed_artifact: dict[str, Any] = {}
        dependencies = self._normalized_dependencies(blueprint.get("dependencies"))

        if self._valid_files(files) and not self._files_look_like_stub(files):
            files = self._stabilize_standard_library_runtime_files(files, blueprint=blueprint)
            artifact_kind = "real_runtime_implementation"
            generation_status = "provided_blueprint_files_used"
        elif self._should_request_llm_generation(blueprint, identity_contract):
            llm_artifact = self._generate_with_llm(
                tool_id=tool_id,
                entrypoint=entrypoint,
                blueprint=blueprint,
                identity_contract=identity_contract,
                input_schema=input_schema,
                output_schema=output_schema,
                connection_schema=connection_schema,
                secret_schema=secret_schema,
                verification_input=verification_input,
            )
            generation_status = str(llm_artifact.get("generation_status") or "failed")
            generation_route = llm_artifact.get("generation_route") if isinstance(llm_artifact.get("generation_route"), dict) else {}
            generation_error = str(llm_artifact.get("generation_error") or "")
            generation_interaction_request = llm_artifact.get("generation_interaction_request") if isinstance(llm_artifact.get("generation_interaction_request"), dict) else {}
            generation_attempts = llm_artifact.get("generation_attempts") if isinstance(llm_artifact.get("generation_attempts"), list) else []
            generation_preflight = llm_artifact.get("generation_preflight") if isinstance(llm_artifact.get("generation_preflight"), dict) else {}
            generation_failed_artifact = llm_artifact.get("generation_failed_artifact") if isinstance(llm_artifact.get("generation_failed_artifact"), dict) else {}
            if self._valid_generated_artifact(llm_artifact):
                files = llm_artifact["files"]
                input_schema = llm_artifact.get("input_schema") if isinstance(llm_artifact.get("input_schema"), dict) else input_schema
                output_schema = llm_artifact.get("output_schema") if isinstance(llm_artifact.get("output_schema"), dict) else output_schema
                connection_schema = self._closed_schema(llm_artifact.get("connection_schema"))
                secret_schema = self._closed_schema(llm_artifact.get("secret_schema"))
                verification_input = llm_artifact.get("verification_input") if isinstance(llm_artifact.get("verification_input"), dict) else self._generic_verification_input(input_schema, connection_schema, secret_schema)
                verification_input = self._verification_input_with_schema_sample(verification_input, input_schema, connection_schema, secret_schema)
                verification_expectations = llm_artifact.get("verification_expectations") if isinstance(llm_artifact.get("verification_expectations"), dict) else verification_expectations
                files = self._stabilize_standard_library_runtime_files(files, blueprint=blueprint)
                dependencies = self._merge_dependencies(dependencies, self._normalized_dependencies(llm_artifact.get("dependencies")))
                dependencies = self._drop_stdlib_dependencies(dependencies)
                capability_contract = self._capability_contract(tool_id=tool_id, blueprint={**blueprint, **llm_artifact})
                artifact_kind = "real_runtime_implementation"
            else:
                files = self._neutral_files(tool_id=tool_id, entrypoint=entrypoint, reason=generation_error or generation_status)
        else:
            files = self._neutral_files(tool_id=tool_id, entrypoint=entrypoint, reason="llm_generation_not_allowed_by_policy")

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
            "approval_policy": self._approval_policy_or_default(blueprint.get("approval_policy")),
            "runtime_interface": blueprint.get("runtime_interface") if isinstance(blueprint.get("runtime_interface"), dict) else {"input_mode": "json", "output_mode": "json"},
            "runtime_execution_policy": blueprint.get("runtime_execution_policy") if isinstance(blueprint.get("runtime_execution_policy"), dict) else {"side_effects": "runtime_declared"},
            "verification_input": verification_input,
            "verification_expectations": verification_expectations,
            "acquisition_policy": blueprint.get("acquisition_policy") if isinstance(blueprint.get("acquisition_policy"), dict) else {"allow_llm_code_generation": True},
            "capability_match_contract": capability_contract,
            "artifact_kind": artifact_kind,
            "blueprint_source": blueprint.get("blueprint_source") or "runtime_blueprint_planner",
            "code_generation": {
                "mode": "llm_or_supplied_files_only",
                "status": generation_status,
                "route": generation_route,
                "error": generation_error,
                **({"attempts": generation_attempts} if generation_attempts else {}),
                **({"preflight": generation_preflight} if generation_preflight else {}),
                **({"failed_artifact": generation_failed_artifact} if generation_failed_artifact else {}),
                **({"interaction_request": generation_interaction_request} if generation_interaction_request else {}),
            },
            "generated_at": self._now_iso(),
        }

    def _generate_with_llm(
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
    ) -> dict[str, Any]:
        base_complexity = self._generation_complexity(blueprint=blueprint, identity_contract=identity_contract)
        attempts: list[dict[str, Any]] = []
        previous_failure: dict[str, Any] | None = None
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
                compact=bool(attempt.get("compact")),
                previous_failure=previous_failure,
            )
            result = self.llm_client.complete_sync(
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
            preflight = self._preflight_generated_artifact(parsed, entrypoint=entrypoint, verification_input=verification_input)
            if not preflight.get("passed"):
                record["status"] = "preflight_failed"
                record["error"] = "Generated artifact did not pass local runtime preflight."
                record["preflight"] = preflight
                record["failed_artifact"] = self._artifact_failure_summary(parsed)
                previous_failure = {
                    "status": "preflight_failed",
                    "reason": preflight.get("reason"),
                    "stderr": str(preflight.get("stderr") or "")[-2000:],
                    "stdout": str(preflight.get("stdout") or "")[-1000:],
                    "verification_input": verification_input,
                    "artifact_summary": record.get("failed_artifact"),
                }
                attempts.append(record)
                continue
            parsed["generation_status"] = "completed"
            parsed["generation_route"] = route
            parsed["generation_attempts"] = attempts + [record]
            parsed["generation_preflight"] = preflight
            return parsed
        last = attempts[-1] if attempts else {}
        interaction_request = self._interaction_request_from_generation_attempts(attempts)
        return {
            "generation_status": "interaction_required" if interaction_request else str(last.get("status") or "llm_generation_failed"),
            "generation_route": last.get("route") if isinstance(last.get("route"), dict) else {},
            "generation_error": self._generation_failure_message(last),
            "generation_attempts": attempts,
            **({"generation_preflight": last.get("preflight")} if isinstance(last.get("preflight"), dict) else {}),
            **({"generation_failed_artifact": last.get("failed_artifact")} if isinstance(last.get("failed_artifact"), dict) else {}),
            **({"generation_interaction_request": interaction_request} if interaction_request else {}),
        }

    def _generation_failure_message(self, last_attempt: dict[str, Any]) -> str:
        error = str(last_attempt.get("error") or "LLM did not produce a registerable runtime artifact.")
        preflight = last_attempt.get("preflight") if isinstance(last_attempt.get("preflight"), dict) else {}
        if preflight:
            detail = {
                "reason": preflight.get("reason"),
                "returncode": preflight.get("returncode"),
                "stderr": str(preflight.get("stderr") or preflight.get("error") or "")[-1200:],
                "stdout": str(preflight.get("stdout") or "")[-600:],
            }
            return error + " | preflight=" + json.dumps(detail, ensure_ascii=False, default=str)
        return error

    def _artifact_failure_summary(self, artifact: dict[str, Any]) -> dict[str, Any]:
        files = artifact.get("files") if isinstance(artifact.get("files"), list) else []
        summarized: list[dict[str, str]] = []
        for item in files[:8]:
            if not isinstance(item, dict):
                continue
            content = str(item.get("content") or "")
            summarized.append({
                "path": str(item.get("path") or ""),
                "content_excerpt": content[:4000],
                "content_length": str(len(content)),
            })
        return {"files": summarized}

    def _interaction_request_from_generation_attempts(self, attempts: list[dict[str, Any]]) -> dict[str, Any]:
        fields: list[dict[str, Any]] = []
        seen: set[str] = set()
        for attempt in attempts or []:
            route = attempt.get("route") if isinstance(attempt.get("route"), dict) else {}
            request = route.get("interaction_request") if isinstance(route.get("interaction_request"), dict) else {}
            for field in request.get("fields", []) if isinstance(request.get("fields"), list) else []:
                if not isinstance(field, dict):
                    continue
                name = str(field.get("parameter_name") or field.get("name") or "").strip()
                if not name or name in seen:
                    continue
                seen.add(name)
                fields.append(field)
        if not fields:
            return {}
        return {
            "type": "provider_secret_configuration",
            "kind": "provider_secret_configuration",
            "message": "Provide missing provider secret values, or switch to an available local model.",
            "fields": fields,
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
        compact: bool = False,
        previous_failure: dict[str, Any] | None = None,
    ) -> list[dict[str, str]]:
        contract = {
            "tool_id": tool_id,
            "entrypoint": entrypoint,
            "blueprint": blueprint,
            "identity_contract": identity_contract,
            "input_schema": input_schema,
            "output_schema": output_schema,
            "connection_schema": connection_schema,
            "secret_schema": secret_schema,
            "verification_input": verification_input,
            **({"previous_failure": previous_failure} if previous_failure else {}),
            "required_return_shape": {
                "files": [{"path": "tool.py", "content": "Python source code"}, {"path": "test_tool.py", "content": "plain Python test source code"}],
                "input_schema": "JSON schema object",
                "output_schema": "JSON schema object",
                "connection_schema": "JSON schema object",
                "secret_schema": "JSON schema object",
                "dependencies": [{"package": "pip package name", "import_name": "python import name", "auto_install": True}],
                "verification_input": "JSON object used by sandbox validation",
                "verification_expectations": "JSON object",
                "capability_match_contract": "JSON object",
            },
        }
        if compact:
            contract = {
                "tool_id": tool_id,
                "entrypoint": entrypoint,
                "description": str(blueprint.get("description") or "")[:1800],
                "input_schema": input_schema,
                "output_schema": output_schema,
                "verification_input": verification_input,
                **({"previous_failure": previous_failure} if previous_failure else {}),
                "required_return_shape": contract["required_return_shape"],
            }
        system = (
            "You generate runtime capability artifacts as JSON only. "
            "Generate executable Python code that implements the supplied capability blueprint. "
            "Do not use hardcoded sample results. Do not add domain assumptions not present in the blueprint. "
            "Prefer the lowest sufficient implementation level first: standard-library and local deterministic code when it can satisfy the contract. "
            "When the supplied contract, verification target, or previous failure evidence requires packages, declare the minimal required runtime dependencies in the dependencies array with accurate package and import names so the dependency-resolution layer can install and validate them. "
            "Do not avoid dependencies by faking behavior, and do not add dependencies that are not needed for the verified objective. "
            "If external documentation, web evidence, or a stronger model is needed, rely only on evidence and routing supplied by the acquisition/repair pipeline; do not invent undocumented APIs, endpoints, or package behavior. "
            "Escalation is valid only when it is necessary to pass the declared verification contract and the generated artifact remains sandbox-testable. "
            "The entrypoint function must accept one optional dict payload and return a JSON-serializable dict. "
            "The generated artifact must execute successfully with the supplied verification_input exactly as provided; the test file should use that payload shape rather than inventing different sample values. "
            "If a default/sample value names a case-sensitive platform resource, the implementation must handle that value safely or report a structured failure quickly; it must not hang or depend on unavailable external data. "
            "The payload may be either direct input fields or a runtime envelope with input, connection, secrets, and _runtime keys; read user parameters from payload['input'] when it is a dict, otherwise from the top-level payload. "
            "Connection values declared in connection_schema must be read only from payload['connection']; secret values declared in secret_schema must be read only from payload['secrets']; do not duplicate connection or secret fields into input_schema or verification_input['input']. "
            "Do not store secrets in generated source code, generated manifests, tests, logs, or ordinary input fields; tests may use fake secret values only inside the secrets envelope or through mocks. "
            "all nested output values must be JSON-native values such as strings, numbers, booleans, lists, dicts, or null; never return runtime objects, class instances, file handles, exceptions, or other non-primitive runtime objects directly. "
            "Do not assume schema defaults or sample inputs are already canonical for the libraries you use; normalize user strings when the standard library accepts a stricter canonical spelling, and return structured JSON errors instead of uncaught exceptions when validation fails. "
            "The Python code must be real executable implementation code, not a placeholder, not blueprint-only, and not a stub. "
            "The test file must be a plain Python script that uses only standard-library imports and assert statements; "
            "do not import pytest or any external test runner. "
            "The test file must run locally without external network calls, assert the declared verification behavior, "
            "and verify that json.dumps(run(payload)) succeeds. "
            "The implementation must inspect a generic test-mode flag from the optional runtime envelope before any operation that can affect external state, contact a remote service, mutate local files, or require credentials; runtime flags may be absent during live execution, so read them with safe defaults rather than direct required-key indexing. "
            "When test-mode is true, return a successful structured verification result using local deterministic behavior only; do not initialize external clients, open network connections, require live credentials, or perform irreversible side effects. "
            "Live execution may use connection and secret envelopes after sandbox registration and approval, but the sandbox path must remain fully local and deterministic. "
            "If live end-to-end verification needs real user values, expose those values through input_schema, connection_schema, and secret_schema so the runtime interaction layer can ask the user after sandbox registration. "
            "When a standard-library feature needs a platform support package to satisfy the contract, declare the support package rather than the standard-library module itself. "
            "Never declare standard-library modules as pip dependencies. "
            "Return only a JSON object; no markdown, no prose."
        )
        user = "Generate the runtime artifact from this contract:\n" + json.dumps(contract, ensure_ascii=False, indent=2, default=str)
        return [{"role": "system", "content": system}, {"role": "user", "content": user}]

    def _clean_validation_env(self) -> dict[str, str]:
        clean: dict[str, str] = {}
        blocked_prefixes = ("PYDEVD", "DEBUGPY", "VSCODE", "PYCHARM")
        blocked_names = {
            "PYTHONPATH",
            "PYTHONHOME",
            "PYTHONSTARTUP",
        }
        for key, value in os.environ.items():
            upper = key.upper()
            if upper in blocked_names or any(upper.startswith(prefix) for prefix in blocked_prefixes):
                continue
            clean[key] = value
        clean["PYTHONBREAKPOINT"] = "0"
        clean["PYDEVD_DISABLE_FILE_VALIDATION"] = "1"
        clean.setdefault("PYTHONNOUSERSITE", "1")
        clean.setdefault("PYTHONDONTWRITEBYTECODE", "1")
        return clean

    def _debugger_subprocess_injection_active(self) -> bool:
        """Detect IDE/debugger modes that rewrite child Python command lines.

        VS Code/debugpy can monkey-patch subprocess creation and prepend a
        pydevd bootstrap to ``python -c`` calls. In that mode the preflight may
        stop inside debugpy's injected ``<string>`` before generated code runs.
        This check is capability-neutral and only protects the validation runner.
        """
        if sys.gettrace() is not None:
            return True
        module_names = " ".join(sys.modules.keys()).lower()
        if "debugpy" in module_names or "pydevd" in module_names:
            return True
        for key, value in os.environ.items():
            text = f"{key}={value}".lower()
            if "debugpy" in text or "pydevd" in text or "ms-python" in text:
                return True
        return False

    def _write_artifact_files_for_preflight(self, artifact: dict[str, Any], root: Path) -> None:
        files = artifact.get("files") if isinstance(artifact.get("files"), list) else []
        for item in files:
            if not isinstance(item, dict):
                continue
            rel = str(item.get("path") or "").replace("\\", "/").lstrip("/")
            if not rel or ".." in Path(rel).parts:
                continue
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(str(item.get("content") or ""), encoding="utf-8")

    def _preflight_generated_artifact_inprocess(
        self,
        artifact: dict[str, Any],
        *,
        entrypoint: dict[str, Any],
        verification_input: dict[str, Any],
        timeout_seconds: float = 12.0,
    ) -> dict[str, Any]:
        """Run preflight without spawning Python when a debugger owns subprocesses.

        This path exists only to avoid debugpy/pydevd child-process injection.
        It still imports the generated entrypoint from a temporary directory,
        calls the declared function with the exact verification envelope, and
        verifies JSON serialization.
        """
        module_name = str(entrypoint.get("module") or "tool.py")
        function_name = str(entrypoint.get("function") or "run")
        try:
            with tempfile.TemporaryDirectory(prefix="runtime_capability_preflight_") as tmp:
                root = Path(tmp)
                self._write_artifact_files_for_preflight(artifact, root)
                module_path = root / module_name
                if not module_path.exists():
                    return {"passed": False, "reason": "entrypoint_module_missing", "module": module_name}

                result_queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)

                def worker() -> None:
                    old_path = list(sys.path)
                    module_key = f"runtime_preflight_tool_{int(time.time() * 1000000)}"
                    try:
                        sys.path.insert(0, str(root))
                        spec = importlib.util.spec_from_file_location(module_key, str(module_path))
                        if not spec or not spec.loader:
                            raise RuntimeError("entrypoint_spec_loader_missing")
                        module = importlib.util.module_from_spec(spec)
                        spec.loader.exec_module(module)
                        fn = getattr(module, function_name)
                        payload = json.loads(json.dumps(verification_input, ensure_ascii=False, default=str))
                        result = fn(payload)
                        json.dumps(result, ensure_ascii=False)
                        result_queue.put({"passed": True, "reason": "", "stdout": "RUNTIME_PREFLIGHT_OK", "stderr": ""})
                    except BaseException as exc:
                        result_queue.put({
                            "passed": False,
                            "reason": "entrypoint_execution_or_json_serialization_failed",
                            "error": f"{type(exc).__name__}: {exc}"[:2000],
                            "stdout": "",
                            "stderr": "",
                        })
                    finally:
                        sys.path[:] = old_path
                        sys.modules.pop(module_key, None)

                thread = threading.Thread(target=worker, name="runtime-capability-preflight", daemon=True)
                thread.start()
                thread.join(timeout_seconds)
                if thread.is_alive():
                    return {
                        "passed": False,
                        "reason": "entrypoint_preflight_timeout",
                        "error": "in_process_preflight_timeout",
                    }
                try:
                    return result_queue.get_nowait()
                except queue.Empty:
                    return {"passed": False, "reason": "entrypoint_preflight_no_result"}
        except Exception as exc:
            return {"passed": False, "reason": "entrypoint_preflight_exception", "error": str(exc)[:1000]}

    def _preflight_generated_artifact(self, artifact: dict[str, Any], *, entrypoint: dict[str, Any], verification_input: dict[str, Any]) -> dict[str, Any]:
        """Run a small generic preflight before writing/registering a generated artifact.

        This is capability-neutral: it only verifies that the declared entrypoint
        can be imported, called with the exact verification envelope, and encoded
        as JSON. It does not inspect capability names or patch generated code.
        """
        module_name = str(entrypoint.get("module") or "tool.py")
        function_name = str(entrypoint.get("function") or "run")
        if self._debugger_subprocess_injection_active():
            result = self._preflight_generated_artifact_inprocess(
                artifact,
                entrypoint=entrypoint,
                verification_input=verification_input,
            )
            result.setdefault("mode", "in_process_debugger_safe")
            return result
        try:
            with tempfile.TemporaryDirectory(prefix="runtime_capability_preflight_") as tmp:
                root = Path(tmp)
                self._write_artifact_files_for_preflight(artifact, root)
                module_path = root / module_name
                if not module_path.exists():
                    return {"passed": False, "reason": "entrypoint_module_missing", "module": module_name}
                runner = (
                    "import importlib.util, json; "
                    f"module_path = {json.dumps(str(module_path))}; "
                    f"function_name = {json.dumps(function_name)}; "
                    f"payload = json.loads({json.dumps(json.dumps(verification_input, ensure_ascii=False, default=str))}); "
                    "spec = importlib.util.spec_from_file_location('runtime_preflight_tool', module_path); "
                    "module = importlib.util.module_from_spec(spec); "
                    "assert spec and spec.loader; "
                    "spec.loader.exec_module(module); "
                    "result = getattr(module, function_name)(payload); "
                    "json.dumps(result, ensure_ascii=False); "
                    "print('RUNTIME_PREFLIGHT_OK')"
                )
                proc = subprocess.run(
                    [sys.executable, "-I", "-c", runner],
                    cwd=str(root),
                    env=self._clean_validation_env(),
                    text=True,
                    capture_output=True,
                    timeout=12,
                )
                debug_injected = "debugpy" in (proc.stderr or "").lower() or "pydevd" in (proc.stderr or "").lower()
                if debug_injected:
                    retry = self._preflight_generated_artifact_inprocess(
                        artifact, entrypoint=entrypoint, verification_input=verification_input
                    )
                    retry.setdefault("mode", "in_process_debugger_safe_retry")
                    return retry
                return {
                    "passed": proc.returncode == 0,
                    "reason": "" if proc.returncode == 0 else "entrypoint_execution_or_json_serialization_failed",
                    "returncode": proc.returncode,
                    "stdout": (proc.stdout or "")[-2000:],
                    "stderr": (proc.stderr or "")[-3000:],
                }
        except subprocess.TimeoutExpired as exc:
            timeout_material = (str(getattr(exc, "stdout", "") or "") + str(getattr(exc, "stderr", "") or "")).lower()
            if "debugpy" in timeout_material or "pydevd" in timeout_material:
                retry = self._preflight_generated_artifact_inprocess(
                    artifact, entrypoint=entrypoint, verification_input=verification_input
                )
                retry.setdefault("mode", "in_process_debugger_safe_timeout_retry")
                return retry
            return {
                "passed": False,
                "reason": "entrypoint_preflight_timeout",
                "stdout": str(getattr(exc, "stdout", "") or "")[-1000:],
                "stderr": str(getattr(exc, "stderr", "") or "")[-1000:],
            }
        except Exception as exc:
            return {"passed": False, "reason": "entrypoint_preflight_exception", "error": str(exc)[:1000]}


    def _normalized_dependencies(self, value: Any) -> list[dict[str, Any]]:
        """Normalize dependency declarations inside the artifact generator.

        This is intentionally generic. It only normalizes declared package/module
        metadata and does not infer capability/domain behavior.
        """
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
            normalized = {
                "package": package or import_name,
                "import_name": import_name or package.replace("-", "_"),
                "auto_install": bool(item.get("auto_install", True)),
            }
            if item.get("source"):
                normalized["source"] = item.get("source")
            result.append(normalized)
        return result

    def _merge_dependencies(self, left: list[dict[str, Any]], right: list[dict[str, Any]]) -> list[dict[str, Any]]:
        merged: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for item in [*(left or []), *(right or [])]:
            if not isinstance(item, dict):
                continue
            package = str(item.get("package") or item.get("name") or "").strip()
            import_name = str(item.get("import_name") or item.get("module") or "").strip()
            if not package and not import_name:
                continue
            key = (package, import_name)
            if key in seen:
                continue
            seen.add(key)
            merged.append({
                "package": package or import_name,
                "import_name": import_name or package.replace("-", "_"),
                "auto_install": bool(item.get("auto_install", True)),
                **({"source": item.get("source")} if item.get("source") else {}),
            })
        return merged

    def _drop_stdlib_dependencies(self, dependencies: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Keep runtime dependency manifests limited to external packages.

        Uses Python's stdlib module names when available. This avoids writing
        domain/capability-specific exclusions in the generator.
        """
        stdlib = set(getattr(sys, "stdlib_module_names", set()) or set())
        result: list[dict[str, Any]] = []
        for item in dependencies or []:
            if not isinstance(item, dict):
                continue
            import_name = str(item.get("import_name") or item.get("module") or "").strip().split(".", 1)[0]
            package = str(item.get("package") or item.get("name") or "").strip().replace("-", "_").split(".", 1)[0]
            if import_name and import_name in stdlib:
                continue
            if package and package in stdlib:
                continue
            result.append(item)
        return result

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
        # Keep capability acquisition predictable: a declared basic/local task must
        # not be silently escalated into hosted/critical routes just because a
        # local attempt failed. Repair evidence is passed back to the same policy
        # band first; broader escalation must be selected by runtime policy or a
        # user-approved provider configuration, not by capability-specific code.
        base = str(base_complexity or "default").strip().lower()
        if base == "default":
            sequence = ["medium"]
        elif base == "basic":
            sequence = ["basic"]
        elif base == "medium":
            sequence = ["medium"]
        elif base == "high":
            sequence = ["high"]
        else:
            sequence = [base if base in {"basic", "medium", "high", "critical"} else "medium"]
        attempts: list[dict[str, Any]] = []
        for complexity in sequence:
            attempts.append({"complexity": complexity, "force_json": True, "compact": False, "phase": "initial"})
            attempts.append({"complexity": complexity, "force_json": True, "compact": False, "phase": "repair_full"})
            attempts.append({"complexity": complexity, "force_json": False, "compact": True, "phase": "repair_compact"})
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
            if name in required or "default" in (field_schema if isinstance(field_schema, dict) else {}):
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
