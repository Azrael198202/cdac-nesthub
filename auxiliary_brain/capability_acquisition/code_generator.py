from __future__ import annotations

import ast
import json
import re
import sys
import time
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
        verification_input = blueprint.get("verification_input") if isinstance(blueprint.get("verification_input"), dict) else self._generic_verification_input(input_schema)
        verification_expectations = blueprint.get("verification_expectations") if isinstance(blueprint.get("verification_expectations"), dict) else {"status": "completed"}
        capability_contract = self._capability_contract(tool_id=tool_id, blueprint=blueprint)
        files = blueprint.get("files") if isinstance(blueprint.get("files"), list) else []
        artifact_kind = "blueprint_only_not_registerable"
        generation_status = "not_attempted"
        generation_route: dict[str, Any] = {}
        generation_error = ""
        dependencies = self._normalized_dependencies(blueprint.get("dependencies"))

        if self._valid_files(files) and not self._files_look_like_stub(files):
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
            if self._valid_generated_artifact(llm_artifact):
                files = llm_artifact["files"]
                input_schema = llm_artifact.get("input_schema") if isinstance(llm_artifact.get("input_schema"), dict) else input_schema
                output_schema = llm_artifact.get("output_schema") if isinstance(llm_artifact.get("output_schema"), dict) else output_schema
                connection_schema = self._closed_schema(llm_artifact.get("connection_schema"))
                secret_schema = self._closed_schema(llm_artifact.get("secret_schema"))
                verification_input = llm_artifact.get("verification_input") if isinstance(llm_artifact.get("verification_input"), dict) else self._generic_verification_input(input_schema)
                verification_expectations = llm_artifact.get("verification_expectations") if isinstance(llm_artifact.get("verification_expectations"), dict) else verification_expectations
                dependencies = self._merge_dependencies(dependencies, self._normalized_dependencies(llm_artifact.get("dependencies")))
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
            "approval_policy": blueprint.get("approval_policy") if isinstance(blueprint.get("approval_policy"), dict) else {"mode": "required_for_side_effects", "preview_required": True},
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
        compact: bool = False,
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
                "required_return_shape": contract["required_return_shape"],
            }
        system = (
            "You generate runtime capability artifacts as JSON only. "
            "Generate executable Python code that implements the supplied capability blueprint. "
            "Do not use hardcoded sample results. Do not add domain assumptions not present in the blueprint. "
            "Use only the Python standard library unless the blueprint explicitly permits dependencies. "
            "The entrypoint function must accept one optional dict payload and return a JSON-serializable dict; "
            "all nested output values must be JSON-native values such as strings, numbers, booleans, lists, dicts, or null. "
            "The Python code must be real executable implementation code, not a placeholder, not blueprint-only, and not a stub. "
            "The test file must be a plain Python script that uses only standard-library imports and assert statements; "
            "do not import pytest or any external test runner. "
            "The test file must run locally without external network calls, assert the declared verification behavior, "
            "and verify that json.dumps(run(payload)) succeeds. "
            "Return only a JSON object; no markdown, no prose."
        )
        user = "Generate the runtime artifact from this contract:\n" + json.dumps(contract, ensure_ascii=False, indent=2, default=str)
        return [{"role": "system", "content": system}, {"role": "user", "content": user}]

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
            attempts.append({"complexity": complexity, "force_json": True, "compact": False})
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

    def _generic_verification_input(self, input_schema: dict[str, Any]) -> dict[str, Any]:
        props = input_schema.get("properties") if isinstance(input_schema.get("properties"), dict) else {}
        required = input_schema.get("required") if isinstance(input_schema.get("required"), list) else []
        runtime_input: dict[str, Any] = {"dry_run": True}
        for name, schema in props.items():
            if name == "dry_run":
                continue
            if name in required or "default" in (schema if isinstance(schema, dict) else {}):
                runtime_input[name] = self._sample_value(schema if isinstance(schema, dict) else {})
        return {"input": runtime_input, "connection": {}, "secrets": {}, "_runtime": {"dry_run": True}}

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
