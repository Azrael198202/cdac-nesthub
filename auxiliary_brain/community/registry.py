from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import RuntimeCommunityDefinition


class RuntimeCommunityRegistry:
    """Persistence adapter for runtime-generated community artifacts."""

    def __init__(self, runtime_root: str | Path = "runtime") -> None:
        self.runtime_root = Path(runtime_root)
        self.generated_root = self.runtime_root / "generated"
        self.agents_dir = self.generated_root / "agents"
        self.communities_dir = self.generated_root / "communities"
        self.tasks_dir = self.generated_root / "tasks"

    def ensure_layout(self) -> None:
        for path in (self.agents_dir, self.communities_dir, self.tasks_dir):
            path.mkdir(parents=True, exist_ok=True)
            keep = path / ".gitkeep"
            if not keep.exists():
                keep.write_text("", encoding="utf-8")

    def save_community(self, definition: RuntimeCommunityDefinition) -> dict[str, str]:
        self.ensure_layout()
        payload = definition.to_dict()
        community_path = self.communities_dir / f"{definition.community_id}.json"
        task_path = self.tasks_dir / f"{definition.community_id}.json"
        community_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        task_path.write_text(
            json.dumps(
                {
                    "community_id": definition.community_id,
                    "activations": payload["activations"],
                    "tasks": payload["tasks"],
                    "edges": payload["edges"],
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        for agent in definition.agents:
            agent_path = self.agents_dir / f"{agent.agent_id}.json"
            agent_path.write_text(
                json.dumps(agent.to_dict(), ensure_ascii=False, indent=2, sort_keys=True),
                encoding="utf-8",
            )
        return {
            "community": str(community_path),
            "tasks": str(task_path),
            "agents": str(self.agents_dir),
        }

    def load_community_payload(self, community_id: str) -> dict[str, Any]:
        self.ensure_layout()
        path = self.communities_dir / f"{community_id}.json"
        if not path.exists():
            raise FileNotFoundError(f"community artifact not found: {community_id}")
        return json.loads(path.read_text(encoding="utf-8"))
