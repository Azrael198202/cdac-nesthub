from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from auxiliary_brain.runtime import AuxiliaryBrainRuntime
from auxiliary_brain.execution import RuntimeExecutionRuntime
from auxiliary_brain.scheduler import RuntimeTriggerParser
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
        self.execution_runtime = RuntimeExecutionRuntime(self.runtime_root)
        self.trigger_parser = RuntimeTriggerParser()
        self.task_runs_dir = self.runtime_root / "generated" / "task_runs"
        self.runtime_input_dir = self.runtime_root / "generated" / "runtime_inputs"

    def handle_message(self, message: str, provided_inputs: dict[str, Any] | None = None) -> dict[str, Any]:
        action = self.command_config.detect_action(message)
        missing = self._missing_inputs(action, message, provided_inputs or {})
        if missing:
            self._write_interaction_trace(action, message, missing)
            return {
                "origin": self.ORIGIN,
                "action": action,
                "status": "needs_input",
                "original_message": message,
                "missing_inputs": missing,
                "state": self.snapshot(),
            }
        if provided_inputs:
            self._accept_runtime_inputs(provided_inputs)
        if action == "create_participant":
            return self.create_participant(message)
        if action == "create_task_graph":
            return self.create_task_graph(message)
        if action == "start_task_graph":
            return self.update_latest_task_graph("running", message)
        if action == "stop_task_graph":
            return self.update_latest_task_graph("stopped", message)
        return {"origin": self.ORIGIN, "action": action, "status": "view", "state": self.snapshot()}

    def accept_runtime_input(self, input_id: str, value: str) -> dict[str, Any]:
        if not value:
            return {"origin": self.ORIGIN, "action": "runtime_input", "status": "empty", "message": "No value was provided."}
        self._accept_runtime_inputs({input_id: value})
        return {
            "origin": self.ORIGIN,
            "action": "runtime_input",
            "status": "accepted",
            "message": "Runtime input accepted for the active server process.",
            "state": self.snapshot(),
        }

    def create_participant(self, message: str) -> dict[str, Any]:
        extracted = self._extract_terms(message)
        role_label = extracted[0] if extracted else f"role_{uuid4().hex[:8]}"
        capability_labels = extracted[1:4] or self.command_config.action_profile("create_participant").get(
            "default_capabilities",
            ["runtime_generated_capability"],
        )
        tool_refs = self.command_config.action_profile("create_participant").get("default_tools", [])
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
        return {"origin": self.ORIGIN, "action": "create_participant", "status": "completed", "result": result, "state": self.snapshot()}

    def create_task_graph(self, message: str) -> dict[str, Any]:
        agents = self._load_agents()
        if not agents:
            self.create_participant("bootstrap")
            agents = self._load_agents()
        graph_id = f"graph_{uuid4().hex[:8]}"
        profile = self.command_config.action_profile("create_task_graph")
        default_timezone = profile.get("default_timezone", "Asia/Tokyo")
        activation = self.trigger_parser.parse(message, default_timezone=default_timezone)
        selected_agents = self._select_agents_for_message(agents, message) or agents[:1]
        tasks: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []
        material_refs: list[str] = []
        for index, agent in enumerate(selected_agents, start=1):
            task_id = f"{graph_id}_step_{index}"
            output_ref = f"{graph_id}_material_{index}"
            tasks.append({
                "task_id": task_id,
                "assigned_agent_id": agent.get("agent_id"),
                "objective": message,
                "output_ref": output_ref,
                "activation_ref": activation.get("activation_id"),
                "parameters": {"source": "studio_message", "execution_mode": "collect"},
                "metadata": {"selected_by": "runtime_overlap"},
            })
            material_refs.append(output_ref)
        final_agent = selected_agents[0] if selected_agents else agents[0]
        final_id = f"{graph_id}_final"
        tasks.append({
            "task_id": final_id,
            "assigned_agent_id": final_agent.get("agent_id"),
            "objective": message,
            "input_refs": material_refs,
            "output_ref": f"{graph_id}_final_output",
            "parameters": {"source": "studio_message", "execution_mode": "compose"},
        })
        for task in tasks[:-1]:
            edges.append({"from_task_id": task["task_id"], "to_task_id": final_id, "condition": "completed"})
        specification = {
            "community_id": self._active_or_new_community_id(),
            "agents": agents,
            "activations": [activation],
            "tasks": tasks,
            "edges": edges,
            "metadata": {"source": "agent_studio", "message_excerpt": message[:160], "graph_id": graph_id},
        }
        result = self.auxiliary_runtime.create_from_specification(specification)
        graph_path = result.get("paths", {}).get("community")
        registration = self.execution_runtime.register_graph(graph_payload=specification, graph_path=graph_path) if graph_path else {}
        self._write_task_run(graph_id, registration.get("schedule", {}).get("status", "created"), {"created": result, "registration": registration})
        return {"origin": self.ORIGIN, "action": "create_task_graph", "status": "completed", "graph_id": graph_id, "result": result, "registration": registration, "state": self.snapshot()}

    def update_latest_task_graph(self, status: str, message: str = "") -> dict[str, Any]:
        run_files = sorted(self.task_runs_dir.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
        if not run_files:
            created = self.create_task_graph(message or "manual graph")
            graph_id = created.get("graph_id", "graph")
        else:
            payload = json.loads(run_files[0].read_text(encoding="utf-8"))
            graph_id = payload.get("graph_id") or run_files[0].stem
        result_payload: dict[str, Any] = {"message_excerpt": message[:160]}
        final_status = status
        if status == "running":
            schedule_files = sorted((self.runtime_root / "generated" / "schedules").glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
            for schedule_file in schedule_files:
                schedule_payload = json.loads(schedule_file.read_text(encoding="utf-8"))
                if str(schedule_payload.get("graph_id")) == str(graph_id):
                    scheduled_at = (schedule_payload.get("activation") or {}).get("metadata", {}).get("scheduled_at")
                    if not scheduled_at:
                        self.execution_runtime.scheduler.mark(schedule_payload.get("schedule_id"), "running", {"reason": "manual_start"})
                    break
            due_results = self.execution_runtime.run_due()
            if due_results:
                result_payload["executions"] = due_results
                final_status = status
            else:
                result_payload["scheduler"] = "registered_waiting_for_activation"
                final_status = "scheduled"
        elif status == "stopped":
            result_payload["scheduler"] = "stop_requested"
        self._write_task_run(str(graph_id), final_status, result_payload)
        return {"origin": self.ORIGIN, "action": "update_task_graph", "graph_id": graph_id, "status": final_status, "payload": result_payload, "state": self.snapshot()}

    def snapshot(self) -> dict[str, Any]:
        return {
            "origin": self.ORIGIN,
            "agents": self._load_agents(),
            "communities": self._load_json_dir(self.runtime_root / "generated" / "communities"),
            "task_graphs": self._load_json_dir(self.runtime_root / "generated" / "tasks"),
            "task_runs": self._load_json_dir(self.task_runs_dir),
            "runtime_inputs": self._load_json_dir(self.runtime_input_dir),
            "schedules": self._load_json_dir(self.runtime_root / "generated" / "schedules"),
            "instances": self._load_json_dir(self.runtime_root / "instances"),
            "tool_outputs": self._load_json_dir(self.runtime_root / "generated" / "tool_outputs"),
            "deliveries": self._load_json_dir(self.runtime_root / "deliveries"),
            "traces": self._load_json_dir(self.runtime_root / "traces" / "runtime_layers"),
        }


    def run_due_tasks(self) -> dict[str, Any]:
        results = self.execution_runtime.run_due()
        return {"origin": self.ORIGIN, "action": "run_due_tasks", "status": "completed", "results": results, "state": self.snapshot()}

    def _select_agents_for_message(self, agents: list[dict[str, Any]], message: str) -> list[dict[str, Any]]:
        message_terms = {term.casefold() for term in self._extract_terms(message)}
        ranked: list[tuple[int, int, dict[str, Any]]] = []
        for index, agent in enumerate(agents):
            labels = [agent.get("role_label", ""), *agent.get("capability_labels", []), *agent.get("tool_refs", [])]
            agent_terms = {term.casefold() for label in labels for term in self._extract_terms(str(label))}
            score = len(message_terms & agent_terms)
            if score > 0:
                ranked.append((score, -index, agent))
        ranked.sort(reverse=True, key=lambda item: (item[0], item[1]))
        return [agent for _, __, agent in ranked] or agents[:2]

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

    def _missing_inputs(self, action: str, message: str, provided_inputs: dict[str, Any]) -> list[dict[str, Any]]:
        profile = self.command_config.action_profile(action)
        required = profile.get("required_runtime_inputs", [])
        missing: list[dict[str, Any]] = []
        for item in required:
            input_id = str(item.get("input_id", "")).strip()
            if not input_id:
                continue
            if provided_inputs.get(input_id):
                continue
            if self._runtime_input_available(item):
                continue
            token_patterns = item.get("message_patterns", [])
            if token_patterns and not any(re.search(str(pattern), message, re.IGNORECASE) for pattern in token_patterns):
                continue
            missing.append({
                "input_id": input_id,
                "label": item.get("label", input_id),
                "placeholder": item.get("placeholder", ""),
                "secret": bool(item.get("secret", False)),
                "reason": item.get("reason", "required_by_runtime_profile"),
            })
        return missing

    def _runtime_input_available(self, item: dict[str, Any]) -> bool:
        for env_key in item.get("env_keys", []):
            if os.environ.get(str(env_key)):
                return True
        input_id = str(item.get("input_id", ""))
        if input_id:
            marker = self.runtime_input_dir / f"{input_id}.json"
            if marker.exists():
                try:
                    payload = json.loads(marker.read_text(encoding="utf-8"))
                    return bool(payload.get("configured"))
                except json.JSONDecodeError:
                    return False
        return False

    def _accept_runtime_inputs(self, values: dict[str, Any]) -> None:
        config = self.command_config.load()
        known_inputs = {str(item.get("input_id")): item for item in config.get("runtime_inputs", [])}
        for action in config.get("actions", []):
            for item in action.get("required_runtime_inputs", []):
                if item.get("input_id"):
                    known_inputs[str(item.get("input_id"))] = item
        self.runtime_input_dir.mkdir(parents=True, exist_ok=True)
        for input_id, value in values.items():
            if value is None or value == "":
                continue
            profile = known_inputs.get(str(input_id), {"input_id": input_id})
            for env_key in profile.get("env_keys", []):
                os.environ[str(env_key)] = str(value)
            marker = {
                "input_id": str(input_id),
                "origin": self.ORIGIN,
                "configured": True,
                "secret": bool(profile.get("secret", True)),
                "accepted_at": datetime.now(timezone.utc).isoformat(),
            }
            (self.runtime_input_dir / f"{input_id}.json").write_text(
                json.dumps(marker, ensure_ascii=False, indent=2, sort_keys=True),
                encoding="utf-8",
            )

    def _write_interaction_trace(self, action: str, message: str, missing: list[dict[str, Any]]) -> None:
        trace_dir = self.runtime_root / "traces" / "runtime_layers"
        trace_dir.mkdir(parents=True, exist_ok=True)
        trace_id = f"interaction_{uuid4().hex[:8]}"
        record = {
            "trace_id": trace_id,
            "origin": self.ORIGIN,
            "event": "missing_runtime_input",
            "action": action,
            "message_excerpt": message[:160],
            "missing_inputs": missing,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        (trace_dir / f"{trace_id}.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )

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
