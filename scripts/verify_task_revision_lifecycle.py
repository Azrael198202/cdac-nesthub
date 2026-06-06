from __future__ import annotations

import json
import shutil
import tempfile
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from auxiliary_brain.studio.service import AgentStudioService
from auxiliary_brain.storage import JsonStore


def main() -> None:
    root = Path(tempfile.mkdtemp(prefix="task_revision_lifecycle_"))
    try:
        service = AgentStudioService(store=JsonStore(root))
        instruction_v1 = """
Create a task named RevisionTask.

Step 1:
Call Example Agent.

Parameters for Example Agent:
- value: one
"""
        created = service.create_task_graph(instruction_v1, "RevisionTask")
        assert created["status"] == "completed", created
        first = json.loads((root / "generated" / "tasks" / "RevisionTask.json").read_text(encoding="utf-8"))
        assert first["task_revision"] == 1
        assert first["graph_revision"] == 1
        assert first["plan_revision"] == 1
        assert first["active_revision_id"]
        assert first["source_instruction_fingerprint"]
        revision_dir = root / "generated" / "task_revisions" / "RevisionTask"
        assert len(list(revision_dir.glob("*.json"))) == 1

        instruction_v2 = instruction_v1.replace("value: one", "value: two")
        updated = service.update_task_graph_instruction("RevisionTask", instruction_v2)
        assert updated["ok"] is True, updated
        second = json.loads((root / "generated" / "tasks" / "RevisionTask.json").read_text(encoding="utf-8"))
        assert second["task_revision"] == 2
        assert second["graph_revision"] == 2
        assert second["plan_revision"] == 2
        assert second["active_revision_id"] != first["active_revision_id"]
        assert second["previous_revision_id"] == first["active_revision_id"]
        assert len(list(revision_dir.glob("*.json"))) == 2
        print("task_revision_lifecycle: passed")
    finally:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    main()
