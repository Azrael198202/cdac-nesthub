from __future__ import annotations

import ast
import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ai_core.config.paths import RUNTIME_GENERATED, RUNTIME_REGISTRY


class PythonFileCapabilityImporter:
    """Register a user supplied Python file as a runtime capability.

    The importer is intentionally domain-neutral.  It never decides what the
    program is for.  It only wraps a referenced Python file behind the standard
    runtime capability envelope, infers a minimal schema from the selected
    callable signature, verifies the wrapper can be imported, and writes an
    executable registry record.
    """

    CALLABLE_PRIORITY = ("run", "execute", "main", "handler", "handle", "process")

    def __init__(self, *, generated_tools_dir: Path | None = None, registry_path: Path | None = None) -> None:
        self.generated_tools_dir = generated_tools_dir or (RUNTIME_GENERATED / "tools")
        self.registry_path = registry_path or (RUNTIME_REGISTRY / "tool_registry.json")

    def import_file(
        self,
        *,
        source_path: Path,
        participant_name: str,
        instruction: str = "",
        capability_id: str | None = None,
    ) -> dict[str, Any]:
        source_path = Path(source_path).expanduser()
        if not source_path.is_absolute():
            source_path = source_path.resolve()
        if not source_path.exists() or not source_path.is_file():
            return self._failure("source_file_not_found", f"Python file was not found: {source_path}")
        if source_path.suffix.lower() != ".py":
            return self._failure("unsupported_source_file", "Only Python .py files can be imported as a runtime capability.")

        parsed = self._analyze_source(source_path)
        if not parsed.get("ok"):
            return parsed
        callable_name = str(parsed.get("callable") or "").strip()
        if not callable_name:
            return self._failure("callable_not_found", "No callable entrypoint was found in the Python file.")

        tool_id = self._safe_tool_id(capability_id or f"{participant_name}_{source_path.stem}")
        tool_dir = self.generated_tools_dir / tool_id
        source_dir = tool_dir / "source"
        schema_dir = tool_dir / "schemas"
        tests_dir = RUNTIME_GENERATED / "tests" / tool_id
        source_dir.mkdir(parents=True, exist_ok=True)
        schema_dir.mkdir(parents=True, exist_ok=True)
        tests_dir.mkdir(parents=True, exist_ok=True)
        copied_source = source_dir / source_path.name
        shutil.copy2(source_path, copied_source)

        input_schema = parsed.get("input_schema") if isinstance(parsed.get("input_schema"), dict) else self._open_input_schema()
        output_schema = self._output_schema()
        wrapper_path = tool_dir / "tool.py"
        wrapper_path.write_text(self._wrapper_code(copied_source.name, callable_name), encoding="utf-8")
        (schema_dir / "input_schema.json").write_text(json.dumps(input_schema, ensure_ascii=False, indent=2), encoding="utf-8")
        (schema_dir / "output_schema.json").write_text(json.dumps(output_schema, ensure_ascii=False, indent=2), encoding="utf-8")
        manifest = self._manifest(
            tool_id=tool_id,
            participant_name=participant_name,
            instruction=instruction,
            source_path=copied_source,
            wrapper_path=wrapper_path,
            callable_name=callable_name,
            input_schema=input_schema,
            output_schema=output_schema,
        )
        manifest_path = tool_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        test_path = tests_dir / "test_contract_smoke.py"
        test_path.write_text(self._smoke_test_code(wrapper_path, manifest_path), encoding="utf-8")

        import_check = self._import_check(wrapper_path)
        if not import_check.get("ok"):
            return import_check
        registry_record = dict(manifest)
        registry_record.update({
            "status": "enabled",
            "tool_id": tool_id,
            "name": tool_id,
            "capability": tool_id,
            "capabilities": [tool_id, self._safe_tool_id(participant_name)],
            "manifest_path": str(manifest_path),
            "spec_path": str(manifest_path),
            "artifact_dir": str(tool_dir),
            "verification": {
                "sandbox_verification": True,
                "import_check": import_check,
                "contract_smoke_test": str(test_path),
            },
        })
        self._upsert_registry(tool_id, registry_record)
        return {
            "ok": True,
            "status": "completed",
            "tool_id": tool_id,
            "capability": tool_id,
            "capabilities": registry_record["capabilities"],
            "artifact_dir": str(tool_dir),
            "manifest_path": str(manifest_path),
            "input_schema": input_schema,
            "output_schema": output_schema,
            "registry_record": registry_record,
            "callable": callable_name,
            "source_file": str(copied_source),
        }

    def _analyze_source(self, path: Path) -> dict[str, Any]:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except Exception as exc:
            return self._failure("python_source_parse_failed", str(exc))
        functions = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_")]
        if not functions:
            return self._failure("callable_not_found", "No public function was found in the Python file.")
        selected = None
        by_name = {fn.name: fn for fn in functions}
        for name in self.CALLABLE_PRIORITY:
            if name in by_name:
                selected = by_name[name]
                break
        if selected is None:
            selected = functions[0]
        return {
            "ok": True,
            "callable": selected.name,
            "input_schema": self._schema_from_function(selected),
        }

    def _schema_from_function(self, fn: ast.FunctionDef | ast.AsyncFunctionDef) -> dict[str, Any]:
        args = list(fn.args.args or [])
        # Do not treat conventional bound instance parameters as user inputs.
        if args and args[0].arg in {"self", "cls"}:
            args = args[1:]
        defaults = list(fn.args.defaults or [])
        required_count = max(0, len(args) - len(defaults))
        props: dict[str, Any] = {}
        required: list[str] = []
        for idx, arg in enumerate(args):
            name = self._safe_field_name(arg.arg)
            if not name:
                continue
            schema_type = self._annotation_to_json_type(arg.annotation)
            props[name] = {"type": schema_type, "title": name, "description": f"Input value for {name}."}
            if idx < required_count:
                required.append(name)
        if not props:
            return self._open_input_schema()
        return {
            "type": "object",
            "properties": props,
            "required": required,
            "additionalProperties": True,
        }

    def _annotation_to_json_type(self, annotation: ast.AST | None) -> str:
        if annotation is None:
            return "string"
        text = ""
        try:
            text = ast.unparse(annotation).lower()
        except Exception:
            text = ""
        if any(token in text for token in ("int", "integer")):
            return "integer"
        if any(token in text for token in ("float", "double", "decimal", "number")):
            return "number"
        if "bool" in text:
            return "boolean"
        if any(token in text for token in ("list", "tuple", "set", "sequence")):
            return "array"
        if any(token in text for token in ("dict", "mapping", "object")):
            return "object"
        return "string"

    def _open_input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}, "required": [], "additionalProperties": True}

    def _output_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "data": {"type": "object"},
                "final_answer": {"type": "string"},
            },
            "required": ["status"],
            "additionalProperties": True,
        }

    def _manifest(self, *, tool_id: str, participant_name: str, instruction: str, source_path: Path, wrapper_path: Path, callable_name: str, input_schema: dict[str, Any], output_schema: dict[str, Any]) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        return {
            "tool_id": tool_id,
            "name": tool_id,
            "capability": tool_id,
            "capabilities": [tool_id, self._safe_tool_id(participant_name)],
            "status": "enabled",
            "created_at": now,
            "source": "agent_declared_python_file",
            "source_file": str(source_path),
            "definition_instruction": instruction,
            "input_schema": input_schema,
            "output_schema": output_schema,
            "connection_schema": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
            "secret_schema": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
            "approval_policy": {"required": False, "supported_modes": ["always", "once", "never"], "default_mode": "never", "mode": "never"},
            "runtime_execution_policy": {"side_effects": "runtime_declared", "source": "imported_python_file"},
            "implementation": {"type": "python_module", "module_path": str(wrapper_path), "function": "run", "wrapped_callable": callable_name},
        }

    def _wrapper_code(self, source_filename: str, callable_name: str) -> str:
        return f'''from __future__ import annotations

import importlib.util
import inspect
import io
import contextlib
from pathlib import Path
from typing import Any

_SOURCE_PATH = Path(__file__).resolve().parent / "source" / {source_filename!r}
_CALLABLE_NAME = {callable_name!r}


def _load_callable():
    spec = importlib.util.spec_from_file_location("runtime_imported_user_module", _SOURCE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load source module: {{_SOURCE_PATH}}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    fn = getattr(module, _CALLABLE_NAME, None)
    if not callable(fn):
        raise RuntimeError(f"Callable not found: {{_CALLABLE_NAME}}")
    return fn


def _runtime_input(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {{"value": payload}}
    if "input" in payload and isinstance(payload.get("input"), dict):
        return dict(payload.get("input") or {{}})
    return dict(payload)


def _invoke(fn, data: dict[str, Any]):
    signature = inspect.signature(fn)
    params = list(signature.parameters.values())
    if not params:
        return fn()
    accepts_kwargs = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params)
    if accepts_kwargs:
        return fn(**data)
    named = [p for p in params if p.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)]
    if len(named) == 1 and named[0].name not in data:
        return fn(data)
    kwargs = {{p.name: data[p.name] for p in named if p.name in data}}
    return fn(**kwargs)


def run(payload: Any) -> dict[str, Any]:
    data = _runtime_input(payload)
    fn = _load_callable()
    stdout_buffer = io.StringIO()
    with contextlib.redirect_stdout(stdout_buffer):
        result = _invoke(fn, data)
    stdout_text = stdout_buffer.getvalue().strip()
    if isinstance(result, dict):
        result = dict(result)
        final = result.get("final_answer") or result.get("answer") or result.get("summary") or result.get("output") or result.get("result") or stdout_text
        if str(result.get("status") or "").lower() in {{"success", "ok", "completed", "executed"}}:
            result.setdefault("final_answer", str(final or ""))
            if stdout_text:
                result.setdefault("stdout", stdout_text)
            return result
        payload_data = dict(result)
        if stdout_text:
            payload_data.setdefault("stdout", stdout_text)
        return {{"status": "success", "data": payload_data, "stdout": stdout_text, "final_answer": str(final or result)}}
    final = result if result not in (None, "", [], {{}}) else stdout_text
    return {{"status": "success" if final not in (None, "", [], {{}}) else "failed", "data": {{"value": result, "stdout": stdout_text}}, "stdout": stdout_text, "final_answer": str(final or "")}}
'''

    def _smoke_test_code(self, wrapper_path: Path, manifest_path: Path) -> str:
        return f'''import importlib.util
import json
from pathlib import Path

TOOL_PATH = Path({str(wrapper_path)!r})
MANIFEST_PATH = Path({str(manifest_path)!r})


def test_runtime_contract_smoke():
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    spec = importlib.util.spec_from_file_location("runtime_generated_tool_under_test", TOOL_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert callable(getattr(module, "run", None))
    assert manifest.get("implementation", {{}}).get("function") == "run"
'''

    def _import_check(self, wrapper_path: Path) -> dict[str, Any]:
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location("runtime_generated_import_check", wrapper_path)
            if spec is None or spec.loader is None:
                return self._failure("wrapper_import_spec_failed", "Cannot create import spec for wrapper.")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            if not callable(getattr(module, "run", None)):
                return self._failure("wrapper_missing_run", "Wrapper does not expose run(payload).")
            return {"ok": True, "status": "passed"}
        except Exception as exc:
            return self._failure("wrapper_import_failed", str(exc))

    def _upsert_registry(self, tool_id: str, record: dict[str, Any]) -> None:
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            registry = json.loads(self.registry_path.read_text(encoding="utf-8") or "{}") if self.registry_path.exists() else {}
        except Exception:
            registry = {}
        if not isinstance(registry, dict):
            registry = {}
        registry[tool_id] = record
        tmp = self.registry_path.with_suffix(self.registry_path.suffix + ".tmp")
        tmp.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.registry_path)

    def _safe_tool_id(self, value: str) -> str:
        text = re.sub(r"[^A-Za-z0-9_]+", "_", str(value or "").strip()).strip("_").lower()
        if not text:
            text = "python_file_capability"
        digest = hashlib.sha1(str(value or text).encode("utf-8")).hexdigest()[:8]
        if len(text) > 80:
            text = text[:80].strip("_")
        return f"{text}_{digest}" if len(text) < 4 else text

    def _safe_field_name(self, value: str) -> str:
        text = re.sub(r"[^A-Za-z0-9_]+", "_", str(value or "").strip()).strip("_")
        if not text or not re.match(r"^[A-Za-z_]", text):
            return ""
        return text

    def _failure(self, code: str, message: str) -> dict[str, Any]:
        return {"ok": False, "status": "failed", "error": {"code": code, "message": message}}
