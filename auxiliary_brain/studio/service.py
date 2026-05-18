from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from auxiliary_brain.runtime import AuxiliaryBrainRuntime
from auxiliary_brain.studio.config_loader import StudioCommandConfig


class AgentStudioService:
    """UI-facing coordinator for the parallel auxiliary runtime.

    This service remains domain-neutral. It converts user text into generic
    runtime-generated participant/task specifications, persists them under the
    runtime tree, and records origin-labelled traces.
    """

    ORIGIN = "auxiliary_brain"

    def __init__(
        self,
        runtime_root: str | Path = "runtime",
        command_config_path: str | Path = "configs/agent_studio_commands.json",
    ) -> None:
        self.runtime_root = Path(runtime_root)
        self.command_config = StudioCommandConfig(command_config_path)
        self.auxiliary_runtime = AuxiliaryBrainRuntime(self.runtime_root)
        self.task_runs_dir = self.runtime_root / "generated" / "task_runs"

    def handle_message(self, message: str) -> dict[str, Any]:
        action = self.command_config.detect_action(message)
        if action == "create_participant":
            return self.create_participant(message)
        if action == "create_task_graph":
            return self.create_task_graph(message)
        if action == "start_task_graph":
            return self.update_latest_task_graph("running", message)
        if action == "stop_task_graph":
            return self.update_latest_task_graph("stopped", message)
        return {"origin": self.ORIGIN, "action": action, "state": self.snapshot()}

    def create_participant(self, message: str) -> dict[str, Any]:
        extracted = self._extract_terms(message)
        role_label = extracted[0] if extracted else f"role_{uuid4().hex[:8]}"
        capability_labels = extracted[1:4] or self.command_config.action_profile("create_participant").get(
            "default_capabilities",
            ["runtime_generated_capability"],
        )
        tool_refs = [f"tool::{value}" for value in extracted[4:7]]
        specification = {
            "community_id": self._active_or_new_community_id(),
            "agents": [
                {
                    "agent_id": f"participant_{uuid4().hex[:8]}",
                    "role_label": role_label,
                    "capability_labels": capability_labels,
                    "tool_refs": tool_refs,
                    "metadata": {"created_from": "studio_message"},
                }
            ],
            "tasks": [],
            "edges": [],
            "metadata": {"source": "agent_studio", "message_excerpt": message[:160]},
        }
        result = self.auxiliary_runtime.create_from_specification(specification)
        return {"origin": self.ORIGIN, "action": "create_participant", "result": result, "state": self.snapshot()}

    def create_task_graph(self, message: str) -> dict[str, Any]:
        agents = self._load_agents()
        if not agents:
            self.create_participant("bootstrap")
            agents = self._load_agents()
        agent_ids = [item.get("agent_id") for item in agents if item.get("agent_id")]
        primary = agent_ids[0] if agent_ids else "participant_1"
        secondary = agent_ids[1] if len(agent_ids) > 1 else primary
        graph_id = f"graph_{uuid4().hex[:8]}"
        specification = {
            "community_id": self._active_or_new_community_id(),
            "agents": agents,
            "activations": [
                {
                    "activation_id": f"activation_{uuid4().hex[:8]}",
                    "mode": self.command_config.action_profile("create_task_graph").get("default_activation_mode", "manual"),
                    "expression": "manual",
                }
            ],
            "tasks": [
                {
                    "task_id": f"{graph_id}_step_1",
                    "assigned_agent_id": primary,
                    "objective": message,
                    "output_ref": f"{graph_id}_material",
                    "parameters": {"source": "studio_message"},
                },
                {
                    "task_id": f"{graph_id}_step_2",
                    "assigned_agent_id": secondary,
                    "objective": "compose output from prior material",
                    "input_refs": [f"{graph_id}_material"],
                    "output_ref": f"{graph_id}_final",
                    "parameters": {"source": "studio_message"},
                },
            ],
            "edges": [
                {"from_task_id": f"{graph_id}_step_1", "to_task_id": f"{graph_id}_step_2", "condition": "completed"}
            ],
            "metadata": {"source": "agent_studio", "message_excerpt": message[:160], "graph_id": graph_id},
        }
        result = self.auxiliary_runtime.create_from_specification(specification)
        self._write_task_run(graph_id, "created", result)
        return {"origin": self.ORIGIN, "action": "create_task_graph", "graph_id": graph_id, "result": result, "state": self.snapshot()}

    def update_latest_task_graph(self, status: str, message: str = "") -> dict[str, Any]:
        run_files = sorted(self.task_runs_dir.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
        if not run_files:
            created = self.create_task_graph(message or "manual graph")
            graph_id = created.get("graph_id", "graph")
        else:
            payload = json.loads(run_files[0].read_text(encoding="utf-8"))
            graph_id = payload.get("graph_id") or run_files[0].stem
        self._write_task_run(str(graph_id), status, {"message_excerpt": message[:160]})
        return {"origin": self.ORIGIN, "action": "update_task_graph", "graph_id": graph_id, "status": status, "state": self.snapshot()}

    def snapshot(self) -> dict[str, Any]:
        return {
            "origin": self.ORIGIN,
            "agents": self._load_agents(),
            "communities": self._load_json_dir(self.runtime_root / "generated" / "communities"),
            "task_graphs": self._load_json_dir(self.runtime_root / "generated" / "tasks"),
            "task_runs": self._load_json_dir(self.task_runs_dir),
            "traces": self._load_json_dir(self.runtime_root / "traces" / "runtime_layers"),
        }

    def _active_or_new_community_id(self) -> str:
        community_dir = self.runtime_root / "generated" / "communities"
        files = sorted(community_dir.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True) if community_dir.exists() else []
        if files:
            return files[0].stem
        return f"community_{uuid4().hex[:8]}"

    def _extract_terms(self, message: str) -> list[str]:
        candidates = re.findall(r"[A-Za-z0-9_\-]{3,}|[\u3040-\u30ff\u3400-\u9fff]{2,}", message)
        config_terms = []
        for item in self.command_config.load().get("actions", []):
            config_terms.extend(str(value).casefold() for value in item.get("patterns", []))
        result: list[str] = []
        for candidate in candidates:
            value = candidate.strip("-_ ")
            if not value:
                continue
            if value.casefold() in config_terms:
                continue
            if value not in result:
                result.append(value[:64])
        return result[:12]

    def _load_agents(self) -> list[dict[str, Any]]:
        return self._load_json_dir(self.runtime_root / "generated" / "agents")

    def _load_json_dir(self, path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        payloads: list[dict[str, Any]] = []
        for item in sorted(path.glob("*.json"), key=lambda value: value.stat().st_mtime, reverse=True):
            try:
                payload = json.loads(item.read_text(encoding="utf-8"))
                payload["artifact_path"] = str(item)
                payloads.append(payload)
            except json.JSONDecodeError:
                continue
        return payloads

    def _write_task_run(self, graph_id: str, status: str, payload: dict[str, Any]) -> None:
        self.task_runs_dir.mkdir(parents=True, exist_ok=True)
        record = {
            "graph_id": graph_id,
            "status": status,
            "origin": self.ORIGIN,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "payload": payload,
        }
        (self.task_runs_dir / f"{graph_id}.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
