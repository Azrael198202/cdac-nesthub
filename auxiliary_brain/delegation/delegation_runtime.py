from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ai_core.agent_delegation import AgentExecutionRequest, PrimaryBrainDelegationClient
from auxiliary_brain.storage import JsonStore
from auxiliary_brain.runtime import new_id


class AgentDelegationRuntime:
    """Coordinates delegation without executing participant work itself."""

    def __init__(self, store: JsonStore | None = None, primary_client: PrimaryBrainDelegationClient | None = None) -> None:
        self.store = store or JsonStore()
        self.primary_client = primary_client or PrimaryBrainDelegationClient()

    async def execute_task(self, task_graph: dict[str, Any], participants: list[dict[str, Any]]) -> dict[str, Any]:
        run_id = new_id("delegation_run")
        task_name = str(task_graph.get("task_name") or task_graph.get("graph_id") or "task")
        task_instruction = str(task_graph.get("instruction") or task_graph.get("objective") or "")
        community_id = str(task_graph.get("community_id") or "default")
        selected = self._select_participants(task_graph, participants)

        run_payload: dict[str, Any] = {
            "run_id": run_id,
            "origin": "auxiliary_brain",
            "status": "running",
            "task_name": task_name,
            "community_id": community_id,
            "started_at": self._now(),
            "delegation_policy": "participant_requests_are_executed_by_ai_core",
            "agent_results": [],
        }
        self.store.write_json(f"generated/results/{run_id}.json", run_payload)

        agent_results = []
        for participant in selected:
            request = AgentExecutionRequest(
                participant_id=str(participant.get("participant_id") or participant.get("id")),
                participant_name=str(participant.get("name") or participant.get("participant_id") or "participant"),
                participant_instruction=str(participant.get("instruction") or participant.get("description") or ""),
                task_name=task_name,
                task_instruction=task_instruction,
                community_id=community_id,
                shared_context={
                    "task_graph_id": task_graph.get("graph_id"),
                    "participant_count": len(selected),
                },
            )
            result = await self.primary_client.execute_agent_request(request)
            result_payload = result.__dict__
            agent_results.append(result)
            run_payload["agent_results"].append(result_payload)
            self.store.write_json(f"generated/results/{run_id}.json", run_payload)
            if result.status in {"requires_key", "requires_input", "paused"}:
                run_payload.update({
                    "status": result.status,
                    "pending_action": result.pending_action,
                    "missing_inputs": result.missing_inputs or [],
                    "completed_at": self._now(),
                })
                self.store.write_json(f"generated/results/{run_id}.json", run_payload)
                return run_payload

        synthesis = await self.primary_client.synthesize_delegated_results(
            task_name=task_name,
            task_instruction=task_instruction,
            agent_results=agent_results,
            shared_context={"community_id": community_id},
        )
        delivery_id = new_id("delivery")
        delivery_payload = {
            "delivery_id": delivery_id,
            "origin": "auxiliary_brain",
            "upstream_origin": "ai_core",
            "task_name": task_name,
            "run_id": run_id,
            "final_answer": synthesis.get("final_answer"),
            "synthesis": synthesis,
            "created_at": self._now(),
        }
        delivery_path = self.store.write_json(f"deliveries/{delivery_id}.json", delivery_payload)

        run_payload.update({
            "status": "completed",
            "completed_at": self._now(),
            "synthesis": synthesis,
            "delivery": str(delivery_path),
        })
        self.store.write_json(f"generated/results/{run_id}.json", run_payload)
        return run_payload

    def _select_participants(self, task_graph: dict[str, Any], participants: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not participants:
            return []
        text = (str(task_graph.get("instruction") or "") + " " + str(task_graph.get("task_name") or "")).lower()
        selected = []
        for participant in participants:
            name = str(participant.get("name") or "").lower()
            pid = str(participant.get("participant_id") or participant.get("id") or "").lower()
            if name and name in text:
                selected.append(participant)
            elif pid and pid in text:
                selected.append(participant)
        return selected or participants

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()
