import json
from datetime import datetime
from difflib import SequenceMatcher
from ai_core.config.paths import RUNTIME_DATASETS, RUNTIME_KNOWLEDGE


class CorrectionLearningService:
    """
    Runtime learning service for human JSON correction.
    """

    def __init__(self) -> None:
        RUNTIME_DATASETS.mkdir(parents=True, exist_ok=True)
        RUNTIME_KNOWLEDGE.mkdir(parents=True, exist_ok=True)
        self.corrections_path = RUNTIME_DATASETS / "corrections.jsonl"
        self.prompt_memory_path = RUNTIME_KNOWLEDGE / "prompt_optimization_memory.jsonl"

    def record_correction(
        self,
        run_id: str,
        node_id: str,
        user_input: str,
        original_output: dict,
        modified_output: dict,
        feedback: str | None = None,
    ) -> None:
        record = {
            "created_at": datetime.utcnow().isoformat(),
            "run_id": run_id,
            "node_id": node_id,
            "user_input": user_input,
            "original_output": original_output,
            "modified_output": modified_output,
            "feedback": feedback or "",
            "learning_type": "human_json_correction",
        }

        with self.corrections_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\\n")

        memory = {
            "created_at": record["created_at"],
            "node_id": node_id,
            "pattern": feedback or "Human modified JSON result.",
            "recommendation": "Prefer the human-corrected JSON structure for similar future inputs.",
            "source_run_id": run_id,
        }

        with self.prompt_memory_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(memory, ensure_ascii=False) + "\\n")

    def retrieve_similar(self, node_id: str, user_input: str, limit: int = 3) -> list[dict]:
        if not self.corrections_path.exists():
            return []

        scored = []
        with self.corrections_path.open("r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if item.get("node_id") != node_id:
                    continue
                score = SequenceMatcher(
                    None,
                    user_input.lower(),
                    item.get("user_input", "").lower(),
                ).ratio()
                scored.append((score, item))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [item for score, item in scored[:limit] if score >= 0.15]

    def build_prompt_reinforcement(self, node_id: str, user_input: str) -> str:
        items = self.retrieve_similar(node_id, user_input)
        if not items:
            return ""

        lines = [
            "Human correction memory for similar tasks:",
            "Use these corrections to avoid repeating previous mistakes."
        ]

        for i, item in enumerate(items, start=1):
            lines.append(f"Correction {i}:")
            if item.get("feedback"):
                lines.append(f"- Human feedback: {item['feedback']}")
            lines.append("- Previous model output:")
            lines.append(json.dumps(item.get("original_output", {}), ensure_ascii=False, indent=2))
            lines.append("- Human corrected output:")
            lines.append(json.dumps(item.get("modified_output", {}), ensure_ascii=False, indent=2))

        return "\\n".join(lines)
