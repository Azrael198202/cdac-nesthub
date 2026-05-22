from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
import copy
import re

from ai_core.agent_delegation import AgentExecutionRequest, PrimaryBrainDelegationClient
from auxiliary_brain.storage import JsonStore
from auxiliary_brain.runtime import new_id
from auxiliary_brain.delegation.task_mind_graph import TaskMindGraphBuilder
from auxiliary_brain.parameters.agent_parameter_contract import AgentParameterContractService


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
        self.parameter_contract_service = AgentParameterContractService()

    async def execute_task(self, task_graph: dict[str, Any], participants: list[dict[str, Any]]) -> dict[str, Any]:
        selected = self._fresh_task_participants(self._select_participants(task_graph, participants))
        return await self._execute_task_with_selected(task_graph, selected)

    async def _execute_task_with_selected(self, task_graph: dict[str, Any], selected: list[dict[str, Any]]) -> dict[str, Any]:
        run_id = new_id("delegation_run")
        task_name = str(task_graph.get("task_name") or task_graph.get("graph_id") or "task")
        task_instruction = str(task_graph.get("instruction") or task_graph.get("objective") or "")
        community_id = str(task_graph.get("community_id") or "default")
        task_mind_graph = self._build_task_mind_graph(task_graph, selected)
        dependency_plan = task_mind_graph.get("agent_relation_analysis") or self._build_participant_dependency_plan(task_graph, selected)

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
            "participant_dependency_plan": dependency_plan,
            "task_mind_graph": task_mind_graph,
        }
        self._record_progress(run_payload, "prepare", "Preparing delegation run", "running")
        self._record_global_mind_graph_progress(run_payload, task_mind_graph)

        missing_parameter_fields = self._collect_missing_agent_parameter_fields(selected)
        if missing_parameter_fields:
            pending_action = {
                "kind": "agent_parameter_collection",
                "message": "Agent execution requires parameter values before runtime can continue.",
                "request": {
                    "input_mode": "multi_value_list",
                    "fields": missing_parameter_fields,
                },
            }
            run_payload.update({
                "status": "requires_input",
                "current_stage": "waiting_for_agent_parameters",
                "pending_action": pending_action,
                "missing_inputs": missing_parameter_fields,
                "completed_at": self._now(),
            })
            self._record_progress(run_payload, "waiting_agent_parameters", "Waiting for agent parameter values", "waiting")
            self.store.write_json(f"generated/results/{run_id}.json", run_payload)
            return run_payload

        agent_results = []
        execution_order = self._participants_in_mind_graph_order(selected, task_mind_graph)
        for index, participant in enumerate(execution_order):
            participant_name = str(participant.get("display_name") or participant.get("agent_name") or participant.get("name") or participant.get("participant_id") or "participant")
            self._record_progress(
                run_payload,
                f"participant_{index + 1}_prepare",
                f"Preparing participant: {participant_name}",
                "running",
            )
            shared_context = self._build_participant_shared_context(
                task_graph=task_graph,
                selected=selected,
                participant=participant,
                completed_results=agent_results,
                dependency_plan=dependency_plan,
                task_mind_graph=task_mind_graph,
                for_input_parsing=True,
            )
            request = AgentExecutionRequest(
                participant_id=str(participant.get("participant_id") or participant.get("id")),
                participant_name=participant_name,
                participant_instruction=str(participant.get("execution_objective") or participant.get("instruction") or participant.get("description") or ""),
                task_name=task_name,
                task_instruction=task_instruction,
                community_id=community_id,
                shared_context=shared_context,
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
            result_payload = self._sanitize_result_payload(result.__dict__)
            agent_results.append(result)
            run_payload["agent_results"].append(result_payload)
            self._record_progress(
                run_payload,
                f"participant_{index + 1}_complete",
                f"Participant finished: {participant_name}",
                "completed" if result.status == "completed" else result.status,
            )
            if result.status in {"failed", "incomplete", "timeout"}:
                # Do not mark a failed primary-runtime participant as successful.
                # Keep executing remaining participants so the final synthesis can
                # report all failures, but preserve the failure status in payload.
                pass
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

        run_payload["agent_results"] = self._dedupe_result_payloads(run_payload.get("agent_results") or [])
        agent_results = self._to_agent_results(run_payload["agent_results"])
        self._record_progress(run_payload, "final_synthesis", "Primary runtime synthesizing delegated results", "running")
        synthesis = await self.primary_client.synthesize_delegated_results(
            task_name=task_name,
            task_instruction=task_instruction,
            agent_results=agent_results,
            shared_context={"community_id": community_id, "task_mind_graph": task_mind_graph},
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

        final_status = str(synthesis.get("status") or "")
        failed_statuses = {"failed", "completed_with_no_participant_result", "partial_failed", "no_usable_result"}
        run_payload.update({
            "status": "failed" if final_status in failed_statuses else "completed",
            "current_stage": "failed" if final_status in failed_statuses else "completed",
            "completed_at": self._now(),
            "synthesis": synthesis,
            "delivery": str(delivery_path),
        })
        self.store.write_json(f"generated/results/{run_id}.json", run_payload)
        return run_payload


    async def reoptimize_result(
        self,
        *,
        run_payload: dict[str, Any],
        task_graph: dict[str, Any],
        feedback: dict[str, Any],
        strategy: dict[str, Any],
    ) -> dict[str, Any]:
        """Re-synthesize an existing run without restarting completed work."""
        run_id = str(run_payload.get("run_id") or new_id("delegation_run"))
        task_name = str(task_graph.get("task_name") or run_payload.get("task_name") or "task")
        task_instruction = str(task_graph.get("instruction") or "")
        community_id = str(task_graph.get("community_id") or run_payload.get("community_id") or "default")
        run_payload.setdefault("progress_events", [])
        run_payload["status"] = "reoptimizing"
        run_payload["current_stage"] = "adaptive_resynthesis"
        run_payload.setdefault("adaptation_events", []).append({
            "at": self._now(),
            "feedback": feedback,
            "strategy": strategy,
        })
        self._record_progress(run_payload, "adaptive_resynthesis", "Applying feedback and re-optimizing final result", "running")
        agent_results = self._to_agent_results(self._dedupe_result_payloads(run_payload.get("agent_results") or []))
        synthesis = await self.primary_client.synthesize_delegated_results(
            task_name=task_name,
            task_instruction=task_instruction,
            agent_results=agent_results,
            shared_context={
                "community_id": community_id,
                "feedback": feedback,
                "strategy": strategy,
                "model_escalation_requested": bool(strategy.get("model_escalation")),
            },
        )
        self._record_progress(run_payload, "adaptive_resynthesis_complete", "Adaptive final synthesis completed", "completed")
        delivery_id = new_id("delivery")
        delivery_payload = {
            "delivery_id": delivery_id,
            "origin": "auxiliary_brain",
            "upstream_origin": "ai_core",
            "task_name": task_name,
            "run_id": run_id,
            "final_answer": synthesis.get("final_answer"),
            "synthesis": synthesis,
            "adaptation": {"feedback": feedback, "strategy": strategy},
            "created_at": self._now(),
        }
        delivery_path = self.store.write_json(f"deliveries/{delivery_id}.json", delivery_payload)
        final_status = str(synthesis.get("status") or "")
        failed_statuses = {"failed", "completed_with_no_participant_result", "partial_failed", "no_usable_result"}
        run_payload.update({
            "status": "failed" if final_status in failed_statuses else "completed",
            "current_stage": "failed" if final_status in failed_statuses else "completed",
            "completed_at": self._now(),
            "synthesis": synthesis,
            "delivery": str(delivery_path),
        })
        self.store.write_json(f"generated/results/{run_id}.json", run_payload)
        return run_payload


    async def resume_task(self, run_payload: dict[str, Any], task_graph: dict[str, Any], participants: list[dict[str, Any]], provided_inputs: dict[str, Any] | None = None) -> dict[str, Any]:
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
        pending = run_payload.get("pending_action") if isinstance(run_payload.get("pending_action"), dict) else {}
        if str(pending.get("kind") or "") == "agent_parameter_collection":
            selected = self._fresh_task_participants(selected)
            self._apply_agent_parameter_values(selected, provided_inputs or {})
            return await self._execute_task_with_selected(task_graph, selected)
        task_mind_graph = self._build_task_mind_graph(task_graph, selected)
        dependency_plan = task_mind_graph.get("agent_relation_analysis") or self._build_participant_dependency_plan(task_graph, selected)
        run_payload["participant_dependency_plan"] = dependency_plan
        run_payload["status"] = "resuming"
        run_payload["current_stage"] = "resuming"
        # Once resume has been accepted, the top-level waiting contract must be
        # cleared immediately. Otherwise the UI keeps showing a required-input
        # prompt while the primary runtime is already continuing from the
        # checkpoint. Participant-level paused payloads are left intact until
        # the primary runtime returns the resumed result, because they carry the
        # durable checkpoint identity needed by the resume call.
        self._clear_waiting_fields(run_payload)
        self._record_progress(run_payload, "durable_resume", "Durable resume requested", "running")
        self.store.write_json(f"generated/results/{run_id}.json", run_payload)

        existing_results = self._dedupe_result_payloads(list(run_payload.get("agent_results") or []))
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
                    provided_inputs=provided_inputs,
                )
                resumed_payload = self._sanitize_result_payload(resumed.__dict__)
                existing_results[idx] = resumed_payload
                existing_results = self._dedupe_result_payloads(existing_results)
                run_payload["agent_results"] = existing_results
                if resumed.status not in {"requires_key", "requires_input", "paused"}:
                    self._clear_waiting_fields(run_payload)
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
            participant_name = str(participant.get("display_name") or participant.get("agent_name") or participant.get("name") or participant_id or "participant")
            self._record_progress(run_payload, f"participant_{index + 1}_primary_runtime", f"Primary runtime executing participant: {participant_name}", "running")
            request = AgentExecutionRequest(
                participant_id=participant_id,
                participant_name=participant_name,
                participant_instruction=str(participant.get("execution_objective") or participant.get("instruction") or participant.get("description") or ""),
                task_name=task_name,
                task_instruction=task_instruction,
                community_id=community_id,
                shared_context=self._build_participant_shared_context(
                    task_graph=task_graph,
                    selected=selected,
                    participant=participant,
                    completed_results=agent_results,
                    dependency_plan=dependency_plan,
                    task_mind_graph=task_mind_graph,
                    for_input_parsing=True,
                ),
            )
            result = await self._execute_agent_request_with_progress(
                request,
                self._build_primary_runtime_progress_bridge(
                    run_payload,
                    participant_index=index + 1,
                    participant_name=participant_name,
                ),
            )
            payload = self._sanitize_result_payload(result.__dict__)
            existing_results.append(payload)
            agent_results.append(result)
            self._record_progress(run_payload, f"participant_{index + 1}_complete", f"Participant finished: {participant_name}", "completed" if result.status == "completed" else result.status)
            if result.status in {"failed", "incomplete", "timeout"}:
                # Do not mark a failed primary-runtime participant as successful.
                # Keep executing remaining participants so the final synthesis can
                # report all failures, but preserve the failure status in payload.
                pass
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

        existing_results = self._dedupe_result_payloads(existing_results)
        run_payload["agent_results"] = existing_results
        self._clear_waiting_fields(run_payload)
        agent_results = self._to_agent_results(existing_results)
        self._record_progress(run_payload, "final_synthesis", "Primary runtime synthesizing delegated results", "running")
        synthesis = await self.primary_client.synthesize_delegated_results(
            task_name=task_name,
            task_instruction=task_instruction,
            agent_results=agent_results,
            shared_context={"community_id": community_id, "task_mind_graph": task_mind_graph},
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
        final_status = str(synthesis.get("status") or "")
        failed_statuses = {"failed", "completed_with_no_participant_result", "partial_failed", "no_usable_result"}
        run_payload.update({
            "status": "failed" if final_status in failed_statuses else "completed",
            "current_stage": "failed" if final_status in failed_statuses else "completed",
            "completed_at": self._now(),
            "synthesis": synthesis,
            "delivery": str(delivery_path),
        })
        self.store.write_json(f"generated/results/{run_id}.json", run_payload)
        return run_payload


    def _participant_identity(self, participant: dict[str, Any]) -> str:
        return str(participant.get("participant_id") or participant.get("id") or participant.get("name") or "").strip()

    def _participant_name(self, participant: dict[str, Any]) -> str:
        return str(participant.get("display_name") or participant.get("agent_name") or participant.get("name") or participant.get("participant_id") or participant.get("id") or "participant").strip()

    def _participant_objective(self, participant: dict[str, Any]) -> str:
        return str(participant.get("execution_objective") or participant.get("instruction") or participant.get("description") or "").strip()

    def _build_task_mind_graph(self, task_graph: dict[str, Any], selected: list[dict[str, Any]]) -> dict[str, Any]:
        """Create the top-level task mind graph before executing agents.

        The graph is stored in runtime results and used only for coordination.
        Every agent still runs its own primary-runtime flow. Independent agent
        nodes do not receive peer output. Dependent agent nodes receive only the
        upstream safe JSON summaries declared by graph edges.
        """
        return TaskMindGraphBuilder().build(task_graph, selected)

    def _record_global_mind_graph_progress(self, run_payload: dict[str, Any], task_mind_graph: dict[str, Any]) -> None:
        stages = [
            ("global_input_parsing", "Global task input parsing completed"),
            ("global_intent_recognition", "Global task intent recognition completed"),
            ("global_workflow_planning", "Global task workflow planning completed"),
            ("global_agent_relation_analysis", "Agent relation analysis completed"),
            ("global_graph_generation", "Task mind graph generated"),
        ]
        for stage, label in stages:
            self._record_progress(run_payload, stage, label, "completed")
        run_payload["current_stage"] = "task_mind_graph_generated"

    def _participants_in_mind_graph_order(self, selected: list[dict[str, Any]], task_mind_graph: dict[str, Any]) -> list[dict[str, Any]]:
        by_id = {self._participant_identity(p): p for p in selected if self._participant_identity(p)}
        ordered: list[dict[str, Any]] = []
        for group in ((task_mind_graph.get("execution_plan") or {}).get("groups") or []):
            for pid in group:
                participant = by_id.get(str(pid))
                if participant and participant not in ordered:
                    ordered.append(participant)
        for participant in selected:
            if participant not in ordered:
                ordered.append(participant)
        return ordered

    def _mind_graph_node_for_participant(self, task_mind_graph: dict[str, Any], participant: dict[str, Any]) -> dict[str, Any]:
        pid = self._participant_identity(participant)
        for node in task_mind_graph.get("nodes") or []:
            if isinstance(node, dict) and str(node.get("node_id") or "") == pid:
                return node
        return {}

    def _build_participant_dependency_plan(self, task_graph: dict[str, Any], selected: list[dict[str, Any]]) -> dict[str, Any]:
        """Build a coordination-only dependency plan for participant execution.

        Default is independent. A participant receives another participant's
        result only when there is an explicit dependency signal in the task
        graph/participant definition or a clear textual reference to that
        participant's result. This prevents unrelated agents from polluting each
        other's LLM input-parsing prompts.
        """
        identities = {self._participant_identity(p): p for p in selected if self._participant_identity(p)}
        name_to_id = {self._participant_name(p).lower(): pid for pid, p in identities.items()}
        plan: dict[str, Any] = {
            "default_relationship": "independent",
            "participants": {},
            "edges": [],
        }
        explicit_by_task: dict[str, list[str]] = {}
        for task in task_graph.get("tasks") or []:
            if not isinstance(task, dict):
                continue
            target = str(task.get("participant_id") or task.get("participant") or task.get("agent_id") or "").strip()
            raw_deps = task.get("depends_on") or task.get("requires") or task.get("input_from") or []
            if isinstance(raw_deps, str):
                raw_deps = [raw_deps]
            deps = [str(x).strip() for x in raw_deps if str(x).strip()]
            if target and deps:
                explicit_by_task.setdefault(target, []).extend(deps)

        for pid, participant in identities.items():
            objective = self._participant_objective(participant).lower()
            raw_deps = participant.get("depends_on") or participant.get("requires") or participant.get("input_from") or explicit_by_task.get(pid) or []
            if isinstance(raw_deps, str):
                raw_deps = [raw_deps]
            deps: list[str] = []
            for item in raw_deps:
                dep = str(item).strip()
                if not dep:
                    continue
                dep_id = dep if dep in identities else name_to_id.get(dep.lower(), dep)
                if dep_id != pid and dep_id not in deps:
                    deps.append(dep_id)
            # Clear textual references only. Do not infer dependencies merely
            # because two participants appear in the same task instruction.
            dependency_markers = ["result", "output", "answer", "previous", "upstream", "after", "based on"]
            if any(marker in objective for marker in dependency_markers):
                for other_id, other in identities.items():
                    if other_id == pid:
                        continue
                    other_name = self._participant_name(other).lower()
                    if other_name and other_name in objective and other_id not in deps:
                        deps.append(other_id)
            relationship = "dependent" if deps else "independent"
            plan["participants"][pid] = {
                "participant_id": pid,
                "participant_name": self._participant_name(participant),
                "relationship": relationship,
                "depends_on": deps,
                "peer_results_injected": bool(deps),
            }
            for dep_id in deps:
                plan["edges"].append({"from": dep_id, "to": pid, "reason": "declared_or_clear_result_reference"})
        return plan

    def _build_participant_shared_context(
        self,
        *,
        task_graph: dict[str, Any],
        selected: list[dict[str, Any]],
        participant: dict[str, Any],
        completed_results: list[Any],
        dependency_plan: dict[str, Any],
        task_mind_graph: dict[str, Any] | None = None,
        for_input_parsing: bool = False,
    ) -> dict[str, Any]:
        task_mind_graph = task_mind_graph or self._build_task_mind_graph(task_graph, selected)
        participant_id = self._participant_identity(participant)
        participant_plan = (dependency_plan.get("participants") or {}).get(participant_id) or {}
        own_node = self._mind_graph_node_for_participant(task_mind_graph, participant)
        # For the participant's first input_parsing call, pass only its own
        # minimal parameter state. Do not include the full mind graph, dependency
        # plan, policy blocks, or peer results. Those coordination artifacts stay
        # in the delegation run and are used by final synthesis / dependent-agent
        # later stages only.
        if for_input_parsing:
            return {
                "task_graph_id": task_graph.get("graph_id"),
                "participant_count": len(selected),
                "relationship": participant_plan.get("relationship") or own_node.get("relation") or "independent",
                "depends_on": participant_plan.get("depends_on") or own_node.get("depends_on") or [],
                "agent_parameters": {
                    "values": participant.get("runtime_parameters") or {},
                    "missing": self.parameter_contract_service.missing_parameters(participant),
                },
                "uploaded_artifacts": participant.get("uploaded_artifacts") or task_graph.get("uploaded_artifacts") or [],
                "available_artifacts": participant.get("uploaded_artifacts") or task_graph.get("uploaded_artifacts") or [],
                "artifact_policy": participant.get("artifact_policy") or {},
                "artifact_binding": {
                    "available": bool(participant.get("uploaded_artifacts") or task_graph.get("uploaded_artifacts")),
                    "resolution_key": "artifact_id_or_filename",
                    "preferred_action_type": "use_uploaded_file",
                },
            }

        shared_context: dict[str, Any] = {
            "task_graph_id": task_graph.get("graph_id"),
            "participant_count": len(selected),
            "relationship": participant_plan.get("relationship") or own_node.get("relation") or "independent",
            "depends_on": participant_plan.get("depends_on") or own_node.get("depends_on") or [],
            "participant_dependency_policy": {
                "default_relationship": "independent",
                "peer_results_are_injected_only_for_declared_dependencies": True,
                "independent_results_are_merged_only_at_final_synthesis": True,
                "peer_result_format": "strict_json_safe_summary",
            },
            "agent_parameters": {
                "values": participant.get("runtime_parameters") or {},
                "contract": self._compact_parameter_contract(participant.get("parameter_contract") or {}),
            },
            "uploaded_artifacts": participant.get("uploaded_artifacts") or task_graph.get("uploaded_artifacts") or [],
            "available_artifacts": participant.get("uploaded_artifacts") or task_graph.get("uploaded_artifacts") or [],
            "artifact_policy": participant.get("artifact_policy") or {},
            "artifact_binding": {
                "available": bool(participant.get("uploaded_artifacts") or task_graph.get("uploaded_artifacts")),
                "resolution_key": "artifact_id_or_filename",
                "preferred_action_type": "use_uploaded_file",
            },
        }
        peer_results = self._peer_results_for_participant(participant, completed_results, dependency_plan)
        if peer_results:
            shared_context["available_peer_results"] = peer_results
        return shared_context



    def _compact_parameter_contract(self, contract: Any) -> dict[str, Any]:
        if not isinstance(contract, dict):
            return {}
        out = {"parameters": []}
        params = contract.get("parameters") if isinstance(contract.get("parameters"), list) else []
        for param in params:
            if not isinstance(param, dict):
                continue
            out["parameters"].append({
                "name": param.get("name"),
                "type": param.get("type") or "list",
                "required": bool(param.get("required", True)),
                "values": param.get("values") if isinstance(param.get("values"), list) else [],
            })
        return out

    def _collect_missing_agent_parameter_fields(self, participants: list[dict[str, Any]]) -> list[dict[str, Any]]:
        fields: list[dict[str, Any]] = []
        for participant in participants:
            # If the agent is explicitly bound to uploaded artifacts, the real
            # executable parameter contract is owned by artifact introspection
            # in execution_preparation, not by the durable agent profile.
            # This avoids asking stale or inferred agent-level fields before the
            # uploaded file has been inspected. The UI will receive the concrete
            # runtime fields produced from the artifact callable/signature.
            if self._uses_uploaded_artifact_runtime(participant):
                continue
            fields.extend(self.parameter_contract_service.to_missing_input_fields(participant))
        return fields

    def _uses_uploaded_artifact_runtime(self, participant: dict[str, Any]) -> bool:
        if not isinstance(participant, dict):
            return False
        artifacts = participant.get("uploaded_artifacts")
        if isinstance(artifacts, list) and artifacts:
            return True
        policy = participant.get("artifact_policy") if isinstance(participant.get("artifact_policy"), dict) else {}
        if policy.get("bind_uploaded_artifacts_to_agent") or str(policy.get("allowed_action") or "") == "use_uploaded_file":
            return True
        text = " ".join(str(participant.get(k) or "") for k in ("instruction", "execution_objective", "definition_instruction", "objective"))
        return bool(re.search(r"\buse\s+file\b|\b[a-zA-Z0-9_.-]+\.[A-Za-z0-9]{1,8}\b", text, flags=re.I))

    def _apply_agent_parameter_values(self, participants: list[dict[str, Any]], provided_inputs: dict[str, Any]) -> None:
        if not isinstance(provided_inputs, dict):
            return
        for participant in participants:
            updated = self.parameter_contract_service.apply_values(participant, provided_inputs)
            pid = str(updated.get("participant_id") or "").strip()
            if pid:
                self.store.write_json(f"generated/agents/{pid}.json", updated)

    def _peer_results_for_participant(self, participant: dict[str, Any], completed_results: list[Any], dependency_plan: dict[str, Any]) -> list[dict[str, Any]]:
        pid = self._participant_identity(participant)
        participant_plan = (dependency_plan.get("participants") or {}).get(pid) or {}
        deps = {str(x) for x in participant_plan.get("depends_on") or [] if str(x)}
        if not deps:
            return []
        safe_results: list[dict[str, Any]] = []
        for result in completed_results:
            result_pid = str(getattr(result, "participant_id", "") or "")
            result_name = str(getattr(result, "participant_name", "") or "")
            if result_pid not in deps and result_name not in deps:
                continue
            safe_results.append(self._safe_peer_result(result))
        return safe_results

    def _safe_peer_result(self, result: Any) -> dict[str, Any]:
        """Return a strict JSON object for dependent-agent context.

        Never use Python repr strings. Keep the summary compact and schema-safe so
        downstream LLM JSON output is not destabilized by quotes, newlines, or
        partially trimmed dictionaries.
        """
        return {
            "participant_id": str(getattr(result, "participant_id", "") or ""),
            "participant_name": str(getattr(result, "participant_name", "") or ""),
            "status": str(getattr(result, "status", "") or ""),
            "final_answer_summary": self._compact_text(getattr(result, "final_answer", "") or "", 600),
            "missing_inputs": list(getattr(result, "missing_inputs", None) or []),
        }

    def _compact_text(self, value: Any, max_chars: int = 800) -> str:
        """Return a short, JSON-safe text preview for peer-agent context.

        This is coordination-only data. It must not change the participant's
        own objective; it only gives later participants compact optional context
        from already finished peers.
        """
        if value is None:
            return ""
        text = str(value)
        text = " ".join(text.split())
        if max_chars <= 0:
            return text
        if len(text) <= max_chars:
            return text
        return text[: max_chars - 3].rstrip() + "..."

    def _result_key(self, payload: dict[str, Any]) -> str:
        return str(payload.get("participant_id") or payload.get("participant_name") or "")

    def _dedupe_result_payloads(self, payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Keep the latest result per participant and prefer non-paused results.

        Durable resume first stores a paused result and later replaces it with a
        completed result. This helper prevents stale waiting placeholders from
        being included in final synthesis.
        """
        order: list[str] = []
        merged: dict[str, dict[str, Any]] = {}
        paused_statuses = {"requires_key", "requires_input", "paused"}
        for payload in payloads:
            if not isinstance(payload, dict):
                continue
            key = self._result_key(payload)
            if not key:
                key = str(len(order))
            if key not in merged:
                order.append(key)
                merged[key] = payload
                continue
            old_status = str(merged[key].get("status") or "")
            new_status = str(payload.get("status") or "")
            if old_status in paused_statuses and new_status not in paused_statuses:
                merged[key] = payload
            else:
                merged[key] = payload
        return [merged[key] for key in order if key in merged]

    def _to_agent_results(self, payloads: list[dict[str, Any]]):
        from ai_core.agent_delegation import AgentExecutionResult
        results = []
        paused_statuses = {"requires_key", "requires_input", "paused"}
        for payload in self._dedupe_result_payloads(payloads):
            status = str(payload.get("status") or "")
            if status in paused_statuses:
                continue
            try:
                results.append(AgentExecutionResult(**payload))
            except Exception:
                continue
        return results

    def _clear_waiting_fields(self, run_payload: dict[str, Any]) -> None:
        for key in ["pending_action", "missing_inputs"]:
            run_payload.pop(key, None)

    def _sanitize_result_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            return payload
        status = str(payload.get("status") or "")
        if status not in {"requires_key", "requires_input", "paused"}:
            payload.pop("pending_action", None)
            payload["missing_inputs"] = []
        return payload

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

    async def _resume_agent_request_with_progress(self, payload, progress_callback, provided_inputs: dict[str, Any] | None = None):
        try:
            return await self.primary_client.resume_agent_request(
                payload,
                progress_callback=progress_callback,
                provided_inputs=provided_inputs,
            )
        except TypeError as exc:
            if "progress_callback" not in str(exc):
                raise
            return await self.primary_client.resume_agent_request(payload, provided_inputs=provided_inputs)

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

    def _fresh_task_participants(self, participants: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Return task-run copies with no persisted runtime values.

        Agent definitions are durable capability/schema records. Parameter values
        belong to one task run only. This prevents a later task execution from
        silently reusing values collected during an earlier run.
        """
        fresh: list[dict[str, Any]] = []
        for participant in participants:
            item = copy.deepcopy(participant)
            item["runtime_parameters"] = {}
            contract = item.get("parameter_contract") if isinstance(item.get("parameter_contract"), dict) else {}
            params = contract.get("parameters") if isinstance(contract.get("parameters"), list) else []
            for param in params:
                if isinstance(param, dict):
                    param["values"] = []
            if isinstance(contract, dict):
                contract["missing_information"] = self.parameter_contract_service.missing_parameters({"parameter_contract": contract, "runtime_parameters": {}})
                item["parameter_contract"] = contract
            item["missing_information"] = item.get("parameter_contract", {}).get("missing_information", []) if isinstance(item.get("parameter_contract"), dict) else []
            fresh.append(item)
        return fresh

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
