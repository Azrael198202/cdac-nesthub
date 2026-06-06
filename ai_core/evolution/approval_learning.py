from __future__ import annotations

import json
from datetime import datetime
from difflib import SequenceMatcher
from typing import Any

from ai_core.config.paths import RUNTIME_DATASETS, RUNTIME_KNOWLEDGE


class ApprovalLearningService:
    def __init__(self) -> None:
        RUNTIME_DATASETS.mkdir(parents=True, exist_ok=True)
        RUNTIME_KNOWLEDGE.mkdir(parents=True, exist_ok=True)
        self.approved_outputs_path = RUNTIME_DATASETS / "approved_outputs.jsonl"
        self.success_patterns_path = RUNTIME_KNOWLEDGE / "success_patterns.jsonl"
        self.prompt_memory_path = RUNTIME_KNOWLEDGE / "prompt_optimization_memory.jsonl"

    def record_approval(
        self,
        *,
        run_id: str,
        node_id: str,
        user_input: str,
        approved_output: dict[str, Any],
        feedback: str | None = None,
    ) -> None:
        record = {
            "created_at": datetime.utcnow().isoformat(),
            "type": "approved_output",
            "run_id": run_id,
            "node_id": node_id,
            "user_input": user_input,
            "approved_output": approved_output,
            "feedback": feedback or "",
        }
        self._append_jsonl(self.approved_outputs_path, record)
        pattern = {
            "created_at": record["created_at"],
            "memory_type": "success_pattern",
            "node_id": node_id,
            "user_input": user_input,
            "approved_structure": approved_output,
            "feedback": feedback or "",
            "recommendation": "For similar future tasks, prefer this approved output structure.",
            "source_run_id": run_id,
        }
        self._append_jsonl(self.success_patterns_path, pattern)
        self._append_jsonl(self.prompt_memory_path, pattern)

    def build_prompt_reinforcement(self, *, node_id: str, user_input: str) -> str:
        items = self._retrieve(node_id=node_id, user_input=user_input)
        if not items:
            return ""
        lines = [
            "Approved output memory for this node:",
            "These are positive user-approved structures. Prefer similar structure when appropriate.",
        ]
        for i, item in enumerate(items, start=1):
            lines.append(f"\nApproved pattern {i}:")
            if item.get("feedback"):
                lines.append(f"- Approval note: {item.get('feedback')}")
            lines.append("- Approved output:")
            lines.append(json.dumps(item.get("approved_output", {}), ensure_ascii=False, indent=2))
        return "\n".join(lines)

    def _retrieve(self, *, node_id: str, user_input: str, limit: int = 3) -> list[dict[str, Any]]:
        if not self.approved_outputs_path.exists():
            return []
        scored = []
        with self.approved_outputs_path.open("r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if item.get("node_id") != node_id:
                    continue
                score = SequenceMatcher(None, user_input.lower(), item.get("user_input", "").lower()).ratio()
                if score >= 0.15:
                    item["_score"] = score
                    scored.append(item)
        scored.sort(key=lambda x: x.get("_score", 0), reverse=True)
        return scored[:limit]

    def _append_jsonl(self, path, record: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
