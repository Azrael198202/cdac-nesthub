from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class PromptProfileCompiler:
    """Locks a prompt profile at task creation time.

    Runtime code receives only the selected profile id and profile path. It must
    not infer, rewrite, or guess prompt text during execution.
    """

    profile_dir: Path = Path("runtime") / "prompt_profiles"
    default_profile: str = "capability_execution"

    def compile_for_step(self, step: dict[str, Any]) -> dict[str, Any]:
        profile = self._declared_profile(step) or self.default_profile
        path = self.profile_dir / f"{profile}.prompt"
        return {
            "prompt_profile": profile,
            "profile_path": str(path),
            "locked_at": "task_compile",
            "runtime_prompt_guessing": False,
            "exists": path.exists(),
        }

    def _declared_profile(self, step: dict[str, Any]) -> str | None:
        candidates = [
            step.get("prompt_profile"),
            step.get("profile"),
            (step.get("execution_contract") or {}).get("prompt_profile") if isinstance(step.get("execution_contract"), dict) else None,
            (step.get("source_contract") or {}).get("prompt_profile") if isinstance(step.get("source_contract"), dict) else None,
        ]
        for value in candidates:
            text = str(value or "").strip()
            if text:
                return text
        step_type = str(step.get("step_type") or step.get("task_type") or "").strip().lower()
        if step_type in {"source", "retrieval", "source_retrieval"}:
            return "source_retrieval"
        if step_type in {"verification", "validate", "result_verification"}:
            return "verification"
        if step_type in {"presentation", "final", "final_synthesis"}:
            return "presentation"
        if step_type in {"planning", "workflow", "json_planning"}:
            return "json_planning"
        return None
