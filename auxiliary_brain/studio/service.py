from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
import re

from auxiliary_brain.delegation import AgentDelegationRuntime
from auxiliary_brain.runtime import new_id
from auxiliary_brain.storage import JsonStore
from auxiliary_brain.studio.command_router import StudioCommandRouter


class AgentStudioService:
    """Studio service for managing participants, task graphs, and delegation state."""

    def __init__(self, store: JsonStore | None = None, router: StudioCommandRouter | None = None) -> None:
        self.store = store or JsonStore()
        self.router = router or StudioCommandRouter()
        self.delegation_runtime = AgentDelegationRuntime(store=self.store)
        self.store.ensure_workspace()
        self.community_id = self._ensure_community()

    async def handle_message(self, message: str, provided_inputs: dict[str, Any] | None = None) -> dict[str, Any]:
        routed = self.router.route(message)
        if routed.action == "create_participant":
            return self.create_participant(message, routed.name)
        if routed.action == "create_task":
            return self.create_task_graph(message, routed.name)
        if routed.action == "execute_task":
            return await self.execute_task(routed.name)
        return {
            "action": "unrouted_message",
            "origin": "auxiliary_brain",
            "status": "needs_instruction",
            "message": "No configured studio command matched this input.",
        }

    def snapshot(self) -> dict[str, Any]:
        return {
            "origin": "auxiliary_brain",
            "community_id": self.community_id,
            "participants": self.store.list_json("generated/agents"),
            "task_graphs": self.store.list_json("generated/tasks"),
            "task_runs": self.store.list_json("generated/results"),
            "deliveries": self.store.list_json("deliveries"),
            "traces": self.store.list_json("traces/agent_delegation"),
        }

    def create_participant(self, instruction: str, name: str | None = None) -> dict[str, Any]:
        participant_id = new_id("participant")
        participant_name = name or participant_id
        execution_objective = self._derive_execution_objective(instruction, participant_name)
        payload = {
            "participant_id": participant_id,
            "name": participant_name,
            "instruction": execution_objective,
            "execution_objective": execution_objective,
            "definition_instruction": instruction,
            "origin": "auxiliary_brain",
            "status": "created",
            "created_at": self._now(),
            "execution_policy": "delegate_to_ai_core",
        }
        path = self.store.write_json(f"generated/agents/{participant_id}.json", payload)
        self._update_community()
        return {
            "action": "create_participant",
            "origin": "auxiliary_brain",
            "status": "completed",
            "participant_id": participant_id,
            "path": str(path),
        }

    def create_task_graph(self, instruction: str, name: str | None = None) -> dict[str, Any]:
        graph_id = new_id("graph")
        task_name = name or graph_id
        participants = self.store.list_json("generated/agents")
        selected_ids = [p.get("participant_id") for p in self._select_participants_for_instruction(instruction, participants)]
        payload = {
            "graph_id": graph_id,
            "task_name": task_name,
            "community_id": self.community_id,
            "instruction": instruction,
            "origin": "auxiliary_brain",
            "status": "created",
            "created_at": self._now(),
            "execution_policy": "delegated_participant_execution_via_ai_core",
            "selected_participant_ids": selected_ids,
            "tasks": [
                {
                    "task_id": f"{graph_id}_delegate_{index + 1}",
                    "participant_id": participant_id,
                    "execution_owner": "ai_core",
                    "status": "pending",
                }
                for index, participant_id in enumerate(selected_ids)
            ],
            "final_synthesis_owner": "ai_core",
        }
        path = self.store.write_json(f"generated/tasks/{task_name}.json", payload)
        self._update_community()
        return {
            "action": "create_task_graph",
            "origin": "auxiliary_brain",
            "status": "completed",
            "graph_id": graph_id,
            "task_name": task_name,
            "path": str(path),
        }

    async def execute_task(self, task_name: str | None) -> dict[str, Any]:
        if not task_name:
            return {
                "action": "execute_task_graph",
                "origin": "auxiliary_brain",
                "status": "blocked",
                "message": "A task name is required.",
            }
        task_graph = self.store.read_json(f"generated/tasks/{task_name}.json")
        if not task_graph:
            return {
                "action": "execute_task_graph",
                "origin": "auxiliary_brain",
                "status": "not_found",
                "task_name": task_name,
            }
        all_participants = self.store.list_json("generated/agents")
        selected_ids = set(task_graph.get("selected_participant_ids") or [])
        participants = [p for p in all_participants if p.get("participant_id") in selected_ids] or all_participants
        result = await self.delegation_runtime.execute_task(task_graph, participants)
        status = result.get("status", "completed")
        response = {
            "action": "execute_task_graph",
            "origin": "auxiliary_brain",
            "status": status,
            "task_name": task_name,
            "run_id": result.get("run_id"),
            "final_answer": (result.get("synthesis") or {}).get("final_answer"),
            "delivery": result.get("delivery"),
        }
        if status in {"requires_key", "requires_input", "paused"}:
            response["missing_inputs"] = result.get("missing_inputs", [])
            response["pending_action"] = result.get("pending_action")
            response["message"] = "Delegated primary-runtime execution is waiting for required input."
        return response

    async def resume_run(self, run_id: str) -> dict[str, Any]:
        run_id = (run_id or "").strip()
        if not run_id:
            return {
                "action": "resume_task_graph",
                "origin": "auxiliary_brain",
                "status": "blocked",
                "message": "A run id is required.",
            }
        run_payload = self.store.read_json(f"generated/results/{run_id}.json")
        if not run_payload:
            return {
                "action": "resume_task_graph",
                "origin": "auxiliary_brain",
                "status": "not_found",
                "run_id": run_id,
            }
        task_name = str(run_payload.get("task_name") or "").strip()
        if not task_name:
            return {
                "action": "resume_task_graph",
                "origin": "auxiliary_brain",
                "status": "blocked",
                "run_id": run_id,
                "message": "The paused run does not reference a task name.",
            }
        task_graph = self.store.read_json(f"generated/tasks/{task_name}.json")
        if not task_graph:
            return {
                "action": "resume_task_graph",
                "origin": "auxiliary_brain",
                "status": "not_found",
                "run_id": run_id,
                "task_name": task_name,
            }
        all_participants = self.store.list_json("generated/agents")
        selected_ids = set(task_graph.get("selected_participant_ids") or [])
        participants = [p for p in all_participants if p.get("participant_id") in selected_ids] or all_participants
        result = await self.delegation_runtime.resume_task(run_payload, task_graph, participants)
        status = result.get("status", "completed")
        response = {
            "action": "resume_task_graph",
            "origin": "auxiliary_brain",
            "status": status,
            "task_name": task_name,
            "run_id": result.get("run_id"),
            "resumed_from_run_id": run_id,
            "final_answer": (result.get("synthesis") or {}).get("final_answer"),
            "delivery": result.get("delivery"),
        }
        if status in {"requires_key", "requires_input", "paused"}:
            response["missing_inputs"] = result.get("missing_inputs", [])
            response["pending_action"] = result.get("pending_action")
            response["message"] = "Delegated primary-runtime execution is waiting for required input."
        return response


    def _derive_execution_objective(self, instruction: str, participant_name: str | None = None) -> str:
        """Extract the participant's reusable work objective from a creation command.

        The studio stores both the original definition command and the runtime
        objective. Delegated execution must use the objective, not the creation
        sentence, otherwise the primary runtime may plan to create an agent again.
        This parser is generic command-shape handling; it does not encode any
        business domain.
        """
        text = (instruction or "").strip()
        if not text:
            return ""

        # Common shape: "create ... named <name> to <objective>".
        match = re.search(
            r"\bnamed\s+.+?\s+to\s+(.+?)(?:[。.!?]\s*)?$",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if match:
            return match.group(1).strip(" .。")

        # Common shape without a name: "create ... to <objective>".
        match = re.search(
            r"\bcreate\b.+?\bto\s+(.+?)(?:[。.!?]\s*)?$",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if match:
            return match.group(1).strip(" .。")

        # If the task statement used a relative clause, keep the clause body.
        match = re.search(
            r"\bthat\s+(.+?)(?:[。.!?]\s*)?$",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if match:
            return match.group(1).strip(" .。")

        return text

    def _ensure_community(self) -> str:
        existing = self.store.list_json("generated/communities")
        if existing:
            return str(existing[0].get("community_id") or existing[0].get("id") or "community")
        community_id = new_id("community")
        payload = {
            "community_id": community_id,
            "origin": "auxiliary_brain",
            "status": "created",
            "created_at": self._now(),
            "participants_path": "runtime/generated/agents",
            "tasks_path": "runtime/generated/tasks",
        }
        self.store.write_json(f"generated/communities/{community_id}.json", payload)
        return community_id

    def _update_community(self) -> None:
        payload = {
            "community_id": self.community_id,
            "origin": "auxiliary_brain",
            "status": "active",
            "updated_at": self._now(),
            "participants_count": len(self.store.list_json("generated/agents")),
            "tasks_count": len(self.store.list_json("generated/tasks")),
        }
        self.store.write_json(f"generated/communities/{self.community_id}.json", payload)
        trace = {
            "trace_id": new_id("trace"),
            "origin": "auxiliary_brain",
            "community_id": self.community_id,
            "updated_at": self._now(),
            "paths": {
                "participants": "runtime/generated/agents",
                "tasks": "runtime/generated/tasks",
                "communities": "runtime/generated/communities",
            },
        }
        self.store.write_json(f"traces/agent_delegation/{trace['trace_id']}.json", trace)

    def _select_participants_for_instruction(self, instruction: str, participants: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not participants:
            return []
        text = instruction.lower()
        selected = []
        for participant in participants:
            name = str(participant.get("name") or "").lower()
            pid = str(participant.get("participant_id") or "").lower()
            if name and name in text:
                selected.append(participant)
            elif pid and pid in text:
                selected.append(participant)
        return selected or participants

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()
