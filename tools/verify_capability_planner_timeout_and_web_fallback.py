from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    conversation = (ROOT / "ai_core/interaction/conversation_core_runtime.py").read_text(encoding="utf-8")
    assert '"planner_failed", "planner_low_confidence", "evidence_missing"' in conversation, "planner_failed must trigger web evidence fallback"
    assert "optimized_evidence" in conversation, "web fallback must store optimized evidence"

    planner_path = ROOT / "runtime_assets/seeds/capability_planners/default_capability_planner.py"
    planner = planner_path.read_text(encoding="utf-8")
    assert 'AI_CORE_CAPABILITY_PLANNER_TIMEOUT", "600"' in planner, "default local planner timeout must be extended"
    assert "return None" in planner, "timeout<=0 should allow operator-controlled indefinite wait for planner call"
    assert "optimized_evidence" in planner and "evidence_pack" in planner, "planner must read optimized evidence pack"
    assert "compact=True" in planner, "planner must retry with compact prompt"
    ast.parse(planner)
    print("capability planner timeout and web fallback verified")


if __name__ == "__main__":
    main()
