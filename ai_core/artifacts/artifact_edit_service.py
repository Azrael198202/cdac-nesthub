from __future__ import annotations

import json
import shutil
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from ai_core.artifacts.artifact_registry import UploadedArtifactRegistry
from ai_core.config.paths import PROJECT_ROOT, RUNTIME_DIR
from ai_core.llm.provider_router import ProviderRouter


@dataclass
class ArtifactEditProposal:
    proposal_id: str
    artifact_id: str
    original_path: str
    draft_path: str
    instruction: str
    status: str


class ArtifactEditService:
    """Create reviewable edited copies of uploaded artifacts.

    The service is intentionally artifact-generic. It never mutates the original
    file until the user confirms a proposal. Confirmation creates a backup of the
    previous original and then replaces the artifact content with the reviewed
    draft. The UI can request another revision with feedback before confirming.
    """

    def __init__(self) -> None:
        self.registry = UploadedArtifactRegistry()
        self.proposal_dir = RUNTIME_DIR / "uploads" / "edit_proposals"
        self.backup_dir = RUNTIME_DIR / "uploads" / "backups"
        self.applied_dir = RUNTIME_DIR / "uploads" / "applied_edits"
        self._ensure_dirs()

    def _ensure_dirs(self) -> None:
        """Ensure artifact edit runtime directories exist before every file write.

        Runtime directories may be cleaned while the server process is still alive
        during local testing.  The service therefore does not rely only on
        __init__; every write path calls this method first.
        """
        self.proposal_dir.mkdir(parents=True, exist_ok=True)
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self.applied_dir.mkdir(parents=True, exist_ok=True)

    def list_artifacts(self) -> list[dict[str, Any]]:
        return self.registry.list()

    def get_artifact(self, artifact_id: str) -> dict[str, Any] | None:
        artifact_id = str(artifact_id or "").strip()
        for item in self.registry.list():
            if isinstance(item, dict) and str(item.get("artifact_id") or item.get("id") or "") == artifact_id:
                return item
        return None

    async def propose_edit(self, *, artifact_id: str, instruction: str, feedback: str = "", base_proposal_id: str = "", new_content: str | None = None) -> dict[str, Any]:
        artifact = self.get_artifact(artifact_id)
        if not artifact:
            return {"ok": False, "status": "not_found", "message": "Artifact was not found."}
        original = self._safe_path(str(artifact.get("path") or ""))
        if not original or not original.exists() or not original.is_file():
            return {"ok": False, "status": "missing_file", "message": "Artifact file does not exist."}
        base_text = self._read_text(original)
        if base_proposal_id:
            previous = self._proposal_meta_path(base_proposal_id)
            if previous.exists():
                try:
                    prev_meta = json.loads(previous.read_text(encoding="utf-8"))
                    draft = self._safe_path(str(prev_meta.get("draft_path") or ""))
                    if draft and draft.exists():
                        base_text = self._read_text(draft)
                except Exception:
                    pass
        if new_content is not None:
            edited = str(new_content)
            generation = {"mode": "user_supplied_content"}
        else:
            deterministic = self._try_deterministic_edit(
                base_text=base_text,
                instruction=instruction,
                feedback=feedback,
                filename=str(artifact.get("filename") or original.name),
            )
            if deterministic is not None:
                edited, generation = deterministic
            else:
                edited, generation = await self._generate_edit(base_text=base_text, instruction=instruction, feedback=feedback, filename=str(artifact.get("filename") or original.name))
        self._ensure_dirs()
        proposal_id = "edit_" + uuid4().hex[:12]
        suffix = original.suffix or ".txt"
        draft_path = self.proposal_dir / f"{proposal_id}{suffix}"
        draft_path.parent.mkdir(parents=True, exist_ok=True)
        draft_path.write_text(edited, encoding="utf-8")
        meta = {
            "proposal_id": proposal_id,
            "artifact_id": artifact_id,
            "artifact_name": artifact.get("filename") or artifact.get("name") or original.name,
            "original_path": str(original),
            "draft_path": str(draft_path),
            "instruction": instruction,
            "feedback": feedback,
            "status": "pending_review",
            "created_at": self._now(),
            "generation": generation,
            "download_url": f"/api/agent-studio/artifact-edit/{proposal_id}/download",
        }
        meta_path = self._proposal_meta_path(proposal_id)
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"ok": True, "status": "pending_review", "proposal": meta, "preview": edited[:4000]}

    def confirm(self, proposal_id: str) -> dict[str, Any]:
        meta = self._read_meta(proposal_id)
        if not meta:
            return {"ok": False, "status": "not_found", "message": "Edit proposal was not found."}
        original = self._safe_path(str(meta.get("original_path") or ""))
        draft = self._safe_path(str(meta.get("draft_path") or ""))
        if not original or not draft or not draft.exists():
            return {"ok": False, "status": "missing_file", "message": "Original or draft file is missing."}
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        backup = self.backup_dir / f"{Path(original).stem}.{proposal_id}.backup{Path(original).suffix}"
        if original.exists():
            shutil.copy2(original, backup)
        shutil.copy2(draft, original)
        meta["status"] = "confirmed"
        meta["confirmed_at"] = self._now()
        meta["backup_path"] = str(backup)
        meta_path = self._proposal_meta_path(proposal_id)
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        self._mark_registry_replacement(str(meta.get("artifact_id") or ""), backup_path=str(backup), proposal_id=proposal_id)
        return {"ok": True, "status": "confirmed", "proposal": meta}

    def cancel(self, proposal_id: str) -> dict[str, Any]:
        meta = self._read_meta(proposal_id)
        if not meta:
            return {"ok": False, "status": "not_found", "message": "Edit proposal was not found."}
        meta["status"] = "cancelled"
        meta["cancelled_at"] = self._now()
        meta_path = self._proposal_meta_path(proposal_id)
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"ok": True, "status": "cancelled", "proposal": meta}

    def _mark_registry_replacement(self, artifact_id: str, *, backup_path: str, proposal_id: str) -> None:
        items = self.registry.list()
        for item in items:
            if isinstance(item, dict) and str(item.get("artifact_id") or item.get("id") or "") == artifact_id:
                item.setdefault("backups", []).append({"path": backup_path, "proposal_id": proposal_id, "created_at": self._now()})
                item["last_edit_proposal_id"] = proposal_id
                item["updated_at"] = self._now()
        self.registry.write(items)

    def _try_deterministic_edit(self, *, base_text: str, instruction: str, feedback: str, filename: str) -> tuple[str, dict[str, Any]] | None:
        """Apply small, safe structural edits without asking the LLM.

        This is intentionally generic: it only triggers when the user explicitly
        asks to convert named function parameters to list types. It preserves the
        original function by renaming it to a private single-call helper, then
        adds a thin public wrapper that accepts scalar or list inputs and loops
        through the cartesian product. This prevents an edit request from getting
        stuck in a review dialog with only an advisory text response.
        """
        combined = f"{instruction}\n{feedback}".lower()
        if not filename.lower().endswith(".py"):
            return None
        if "list" not in combined or "parameter" not in combined:
            return None

        params = []
        for name in re.findall(r"`([A-Za-z_]\w*)`", instruction + "\n" + feedback):
            if name not in params:
                params.append(name)
        if not params:
            # Fallback to conservative known identifiers mentioned as words.
            for name in re.findall(r"\b([A-Za-z_]\w*)\b", instruction + "\n" + feedback):
                if name not in {"change", "parameters", "parameter", "file", "list", "types", "function", "accept", "multiple", "and", "the", "to", "so", "that", "can", "information", "for", "dates", "cities"} and name not in params:
                    params.append(name)
        if not params:
            return None

        lines = base_text.splitlines()
        def_index = None
        def_indent = ""
        def_name = ""
        sig_line = ""
        for i, line in enumerate(lines):
            m = re.match(r"^(\s*)def\s+([A-Za-z_]\w*)\s*\((.*?)\)\s*:\s*$", line)
            if not m:
                continue
            signature_params = m.group(3)
            if any(re.search(rf"(^|[,\s]){re.escape(param)}\s*(:|=|,|$)", signature_params) for param in params):
                def_index = i
                def_indent = m.group(1)
                def_name = m.group(2)
                sig_line = line
                break
        if def_index is None or not def_name:
            return None

        # Find function block end by indentation.
        block_end = len(lines)
        for j in range(def_index + 1, len(lines)):
            line = lines[j]
            if line.strip() and not line.startswith(def_indent + " ") and not line.startswith(def_indent + "\t"):
                block_end = j
                break

        original_block = lines[def_index:block_end]
        helper_name = f"_{def_name}_single"
        original_block[0] = re.sub(r"def\s+" + re.escape(def_name) + r"\s*\(", f"def {helper_name}(", original_block[0], count=1)

        # Extract parameter defaults from original signature.
        sig_match = re.match(r"^(\s*)def\s+[A-Za-z_]\w*\s*\((.*?)\)\s*:\s*$", sig_line)
        original_params_raw = [part.strip() for part in (sig_match.group(2) if sig_match else "").split(",") if part.strip()]
        selected = [p for p in params if any(re.match(rf"{re.escape(p)}\b", raw) for raw in original_params_raw)]
        if not selected:
            return None
        wrapper_params = []
        for raw in original_params_raw:
            name = re.split(r"[:=]", raw, 1)[0].strip()
            if name in selected:
                if "=" in raw:
                    default = raw.split("=", 1)[1].strip()
                    wrapper_params.append(f"{name}: List[str] = {default}")
                else:
                    wrapper_params.append(f"{name}: List[str]")
            else:
                wrapper_params.append(raw)

        loop_names = []
        prep_lines = []
        for name in selected:
            plural = f"{name}_items"
            loop_names.append((name, plural))
            prep_lines.append(f"{def_indent}    {plural} = {name} if isinstance({name}, list) else ([{name}] if {name} is not None else [None])")
        call_args = []
        for raw in original_params_raw:
            name = re.split(r"[:=]", raw, 1)[0].strip()
            if name in selected:
                call_args.append(f"one_{name}")
            else:
                call_args.append(name)
        wrapper = [f"{def_indent}def {def_name}({', '.join(wrapper_params)}):"]
        wrapper += prep_lines
        if len(loop_names) == 1:
            name, plural = loop_names[0]
            wrapper.append(f"{def_indent}    for one_{name} in {plural}:")
            wrapper.append(f"{def_indent}        {helper_name}({', '.join(call_args)})")
        else:
            first_name, first_plural = loop_names[0]
            wrapper.append(f"{def_indent}    for one_{first_name} in {first_plural}:")
            current_indent = def_indent + "        "
            for name, plural in loop_names[1:]:
                wrapper.append(f"{current_indent}for one_{name} in {plural}:")
                current_indent += "    "
            wrapper.append(f"{current_indent}{helper_name}({', '.join(call_args)})")

        new_lines = lines[:def_index] + wrapper + [""] + original_block + lines[block_end:]
        edited = "\n".join(new_lines) + ("\n" if base_text.endswith("\n") else "")
        if "List" in edited and not re.search(r"from\s+typing\s+import\s+.*\bList\b", edited):
            insert_at = 0
            while insert_at < len(new_lines) and (new_lines[insert_at].startswith("#!") or new_lines[insert_at].startswith("# -*-")):
                insert_at += 1
            new_lines.insert(insert_at, "from typing import List")
            edited = "\n".join(new_lines) + ("\n" if base_text.endswith("\n") else "")
        return edited, {"mode": "deterministic_python_list_parameter_edit", "changed_parameters": selected}

    async def _generate_edit(self, *, base_text: str, instruction: str, feedback: str, filename: str) -> tuple[str, dict[str, Any]]:
        schema = {
            "type": "object",
            "required": ["modified_content"],
            "properties": {
                "modified_content": {"type": "string"},
                "change_summary": {"type": "string"},
            },
            "additionalProperties": False,
        }
        prompt = {
            "system": "You edit one uploaded file. Return JSON only. Preserve the file language and runnable structure unless the user explicitly asks otherwise.",
            "user": "Edit the file content according to the instruction and optional feedback.",
        }
        rendered = (
            f"Filename: {filename}\n"
            f"Instruction:\n{instruction}\n\n"
            f"Feedback for this revision:\n{feedback}\n\n"
            f"Current file content:\n```\n{base_text[:12000]}\n```\n"
            "Return only JSON with modified_content and change_summary."
        )
        try:
            result = await ProviderRouter().generate_json(
                run_id="artifact_edit_" + uuid4().hex[:8],
                node_id="artifact_edit",
                adapter={"provider_timeout_seconds": 120, "max_prompt_tokens": 6000, "provider_options": {"temperature": 0}},
                prompt=prompt,
                rendered_user_prompt=rendered,
                schema=schema,
            )
            content = str(result.get("modified_content") or "")
            if content.strip():
                return content, {"mode": "llm_edit", "change_summary": result.get("change_summary")}
        except Exception as exc:
            # Return a reviewable draft rather than mutating the original.  The UI
            # clearly shows that the automated edit could not be produced.
            fallback = base_text + "\n\n# Edit instruction could not be applied automatically.\n# User instruction:\n# " + instruction.replace("\n", "\n# ") + "\n"
            return fallback, {"mode": "fallback_review_draft", "error": str(exc)}
        return base_text, {"mode": "unchanged_empty_generation"}

    def _proposal_meta_path(self, proposal_id: str) -> Path:
        self._ensure_dirs()
        clean = "".join(ch for ch in str(proposal_id or "") if ch.isalnum() or ch in "_-.")[:80]
        return self.proposal_dir / f"{clean}.json"

    def _read_meta(self, proposal_id: str) -> dict[str, Any] | None:
        path = self._proposal_meta_path(proposal_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else None
        except Exception:
            return None

    def _safe_path(self, value: str) -> Path | None:
        text = str(value or "").replace("\\", "/").strip()
        if not text:
            return None
        path = Path(text)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        try:
            resolved = path.resolve()
        except Exception:
            return None
        allowed = (PROJECT_ROOT.resolve(), RUNTIME_DIR.resolve(), Path("/mnt/data").resolve())
        if not any(str(resolved).startswith(str(root)) for root in allowed):
            return None
        return resolved

    def _read_text(self, path: Path) -> str:
        return path.read_text(encoding="utf-8", errors="replace")

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()
