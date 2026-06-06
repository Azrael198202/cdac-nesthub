from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
files = [
    ROOT / "ai_core" / "runtime" / "self_repair" / "execution_failure_repair.py",
    ROOT / "ai_core" / "runtime" / "self_repair" / "repair_orchestrator.py",
    ROOT / "auxiliary_brain" / "delegation" / "delegation_runtime.py",
]

for path in files:
    text = path.read_text(encoding="utf-8")
    if re.search(r"[\u4e00-\u9fff]", text):
        raise SystemExit(f"Non-English user-facing repair text remains in {path}")

runtime = (ROOT / "auxiliary_brain" / "delegation" / "delegation_runtime.py").read_text(encoding="utf-8")
required = [
    '"original_user_material": source_material',
    '"detected_structural_values": detected_structural_values',
    'checkpoint_material = str(checkpoint.get("original_user_material")',
    'checkpoint_structural = checkpoint.get("detected_structural_values")',
    'def _task_source_material',
    'def _extract_structural_values_from_material',
]
missing = [item for item in required if item not in runtime]
if missing:
    raise SystemExit(f"Missing repair checkpoint structural binding support: {missing}")

forbidden = ["smtp", "gmail", "weather", "forecast"]
method_start = runtime.index('async def _resume_feedback_repair_confirmation')
method_end = runtime.index('def _submitted_confirmation', method_start)
method = runtime[method_start:method_end].casefold()
found = [w for w in forbidden if w in method]
if found:
    raise SystemExit(f"Feedback repair resume method contains business/protocol terms: {found}")

print("feedback repair confirmation checkpoint and English text verification passed")
