from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "auxiliary_brain" / "delegation" / "delegation_runtime.py"
text = SRC.read_text(encoding="utf-8")

required_snippets = [
    '"feedback_repair_confirmation"',
    'async def _resume_feedback_repair_confirmation',
    '"resume_owner": "auxiliary_brain"',
    '"resume_kind": "registered_capability_feedback_repair"',
    '"current_stage": "resuming_feedback_repair"',
    '"_original_user_material"',
    'terminal_graph_outputs_after_feedback_repair',
]
missing = [s for s in required_snippets if s not in text]
if missing:
    raise SystemExit(f"Missing feedback repair resume support snippets: {missing}")

# This module must not route confirmed feedback repair through the primary
# runtime checkpoint resume path. The branch must appear before the generic
# durable primary-runtime resume block.
repair_branch = text.index('if str(pending.get("kind") or "") == "feedback_repair_confirmation"')
generic_resume = text.index('task_mind_graph = self._build_task_mind_graph(task_graph, selected)', repair_branch)
if repair_branch > generic_resume:
    raise SystemExit("feedback repair branch is not before generic primary-runtime resume")

forbidden = ["smtp", "gmail", "weather", "forecast"]
method_start = text.index('async def _resume_feedback_repair_confirmation')
method_end = text.index('def _submitted_confirmation', method_start)
method = text[method_start:method_end].casefold()
found = [w for w in forbidden if w in method]
if found:
    raise SystemExit(f"Feedback repair resume method contains business/protocol terms: {found}")

print("feedback repair resume checkpoint verification passed")
