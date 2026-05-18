from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ai_core.agent_delegation import AgentExecutionRequest, PrimaryBrainDelegationClient
from auxiliary_brain.storage import JsonStore
from auxiliary_brain.runtime import new_id


class AgentDelegationRuntime:
    """Coordinates delegation without executing participant work itself.

    This runtime owns coordination state only. It records progress so the Studio
    can show where a long-running delegated execution is currently working.
    Actual participant work and final synthesis are delegated to the primary
    runtime.
    """

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
            "current_stage": "preparing_delegation",
            "delegation_policy": "participant_requests_are_executed_by_ai_core",
            "progress_events": [],
            "agent_results": [],
        }
        self._record_progress(run_payload, "prepare", "Preparing delegation run", "running")

        agent_results = []
        for index, participant in enumerate(selected):
            participant_name = str(participant.get("name") or participant.get("participant_id") or "participant")
            self._record_progress(
                run_payload,
                f"participant_{index + 1}_prepare",
                f"Preparing participant: {participant_name}",
                "running",
            )
            request = AgentExecutionRequest(
                participant_id=str(participant.get("participant_id") or participant.get("id")),
                participant_name=participant_name,
                participant_instruction=str(participant.get("instruction") or participant.get("description") or ""),
                task_name=task_name,
                task_instruction=task_instruction,
                community_id=community_id,
                shared_context={
                    "task_graph_id": task_graph.get("graph_id"),
                    "participant_count": len(selected),
                },
            )
            self._record_progress(
                run_payload,
                f"participant_{index + 1}_primary_runtime",
                f"Primary runtime executing participant: {participant_name}",
                "running",
            )
            result = await self._execute_agent_request_with_progress(
                request,
                self._build_primary_runtime_progress_bridge(
                    run_payload,
                    participant_index=index + 1,
                    participant_name=participant_name,
                ),
            )
            result_payload = result.__dict__
            agent_results.append(result)
            run_payload["agent_results"].append(result_payload)
            self._record_progress(
                run_payload,
                f"participant_{index + 1}_complete",
                f"Participant finished: {participant_name}",
                "completed" if result.status == "completed" else result.status,
            )
            if result.status in {"requires_key", "requires_input", "paused"}:
                run_payload.update({
                    "status": result.status,
                    "current_stage": "waiting_for_required_input",
                    "pending_action": result.pending_action,
                    "missing_inputs": result.missing_inputs or [],
                    "completed_at": self._now(),
                })
                self._record_progress(run_payload, "waiting_input", "Waiting for required input", "waiting")
                return run_payload

        self._record_progress(run_payload, "final_synthesis", "Primary runtime synthesizing delegated results", "running")
        synthesis = await self.primary_client.synthesize_delegated_results(
            task_name=task_name,
            task_instruction=task_instruction,
            agent_results=agent_results,
            shared_context={"community_id": community_id},
        )
        self._record_progress(run_payload, "final_synthesis_complete", "Final synthesis completed", "completed")
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
            "current_stage": "completed",
            "completed_at": self._now(),
            "synthesis": synthesis,
            "delivery": str(delivery_path),
        })
        self.store.write_json(f"generated/results/{run_id}.json", run_payload)
        return run_payload


    async def resume_task(self, run_payload: dict[str, Any], task_graph: dict[str, Any], participants: list[dict[str, Any]]) -> dict[str, Any]:
        """Resume the same delegation run from its paused participant checkpoint.

        This method must not create a new run id and must not restart already
        completed participant work. It resumes the participant result that owns
        the saved primary-runtime checkpoint, then continues the remaining
        participants and final synthesis.
        """
        run_id = str(run_payload.get("run_id") or "").strip()
        if not run_id:
            run_payload["status"] = "failed"
            run_payload["message"] = "Run id is required for durable resume."
            return run_payload

        task_name = str(task_graph.get("task_name") or run_payload.get("task_name") or "task")
        task_instruction = str(task_graph.get("instruction") or "")
        community_id = str(task_graph.get("community_id") or run_payload.get("community_id") or "default")
        selected = self._select_participants(task_graph, participants)
        run_payload["status"] = "resuming"
        self._record_progress(run_payload, "durable_resume", "Durable resume requested", "running")

        existing_results = list(run_payload.get("agent_results") or [])
        resumed_index = None
        agent_results = []
        for idx, payload in enumerate(existing_results):
            status = str(payload.get("status") or "")
            if resumed_index is None and status in {"requires_key", "requires_input", "paused"}:
                resumed_index = idx
                self._record_progress(run_payload, f"participant_{idx + 1}_resume", f"Resuming participant from checkpoint: {payload.get('participant_name') or 'participant'}", "running")
                resumed = await self._resume_agent_request_with_progress(
                    payload,
                    self._build_primary_runtime_progress_bridge(
                        run_payload,
                        participant_index=idx + 1,
                        participant_name=str(payload.get("participant_name") or "participant"),
                        resume=True,
                    ),
                )
                resumed_payload = resumed.__dict__
                existing_results[idx] = resumed_payload
                agent_results.append(resumed)
                self._record_progress(run_payload, f"participant_{idx + 1}_resume_complete", f"Participant resumed: {resumed.participant_name}", "completed" if resumed.status == "completed" else resumed.status)
                if resumed.status in {"requires_key", "requires_input", "paused"}:
                    run_payload.update({
                        "status": resumed.status,
                        "current_stage": "waiting_for_required_input",
                        "pending_action": resumed.pending_action,
                        "missing_inputs": resumed.missing_inputs or [],
                    })
                    run_payload["agent_results"] = existing_results
                    self._record_progress(run_payload, "waiting_input", "Waiting for required input", "waiting")
                    self.store.write_json(f"generated/results/{run_id}.json", run_payload)
                    return run_payload
            else:
                # Preserve completed results without re-running them.
                try:
                    from ai_core.agent_delegation import AgentExecutionResult
                    agent_results.append(AgentExecutionResult(**payload))
                except Exception:
                    pass

        if resumed_index is None:
            run_payload["status"] = "failed"
            run_payload["message"] = "No paused participant checkpoint was found for durable resume."
            self.store.write_json(f"generated/results/{run_id}.json", run_payload)
            return run_payload

        # Continue any selected participants that have not produced a result yet.
        completed_ids = {str(r.get("participant_id") or "") for r in existing_results}
        for index, participant in enumerate(selected):
            participant_id = str(participant.get("participant_id") or participant.get("id") or "")
            if participant_id in completed_ids:
                continue
            participant_name = str(participant.get("name") or participant_id or "participant")
            self._record_progress(run_payload, f"participant_{index + 1}_primary_runtime", f"Primary runtime executing participant: {participant_name}", "running")
            request = AgentExecutionRequest(
                participant_id=participant_id,
                participant_name=participant_name,
                participant_instruction=str(participant.get("instruction") or participant.get("description") or ""),
                task_name=task_name,
                task_instruction=task_instruction,
                community_id=community_id,
                shared_context={"task_graph_id": task_graph.get("graph_id"), "participant_count": len(selected)},
            )
            result = await self._execute_agent_request_with_progress(
                request,
                self._build_primary_runtime_progress_bridge(
                    run_payload,
                    participant_index=index + 1,
                    participant_name=participant_name,
                ),
            )
            payload = result.__dict__
            existing_results.append(payload)
            agent_results.append(result)
            self._record_progress(run_payload, f"participant_{index + 1}_complete", f"Participant finished: {participant_name}", "completed" if result.status == "completed" else result.status)
            if result.status in {"requires_key", "requires_input", "paused"}:
                run_payload.update({
                    "status": result.status,
                    "current_stage": "waiting_for_required_input",
                    "pending_action": result.pending_action,
                    "missing_inputs": result.missing_inputs or [],
                })
                run_payload["agent_results"] = existing_results
                self._record_progress(run_payload, "waiting_input", "Waiting for required input", "waiting")
                self.store.write_json(f"generated/results/{run_id}.json", run_payload)
                return run_payload

        run_payload["agent_results"] = existing_results
        self._record_progress(run_payload, "final_synthesis", "Primary runtime synthesizing delegated results", "running")
        synthesis = await self.primary_client.synthesize_delegated_results(
            task_name=task_name,
            task_instruction=task_instruction,
            agent_results=agent_results,
            shared_context={"community_id": community_id},
        )
        self._record_progress(run_payload, "final_synthesis_complete", "Final synthesis completed", "completed")
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
            "current_stage": "completed",
            "completed_at": self._now(),
            "synthesis": synthesis,
            "delivery": str(delivery_path),
        })
        self.store.write_json(f"generated/results/{run_id}.json", run_payload)
        return run_payload

    async def _execute_agent_request_with_progress(self, request, progress_callback):
        try:
            return await self.primary_client.execute_agent_request(
                request,
                progress_callback=progress_callback,
            )
        except TypeError as exc:
            if "progress_callback" not in str(exc):
                raise
            return await self.primary_client.execute_agent_request(request)

    async def _resume_agent_request_with_progress(self, payload, progress_callback):
        try:
            return await self.primary_client.resume_agent_request(
                payload,
                progress_callback=progress_callback,
            )
        except TypeError as exc:
            if "progress_callback" not in str(exc):
                raise
            return await self.primary_client.resume_agent_request(payload)

    def _build_primary_runtime_progress_bridge(
        self,
        run_payload: dict[str, Any],
        *,
        participant_index: int,
        participant_name: str,
        resume: bool = False,
    ):
        """Mirror primary-runtime node telemetry into the delegation run.

        The auxiliary layer still does not execute tools or reason over content.
        It only records primary-runtime node status so Agent Studio can show
        whether the primary runtime is parsing, planning, executing, waiting,
        failed, or completed for each delegated participant.
        """

        def bridge(event: dict[str, Any]) -> None:
            mapped = self._map_primary_runtime_event(
                event,
                participant_index=participant_index,
                participant_name=participant_name,
                resume=resume,
            )
            if not mapped:
                return
            self._record_progress(
                run_payload,
                mapped["stage"],
                mapped["label"],
                mapped["status"],
            )
            run_payload.setdefault("primary_runtime_events", []).append({
                "participant_index": participant_index,
                "participant_name": participant_name,
                "core_run_id": event.get("run_id"),
                "event_type": event.get("type"),
                "node_id": event.get("node_id"),
                "status": mapped["status"],
                "label": mapped["label"],
                "at": self._now(),
            })
            self.store.write_json(f"generated/results/{run_payload['run_id']}.json", run_payload)

        return bridge

    def _map_primary_runtime_event(
        self,
        event: dict[str, Any],
        *,
        participant_index: int,
        participant_name: str,
        resume: bool,
    ) -> dict[str, str] | None:
        event_type = str(event.get("type") or "")
        node_id = str(event.get("node_id") or "runtime")
        stage_prefix = f"participant_{participant_index}_ai_core"

        if event_type == "NODE_STARTED":
            return {
                "stage": f"{stage_prefix}_{node_id}",
                "label": f"Primary runtime node started: {node_id}",
                "status": "running",
            }
        if event_type == "NODE_EXECUTING":
            return {
                "stage": f"{stage_prefix}_{node_id}",
                "label": f"Primary runtime executing node: {node_id}",
                "status": "running",
            }
        if event_type == "NODE_RESULT":
            return {
                "stage": f"{stage_prefix}_{node_id}",
                "label": f"Primary runtime node completed: {node_id}",
                "status": "completed",
            }
        if event_type in {"SECRET_REQUIRED", "INTERACTION_REQUEST", "HUMAN_INPUT_REQUIRED"}:
            return {
                "stage": f"{stage_prefix}_{node_id}_waiting_input",
                "label": f"Primary runtime waiting for required input at: {node_id}",
                "status": "waiting",
            }
        if event_type in {"RUN_PAUSED"}:
            return {
                "stage": f"{stage_prefix}_paused",
                "label": "Primary runtime paused and saved checkpoint",
                "status": "waiting",
            }
        if event_type in {"DURABLE_RESUME_STARTED"}:
            return {
                "stage": f"{stage_prefix}_{node_id}_resume",
                "label": f"Primary runtime resumed from checkpoint: {node_id}",
                "status": "running",
            }
        if event_type in {"RUN_FAILED"}:
            return {
                "stage": f"{stage_prefix}_failed",
                "label": "Primary runtime failed",
                "status": "failed",
            }
        if event_type in {"RUN_COMPLETED"}:
            return {
                "stage": f"{stage_prefix}_completed",
                "label": f"Primary runtime completed participant: {participant_name}",
                "status": "completed",
            }
        return None

    def _record_progress(self, run_payload: dict[str, Any], stage: str, label: str, status: str) -> None:
        run_payload["current_stage"] = stage
        run_payload.setdefault("progress_events", []).append({
            "stage": stage,
            "label": label,
            "status": status,
            "at": self._now(),
        })
        self.store.write_json(f"generated/results/{run_payload['run_id']}.json", run_payload)

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
