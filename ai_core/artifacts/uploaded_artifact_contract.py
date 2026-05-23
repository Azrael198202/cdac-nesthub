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
                properties[arg.arg] = self._schema_from_annotation(arg.annotation)
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

    def _schema_from_annotation(self, annotation: ast.AST | None) -> dict[str, Any]:
        """Map Python type annotations to a small JSON-schema shape.

        This is intentionally domain-neutral. It only reads the syntax of the
        callable signature and never infers meaning from parameter names.
        """
        if annotation is None:
            return {"type": "string"}
        text = self._annotation_text(annotation).replace(" ", "")
        lowered = text.casefold()
        if lowered in {"list", "list[str]", "typing.list[str]", "sequence[str]", "typing.sequence[str]", "tuple[str]", "typing.tuple[str]"} or lowered.startswith("list[") or lowered.startswith("typing.list["):
            return {"type": "array", "items": {"type": "string"}}
        if lowered in {"int", "integer"}:
            return {"type": "integer"}
        if lowered in {"float", "double", "number"}:
            return {"type": "number"}
        if lowered in {"bool", "boolean"}:
            return {"type": "boolean"}
        if "list[" in lowered or "sequence[" in lowered or "tuple[" in lowered:
            return {"type": "array", "items": {"type": "string"}}
        return {"type": "string"}

    def _annotation_text(self, annotation: ast.AST) -> str:
        try:
            return ast.unparse(annotation)
        except Exception:
            if isinstance(annotation, ast.Name):
                return annotation.id
            if isinstance(annotation, ast.Attribute):
                return annotation.attr
            if isinstance(annotation, ast.Subscript):
                return self._annotation_text(annotation.value)
            return ""

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
            for key in ("known_parameters", "parameter_values", "parameters", "values", "runtime_inputs", "runtime_parameters", "provided_inputs"):
                value = container.get(key)
                if isinstance(value, dict):
                    src = value.get("known") if isinstance(value.get("known"), dict) else value
                    for k, v in src.items():
                        if self._is_usable_runtime_value(v):
                            known[str(k)] = v
        return known

    def _is_usable_runtime_value(self, value: Any) -> bool:
        """Return True only for concrete user/runtime values.

        Planner stages often use placeholder strings such as "missing" when a
        value still has to be collected.  Those placeholders must not satisfy an
        uploaded callable's real input contract; otherwise the UI will not ask
        for the callable parameter and execution will be blocked later.  This is
        generic placeholder filtering, not business/domain logic.
        """
        if value in (None, "", [], {}):
            return False
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return False
            normalized = re.sub(r"[^a-z0-9]+", "_", text.casefold()).strip("_")
            placeholder_values = {
                "missing", "not_provided", "not_available", "none", "null",
                "unknown", "undefined", "required", "todo", "tbd", "n_a", "na",
                "placeholder", "sample", "example",
            }
            if normalized in placeholder_values:
                return False
            if text.startswith("<") and text.endswith(">"):
                return False
            if text.startswith("{") and text.endswith("}"):
                return False
        return True

    def _missing_inputs(self, artifact: dict[str, Any], known: dict[str, Any]) -> list[dict[str, Any]]:
        """Return UI fields for missing callable inputs.

        Required parameters block execution when absent. Optional parameters are
        included in the same UI request when any required input is missing, so a
        user can provide optional values before the artifact runs without making
        those values mandatory.
        """
        contract = artifact.get("input_contract") if isinstance(artifact.get("input_contract"), dict) else {}
        properties = contract.get("properties") if isinstance(contract.get("properties"), dict) else {}
        required = [str(x) for x in (contract.get("required") if isinstance(contract.get("required"), list) else [])]
        fields: list[dict[str, Any]] = []
        missing_required: list[str] = []
        for name in required:
            if self._known_value_for_required_field(name, known) in (None, "", [], {}):
                missing_required.append(name)
        if not missing_required:
            return []
        ordered_names: list[str] = []
        for name in missing_required:
            if name not in ordered_names:
                ordered_names.append(name)
        for name in properties.keys():
            text = str(name).strip()
            if text and text not in ordered_names and self._known_value_for_required_field(text, known) in (None, "", [], {}):
                ordered_names.append(text)
        for name in ordered_names:
            required_flag = name in missing_required
            schema = properties.get(name) if isinstance(properties.get(name), dict) else {"type": "string"}
            fields.append(self._parameter_field(name, schema=schema, required=required_flag))
        return fields

    def _parameter_field(self, name: str, *, schema: dict[str, Any], required: bool) -> dict[str, Any]:
        value_type = str(schema.get("type") or "string")
        input_type = "list" if value_type == "array" else ("number" if value_type in {"integer", "number"} else "text")
        label = self._human_label(name)
        description = "This value is required by the selected uploaded artifact." if required else "Optional value accepted by the selected uploaded artifact."
        return {
            "name": name,
            "label": label,
            "required": required,
            "field": name,
            "type": input_type,
            "input_type": input_type,
            "placeholder": ("Enter one value, then add it" if input_type == "list" else "Enter " + label),
            "description": description,
            "source": "uploaded_artifact_contract",
            "aliases": self._aliases_for_required_field(name),
            "merge_targets": [{"source_field": name}],
            "item_type": schema.get("items", {}).get("type") if isinstance(schema.get("items"), dict) else None,
        }

    def _known_value_for_required_field(self, name: str, known: dict[str, Any]) -> Any:
        if not isinstance(known, dict):
            return None
        candidates = [name] + self._aliases_for_required_field(name)
        normalized_candidates = {self._normalize_key(item) for item in candidates if item}
        for key, value in known.items():
            if not self._is_usable_runtime_value(value):
                continue
            if key in candidates or self._normalize_key(key) in normalized_candidates:
                return value
        return None

    def _aliases_for_required_field(self, name: str) -> list[str]:
        text = str(name or "").strip()
        aliases = [text]
        compact = text.replace("_", "")
        dashed = text.replace("_", "-")
        spaced = text.replace("_", " ")
        camel = self._snake_to_camel(text)
        aliases.extend([compact, dashed, spaced, camel])
        return list(dict.fromkeys(a for a in aliases if a))

    def _snake_to_camel(self, value: str) -> str:
        parts = [p for p in str(value or "").split("_") if p]
        if not parts:
            return ""
        return parts[0] + "".join(p[:1].upper() + p[1:] for p in parts[1:])

    def _normalize_key(self, value: Any) -> str:
        return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().casefold())

    def _human_label(self, value: str) -> str:
        text = str(value or "").strip().replace("_", " ")
        return text[:1].upper() + text[1:] if text else "Input"

    def _safe_name(self, value: str) -> str:
        text = re.sub(r"[^a-zA-Z0-9_.-]+", "_", str(value or "artifact"))[:80].strip("._")
        return text or "artifact"
