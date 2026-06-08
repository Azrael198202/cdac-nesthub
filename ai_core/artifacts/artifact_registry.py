from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from uuid import uuid4

from ai_core.config.paths import PROJECT_ROOT, RUNTIME_DIR


class UploadedArtifactRegistry:
    """Generic registry for user-uploaded runtime artifacts.

    This registry is intentionally domain-neutral. It links user-visible file
    references (filename or artifact_id) to a stored artifact record so planning
    can select the fixed use_uploaded_file action and execution_preparation can
    inspect the file. It does not decide what the file is for.
    """

    def __init__(self, registry_path: Path | None = None) -> None:
        self.registry_path = registry_path or (RUNTIME_DIR / "uploads" / "artifact_registry.json")

    def ensure(self) -> Path:
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.registry_path.exists():
            self.registry_path.write_text("[]", encoding="utf-8")
        return self.registry_path

    def list(self) -> list[dict[str, Any]]:
        path = self.ensure()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def write(self, items: list[dict[str, Any]]) -> None:
        path = self.ensure()
        path.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")

    def register_file(self, *, source_path: Path, original_name: str | None = None, mime_type: str = "", role: str = "method_candidate") -> dict[str, Any]:
        items = self.list()
        original = Path(original_name or source_path.name).name
        existing_ids = {str(item.get("artifact_id")) for item in items if isinstance(item, dict)}
        artifact_id = f"artifact_{uuid4().hex[:12]}"
        while artifact_id in existing_ids:
            artifact_id = f"artifact_{uuid4().hex[:12]}"
        item = {
            "artifact_id": artifact_id,
            "name": original,
            "filename": original,
            "path": str(source_path),
            "mime_type": mime_type,
            "size_bytes": source_path.stat().st_size if source_path.exists() else 0,
            "role": role,
            "source": "agent_studio_upload",
        }
        items.append(item)
        self.write(items)
        return item

    def normalize_records(self, records: Any) -> list[dict[str, Any]]:
        if not isinstance(records, list):
            records = []
        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        registry_by_id = {str(x.get("artifact_id") or x.get("id") or ""): x for x in self.list() if isinstance(x, dict)}
        registry_by_name = {str(x.get("filename") or x.get("name") or "").lower(): x for x in self.list() if isinstance(x, dict)}
        for item in records:
            if isinstance(item, str):
                ref = self.resolve_reference(item) or {"filename": Path(item).name, "name": Path(item).name, "path": item}
            elif isinstance(item, dict):
                artifact_id = str(item.get("artifact_id") or item.get("id") or "").strip()
                filename = str(item.get("filename") or item.get("name") or "").strip()
                ref = registry_by_id.get(artifact_id) or registry_by_name.get(filename.lower()) or item
            else:
                continue
            norm = self._normalize_one(ref)
            key = str(norm.get("artifact_id") or norm.get("path") or norm.get("filename") or "").strip()
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(norm)
        return out

    def resolve_reference(self, reference: str) -> dict[str, Any] | None:
        ref = str(reference or "").strip()
        if not ref:
            return None
        ref_name = Path(ref).name.lower()
        ref_lower = ref.lower()
        for item in self.list():
            if not isinstance(item, dict):
                continue
            candidates = [
                str(item.get("artifact_id") or ""),
                str(item.get("id") or ""),
                str(item.get("filename") or ""),
                str(item.get("name") or ""),
                Path(str(item.get("path") or "")).name,
            ]
            for cand in candidates:
                cand_lower = cand.lower()
                if cand_lower and cand_lower in {ref_lower, ref_name}:
                    return self._normalize_one(item)
        return None

    def resolve_from_text(self, text: str) -> list[dict[str, Any]]:
        body = str(text or "")
        if not body.strip():
            return []
        refs: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in self.list():
            if not isinstance(item, dict):
                continue
            names = [
                str(item.get("filename") or ""),
                str(item.get("name") or ""),
                Path(str(item.get("path") or "")).name,
                str(item.get("artifact_id") or ""),
            ]
            matched = False
            for name in names:
                if not name:
                    continue
                if re.search(r"(?<![\w./-])" + re.escape(name) + r"(?![\w./-])", body, flags=re.I):
                    matched = True
                    break
            if matched:
                norm = self._normalize_one(item)
                key = str(norm.get("artifact_id") or norm.get("path") or "")
                if key and key not in seen:
                    seen.add(key)
                    refs.append(norm)
        return refs

    def bind_for_instruction(self, instruction: str, explicit_records: Any) -> list[dict[str, Any]]:
        explicit = self.normalize_records(explicit_records)
        by_ref = {str(x.get("artifact_id") or x.get("path") or x.get("filename")): x for x in explicit}
        for item in self.resolve_from_text(instruction):
            by_ref.setdefault(str(item.get("artifact_id") or item.get("path") or item.get("filename")), item)
        return list(by_ref.values())

    def _normalize_one(self, item: dict[str, Any]) -> dict[str, Any]:
        path = str(item.get("path") or item.get("filepath") or item.get("file_path") or item.get("local_path") or "").strip()
        filename = str(item.get("filename") or item.get("name") or Path(path).name).strip()
        artifact_id = str(item.get("artifact_id") or item.get("id") or filename or path).strip()
        return {
            "artifact_id": artifact_id,
            "name": str(item.get("name") or filename or artifact_id),
            "filename": filename,
            "path": path,
            "mime_type": str(item.get("mime_type") or item.get("content_type") or ""),
            "size_bytes": item.get("size_bytes") or 0,
            "role": str(item.get("role") or "method_candidate"),
            "source": str(item.get("source") or "artifact_registry"),
            "resolved_by": str(item.get("resolved_by") or "registry"),
        }
