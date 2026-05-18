from __future__ import annotations

from typing import Any


class StableSynthesizer:
    """Combines verified task results without exposing internal traces."""

    BLOCKED_MARKERS = ("Matched Parameter:", "Descriptors:", "Values:", "raw_trace", "debug")

    def synthesize(self, task_results: list[dict[str, Any]], verification: dict[str, Any]) -> dict[str, Any]:
        lines: list[str] = []
        for result in task_results:
            task_id = str(result.get("task_id") or "task")
            material = result.get("material") if isinstance(result.get("material"), dict) else {}
            snippets = self._snippets(material)
            if snippets:
                lines.append(f"{task_id}: {snippets[0]}")
        answer = "\n".join(lines).strip() or "No verified user-facing material was available."
        answer = self._sanitize(answer)
        return {
            "answer": answer,
            "confidence": verification.get("confidence", 0),
            "coverage_ratio": verification.get("coverage_ratio", 0),
            "source_count": verification.get("source_count", 0),
            "verification_passed": verification.get("passed", False),
        }

    def _snippets(self, material: dict[str, Any]) -> list[str]:
        snippets: list[str] = []
        for source in material.get("sources", []):
            if not isinstance(source, dict):
                continue
            for key in ("summary", "text", "excerpt", "content"):
                value = source.get(key)
                if isinstance(value, str) and value.strip():
                    snippets.append(" ".join(value.split())[:240])
                    break
        return snippets

    def _sanitize(self, answer: str) -> str:
        clean = answer
        for marker in self.BLOCKED_MARKERS:
            clean = clean.replace(marker, "")
        return clean.strip()
