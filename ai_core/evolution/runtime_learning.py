from __future__ import annotations

import json
from datetime import datetime
from difflib import SequenceMatcher
from typing import Any

from ai_core.config.paths import RUNTIME_DATASETS, RUNTIME_KNOWLEDGE


class RuntimeLearningService:
    """
    Generic runtime learning service.

    It is node-agnostic:
    - records reject feedback
    - records human JSON corrections
    - retrieves similar corrections for any node
    - builds prompt reinforcement for current node execution
    """

    def __init__(self) -> None:
        RUNTIME_DATASETS.mkdir(parents=True, exist_ok=True)
        RUNTIME_KNOWLEDGE.mkdir(parents=True, exist_ok=True)

        self.corrections_path = RUNTIME_DATASETS / "corrections.jsonl"
        self.rejects_path = RUNTIME_DATASETS / "reject_feedback.jsonl"
        self.prompt_memory_path = RUNTIME_KNOWLEDGE / "prompt_optimization_memory.jsonl"

    def record_reject_feedback(
        self,
        *,
        run_id: str,
        node_id: str,
        user_input: str,
        original_output: dict[str, Any],
        feedback: str,
    ) -> None:
        record = {
            "created_at": datetime.utcnow().isoformat(),
            "type": "reject_feedback",
            "run_id": run_id,
            "node_id": node_id,
            "user_input": user_input,
            "original_output": original_output,
            "feedback": feedback,
        }
        self._append_jsonl(self.rejects_path, record)

        memory = {
            "created_at": record["created_at"],
            "memory_type": "prompt_feedback",
            "node_id": node_id,
            "feedback": feedback,
            "recommendation": self._recommendation_from_feedback(feedback),
            "source_run_id": run_id,
        }
        self._append_jsonl(self.prompt_memory_path, memory)

    def record_correction(
        self,
        *,
        run_id: str,
        node_id: str,
        user_input: str,
        original_output: dict[str, Any],
        modified_output: dict[str, Any],
        feedback: str | None = None,
    ) -> None:
        record = {
            "created_at": datetime.utcnow().isoformat(),
            "type": "human_json_correction",
            "run_id": run_id,
            "node_id": node_id,
            "user_input": user_input,
            "original_output": original_output,
            "modified_output": modified_output,
            "human_corrected_output": modified_output,
            "feedback": feedback or "",
        }
        self._append_jsonl(self.corrections_path, record)

        memory = {
            "created_at": record["created_at"],
            "memory_type": "prompt_optimization",
            "node_id": node_id,
            "feedback": feedback or "",
            "recommendation": (
                "For similar future tasks, prefer the human_corrected_output structure. "
                "Do not repeat the original_output structure if it conflicts with the correction."
            ),
            "source_run_id": run_id,
        }
        self._append_jsonl(self.prompt_memory_path, memory)

    def retrieve_similar_corrections(
        self,
        *,
        node_id: str,
        user_input: str,
        limit: int = 3,
        min_score: float = 0.15,
    ) -> list[dict[str, Any]]:
        items = []

        for path in [self.corrections_path, self.rejects_path]:
            if not path.exists():
                continue

            with path.open("r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        item = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    if item.get("node_id") != node_id:
                        continue

                    score = self._score(user_input, item.get("user_input", ""))
                    if score >= min_score:
                        item["_score"] = score
                        items.append(item)

        items.sort(key=lambda x: x.get("_score", 0), reverse=True)
        return items[:limit]

    def build_prompt_reinforcement(self, *, node_id: str, user_input: str) -> str:
        similar = self.retrieve_similar_corrections(node_id=node_id, user_input=user_input)
        if not similar:
            return ""

        lines = [
            "Runtime learning memory for this node:",
            "Use these prior corrections/rejections to avoid repeating known mistakes.",
        ]

        for i, item in enumerate(similar, start=1):
            lines.append(f"\nMemory {i}:")
            lines.append(f"- Type: {item.get('type')}")
            if item.get("feedback"):
                lines.append(f"- Human feedback: {item.get('feedback')}")

            if item.get("original_output") is not None:
                lines.append("- Previous incorrect output:")
                lines.append(json.dumps(item.get("original_output"), ensure_ascii=False, indent=2))

            corrected = item.get("modified_output") or item.get("human_corrected_output")
            if corrected is not None:
                lines.append("- Human corrected output:")
                lines.append(json.dumps(corrected, ensure_ascii=False, indent=2))

        return "\n".join(lines)

    def _score(self, a: str, b: str) -> float:
        if not a or not b:
            return 0.0
        return SequenceMatcher(None, a.lower(), b.lower()).ratio()

    def _recommendation_from_feedback(self, feedback: str) -> str:
        feedback_l = feedback.lower()
        if "task_id" in feedback_l or "task_type" in feedback_l or "structured object" in feedback_l:
            return "Tasks should be structured objects with task_id, task_type, action, and parameters."
        if "confirmation" in feedback_l or "approval" in feedback_l or "irreversible" in feedback_l:
            return "Irreversible or externally mutating actions require explicit human confirmation."
        if "missing_information" in feedback_l or "missing information" in feedback_l:
            return "missing_information should include all required information absent from the user input."
        return "Follow human feedback in future prompt generation."

    def _append_jsonl(self, path, record: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
