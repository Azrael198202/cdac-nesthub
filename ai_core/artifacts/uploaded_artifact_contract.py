from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

from ai_core.config.paths import PROJECT_ROOT, RUNTIME_DIR
from ai_core.artifacts.artifact_registry import UploadedArtifactRegistry


@dataclass
class UploadedArtifactRef:
    artifact_id: str
    path: str
    name: str
    mime_type: str = ""
    role: str = "method_candidate"


class UploadedArtifactContractBuilder:
    """Build execution contracts for user-provided artifacts.

    The class is generic: it does not know any business/domain task. It only
    collects uploaded file references, inspects callable shapes where possible,
    and creates UI parameter requests when a file requires missing inputs.
    """

    def __init__(self) -> None:
        self.registry = UploadedArtifactRegistry()

    FILE_REF_KEYS = (
        "uploaded_files", "uploaded_artifacts", "available_artifacts", "attachments", "files", "file_refs",
        "artifact_refs", "source_files", "method_files", "external_files",
    )

    def collect_refs(self, *, state: dict[str, Any], step: dict[str, Any]) -> list[UploadedArtifactRef]:
        raw: list[Any] = []
        for container in self._containers(state=state, step=step):
            if not isinstance(container, dict):
                continue
            for key in self.FILE_REF_KEYS:
                if key in container:
                    raw.append(container.get(key))
        text_blob = self._joined_text(state=state, step=step)
        for item in self.registry.resolve_from_text(text_blob):
            raw.append(item)

        # Deterministic uploaded-artifact binding guard.  When the locked action
        # is an uploaded-file execution, a user-visible filename may be present
        # only in upstream stage text, or the UI may have uploaded exactly one
        # candidate file for the current session.  Resolve that before asking an
        # LLM or falling back to ask_user.  This is generic resource binding, not
        # domain/business logic.
        if not raw and self._step_requests_uploaded_artifact(step):
            registry_items = self.registry.list()
            if len(registry_items) == 1 and isinstance(registry_items[0], dict):
                raw.append(registry_items[0])

        refs: list[UploadedArtifactRef] = []
        seen: set[str] = set()
        for item in raw:
            for ref in self._coerce_refs(item):
                if ref.path in seen:
                    continue
                seen.add(ref.path)
                refs.append(ref)
        return refs

    def build_contract(self, *, state: dict[str, Any], step: dict[str, Any], step_id: str) -> dict[str, Any]:
        refs = self.collect_refs(state=state, step=step)
        contracts = [self.inspect_ref(ref) for ref in refs]
        selected = next((item for item in contracts if item.get("exists")), contracts[0] if contracts else {})
        known = self._known_values(state=state, step=step)
        missing = self._missing_inputs(selected, known)
        return {
            "required": True,
            "step_id": step_id,
            "artifact_refs": [asdict(ref) for ref in refs],
            "selected_artifact": selected,
            "input_contract": selected.get("input_contract") or {"type": "object", "additionalProperties": True},
            "known_parameter_values": known,
            "missing_parameter_fields": missing,
            "ui_parameter_request": {
                "type": "collect_runtime_parameters",
                "fields": missing,
                "reason": "The selected uploaded artifact requires runtime parameter values before execution.",
            } if missing else None,
            "execution_policy": {
                "sandbox_required": True,
                "use_uploaded_artifact_as_method": True,
                "preserve_artifact_path_as_evidence": True,
            },
            "approved_in_preparation": bool(selected.get("exists")) and not missing,
            "status": "missing_parameters" if missing else ("prepared" if selected.get("exists") else "missing_artifact"),
        }


    def _step_requests_uploaded_artifact(self, step: dict[str, Any]) -> bool:
        text_parts: list[str] = []
        def visit(value: Any, depth: int = 0) -> None:
            if depth > 4:
                return
            if isinstance(value, str):
                text_parts.append(value)
            elif isinstance(value, dict):
                for nested in value.values():
                    visit(nested, depth + 1)
            elif isinstance(value, list):
                for item in value:
                    visit(item, depth + 1)
        visit(step)
        text = " ".join(text_parts).casefold()
        action = str(step.get("action_type") or step.get("execution_action") or "").casefold()
        method = str(step.get("execution_method") or "").casefold()
        return (action == "use_uploaded_file" or method == "uploaded_artifact" or "use_uploaded_file" in text or "uploaded_artifact" in text)

    def inspect_ref(self, ref: UploadedArtifactRef) -> dict[str, Any]:
        path = self._safe_path(ref.path)
        base = asdict(ref)
        base["resolved_path"] = str(path) if path else ""
        base["exists"] = bool(path and path.exists() and path.is_file())
        base["input_contract"] = {"type": "object", "additionalProperties": True, "required": []}
        base["execution_entrypoint"] = {"type": "unknown"}
        base["inspection"] = {"status": "not_read"}
        if not base["exists"]:
            base["inspection"] = {"status": "missing_file"}
            return base
        suffix = path.suffix.lower()
        if suffix == ".py":
            base.update(self._inspect_python(path))
        else:
            base["inspection"] = {"status": "generic_file", "suffix": suffix}
        return base

    def write_manifest(self, *, state: dict[str, Any], step_id: str, contract: dict[str, Any]) -> str:
        run_id = str(state.get("run_id") or "unknown_run")
        out_dir = RUNTIME_DIR / "sessions" / run_id / "uploaded_artifacts"
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{self._safe_name(step_id)}_artifact_contract.json"
        path.write_text(json.dumps(contract, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(path.relative_to(PROJECT_ROOT))

    def _containers(self, *, state: dict[str, Any], step: dict[str, Any]):
        yield step
        for key in ("parameters", "metadata", "data", "execution_decision", "external_artifact", "uploaded_artifact"):
            value = step.get(key) if isinstance(step, dict) else None
            if isinstance(value, dict):
                yield value
        results = state.get("results") if isinstance(state.get("results"), dict) else {}
        for stage in results.values():
            for nested in self._iter_nested(stage, max_depth=5):
                yield nested
        runtime_context = state.get("runtime_context") if isinstance(state.get("runtime_context"), dict) else {}
        yield runtime_context
        yield state

    def _joined_text(self, *, state: dict[str, Any], step: dict[str, Any]) -> str:
        parts: list[str] = []
        def visit(value: Any, depth: int = 0) -> None:
            if depth > 5:
                return
            if isinstance(value, str):
                parts.append(value)
            elif isinstance(value, dict):
                for key in ("original_input", "user_input", "instruction", "objective", "content", "target", "query", "filename", "name", "artifact_id"):
                    raw = value.get(key)
                    if isinstance(raw, str):
                        parts.append(raw)
                for nested in value.values():
                    visit(nested, depth + 1)
            elif isinstance(value, list):
                for item in value:
                    visit(item, depth + 1)
        visit(step)
        visit(state)
        return "\n".join(part for part in parts if part)

    def _iter_nested(self, value: Any, *, max_depth: int):
        if max_depth < 0:
            return
        if isinstance(value, dict):
            yield value
            for nested in value.values():
                yield from self._iter_nested(nested, max_depth=max_depth - 1)
        elif isinstance(value, list):
            for item in value:
                yield from self._iter_nested(item, max_depth=max_depth - 1)

    def _coerce_refs(self, value: Any) -> list[UploadedArtifactRef]:
        if value in (None, "", [], {}):
            return []
        if isinstance(value, list):
            refs: list[UploadedArtifactRef] = []
            for item in value:
                refs.extend(self._coerce_refs(item))
            return refs
        if isinstance(value, str):
            resolved = self.registry.resolve_reference(value)
            if resolved:
                return self._coerce_refs(resolved)
            name = Path(value).name
            return [UploadedArtifactRef(artifact_id=self._safe_name(value), path=value, name=name)]
        if isinstance(value, dict):
            if not (value.get("path") or value.get("filepath") or value.get("file_path") or value.get("local_path")):
                ref = value.get("artifact_id") or value.get("id") or value.get("filename") or value.get("name")
                resolved = self.registry.resolve_reference(str(ref or ""))
                if resolved:
                    value = resolved
            path = value.get("path") or value.get("filepath") or value.get("file_path") or value.get("local_path") or value.get("uri") or value.get("url")
            if not path:
                return []
            return [UploadedArtifactRef(
                artifact_id=str(value.get("artifact_id") or value.get("id") or self._safe_name(str(path))),
                path=str(path),
                name=str(value.get("name") or value.get("filename") or Path(str(path)).name),
                mime_type=str(value.get("mime_type") or value.get("content_type") or ""),
                role=str(value.get("role") or "method_candidate"),
            )]
        return []

    def _safe_path(self, value: str) -> Path | None:
        text = str(value or "").strip()
        if not text or re.match(r"^https?://", text, flags=re.I):
            return None
        # Registry records may be created on Windows and later read on a
        # POSIX runtime (or vice versa).  Normalize separators before resolving
        # relative paths so runtime\uploads\... can be found reliably.
        normalized_text = text.replace("\\", "/")
        path = Path(normalized_text)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        try:
            resolved = path.resolve()
        except Exception:
            return None
        project = PROJECT_ROOT.resolve()
        runtime = RUNTIME_DIR.resolve()
        allowed_roots = (project, runtime, Path("/mnt/data").resolve())
        if not any(str(resolved).startswith(str(root)) for root in allowed_roots):
            return None
        return resolved

    def _inspect_python(self, path: Path) -> dict[str, Any]:
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source, filename=str(path))
        except Exception as exc:
            return {"inspection": {"status": "parse_failed", "error": str(exc)}}
        functions = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
        selected = next((fn for fn in functions if fn.name == "run"), functions[0] if functions else None)
        required: list[str] = []
        properties: dict[str, Any] = {}
        entrypoint = {"type": "python_module", "function": selected.name if selected else ""}
        if selected:
            args = list(selected.args.args)
            defaults = list(selected.args.defaults)
            default_offset = len(args) - len(defaults)
            for idx, arg in enumerate(args):
                if arg.arg in {"self", "cls"}:
                    continue
                properties[arg.arg] = {"type": "string"}
                if idx < default_offset:
                    required.append(arg.arg)
            if len(args) == 1 and args[0].arg in {"payload", "input", "data", "params"}:
                required = []
                properties = {}
                entrypoint["payload_style"] = "single_object"
        argparse_required = self._extract_argparse_required(tree)
        for name in argparse_required:
            properties.setdefault(name, {"type": "string"})
            if name not in required:
                required.append(name)
        return {
            "inspection": {"status": "parsed", "language": "python", "function_count": len(functions)},
            "execution_entrypoint": entrypoint,
            "input_contract": {
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": True,
            },
        }

    def _extract_argparse_required(self, tree: ast.AST) -> list[str]:
        required: list[str] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Attribute) or func.attr != "add_argument":
                continue
            names = []
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    names.append(arg.value)
            is_required = any(isinstance(kw.value, ast.Constant) and kw.arg == "required" and kw.value.value is True for kw in node.keywords)
            if not is_required:
                continue
            chosen = next((name for name in names if name.startswith("--")), names[0] if names else "")
            chosen = chosen.lstrip("-").replace("-", "_")
            if chosen:
                required.append(chosen)
        return required

    def _known_values(self, *, state: dict[str, Any], step: dict[str, Any]) -> dict[str, Any]:
        known: dict[str, Any] = {}
        for container in self._containers(state=state, step=step):
            if not isinstance(container, dict):
                continue
            for key in ("known_parameters", "parameter_values", "parameters", "values", "runtime_inputs"):
                value = container.get(key)
                if isinstance(value, dict):
                    src = value.get("known") if isinstance(value.get("known"), dict) else value
                    for k, v in src.items():
                        if v not in (None, "", [], {}):
                            known[str(k)] = v
        return known

    def _missing_inputs(self, artifact: dict[str, Any], known: dict[str, Any]) -> list[dict[str, Any]]:
        contract = artifact.get("input_contract") if isinstance(artifact.get("input_contract"), dict) else {}
        required = contract.get("required") if isinstance(contract.get("required"), list) else []
        fields = []
        for name in required:
            text = str(name).strip()
            if text and known.get(text) in (None, "", [], {}):
                fields.append({"name": text, "label": text, "required": True, "source": "uploaded_artifact_contract"})
        return fields

    def _safe_name(self, value: str) -> str:
        text = re.sub(r"[^a-zA-Z0-9_.-]+", "_", str(value or "artifact"))[:80].strip("._")
        return text or "artifact"
