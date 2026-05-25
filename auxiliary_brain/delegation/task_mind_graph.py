from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TaskMindGraphNode:
    node_id: str
    node_type: str
    name: str
    objective: str
    depends_on: list[str]
    relation: str


class TaskMindGraphBuilder:
    """Builds a coordination mind-map for multi-agent task execution.

    This builder is intentionally domain-neutral. It does not hard-code business
    capabilities. It only reasons over task/participant structure and explicit
    dependency fields provided by the runtime workflow graph. The primary runtime may later replace or refine this graph with an
    LLM-generated version; the graph shape and contracts remain the same.
    """

    def build(self, task_graph: dict[str, Any], participants: list[dict[str, Any]]) -> dict[str, Any]:
        selected = [p for p in participants if isinstance(p, dict)]
        participant_ids = [self._participant_id(p) for p in selected]
        participant_ids = [pid for pid in participant_ids if pid]

        nodes: list[dict[str, Any]] = [
            {
                "node_id": "global_understanding",
                "node_type": "global_task_stage",
                "name": "Global task understanding",
                "objective": "Understand the user task and create the participant execution graph.",
                "stage_sequence": [
                    "input_parsing",
                    "intent_recognition",
                    "workflow_planning",
                    "agent_relation_analysis",
                    "graph_generation",
                ],
                "depends_on": [],
                "relation": "root",
            }
        ]

        relation_plan = self._relation_plan(task_graph, selected)
        for participant in selected:
            pid = self._participant_id(participant)
            plan = relation_plan["participants"].get(pid, {})
            deps = list(plan.get("depends_on") or [])
            nodes.append({
                "node_id": pid,
                "node_type": "agent_node",
                "name": self._participant_name(participant),
                "objective": self._participant_objective(participant),
                "stage_sequence": [
                    "input_parsing",
                    "intent_recognition",
                    "context_awareness",
                    "workflow_planning",
                    "execution",
                    "feedback_learning",
                    "output",
                ],
                "depends_on": deps,
                "relation": "dependent" if deps else "independent",
                "input_contract": {
                    "own_objective_is_primary": True,
                    "peer_results_allowed": bool(deps),
                    "peer_results_format": "strict_json_safe_summary",
                },
                "output_contract": {
                    "result_is_collected_for_final_synthesis": True,
                    "raw_intermediate_json_is_not_final_answer": True,
                },
            })

        nodes.append({
            "node_id": "final_synthesis",
            "node_type": "global_task_stage",
            "name": "Final synthesis",
            "objective": "Merge completed participant outputs with the original task into the final answer.",
            "stage_sequence": [
                "collect_agent_outputs",
                "verify_results",
                "generate_final_answer",
            ],
            "depends_on": participant_ids,
            "relation": "collector",
        })

        edges = [{"from": "global_understanding", "to": pid, "data_contract": "task_objective_json"} for pid in participant_ids]
        edges.extend(relation_plan.get("edges") or [])
        edges.extend({"from": pid, "to": "final_synthesis", "data_contract": "participant_final_result"} for pid in participant_ids)

        execution_groups = self._execution_groups(participant_ids, relation_plan.get("edges") or [])
        return {
            "graph_type": "task_mind_graph",
            "status": "generated",
            "generation_mode": "coordination_policy",
            "task": {
                "task_name": str(task_graph.get("task_name") or task_graph.get("graph_id") or "task"),
                "instruction": str(task_graph.get("instruction") or task_graph.get("objective") or ""),
            },
            "nodes": nodes,
            "edges": edges,
            "agent_relation_analysis": relation_plan,
            "execution_plan": {
                "mode": "dependency_groups",
                "groups": execution_groups,
                "independent_agents_may_run_without_peer_context": True,
                "dependent_agents_receive_only_declared_upstream_safe_json": True,
                "final_synthesis_after_all_terminal_agent_results": True,
            },
        }

    def _relation_plan(self, task_graph: dict[str, Any], selected: list[dict[str, Any]]) -> dict[str, Any]:
        identities = {self._participant_id(p): p for p in selected if self._participant_id(p)}
        name_to_id = {self._participant_name(p).lower(): pid for pid, p in identities.items()}
        plan: dict[str, Any] = {"default_relationship": "independent", "participants": {}, "edges": []}

        task_ref_to_participant: dict[str, str] = {}
        for task in task_graph.get("tasks") or []:
            if not isinstance(task, dict):
                continue
            target = str(task.get("participant_id") or task.get("participant") or task.get("agent_id") or "").strip()
            if not target:
                continue
            for key in ("participant_id", "participant", "agent_id", "task_id", "source_step_id", "id", "node_id"):
                value = str(task.get(key) or "").strip()
                if value:
                    task_ref_to_participant[value] = target

        explicit_by_task: dict[str, list[str]] = {}
        for task in task_graph.get("tasks") or []:
            if not isinstance(task, dict):
                continue
            target = str(task.get("participant_id") or task.get("participant") or task.get("agent_id") or "").strip()
            raw_deps = task.get("depends_on") or task.get("requires") or task.get("input_from") or []
            if isinstance(raw_deps, str):
                raw_deps = [raw_deps]
            deps = []
            for item in raw_deps:
                dep = str(item).strip()
                if not dep:
                    continue
                deps.append(task_ref_to_participant.get(dep, dep))
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
                dep_id = task_ref_to_participant.get(dep, dep if dep in identities else name_to_id.get(dep.lower(), dep))
                if dep_id != pid and dep_id not in deps:
                    deps.append(dep_id)

            # Dependencies must come from explicit graph fields.  This builder
            # intentionally does not infer dataflow from vocabulary markers.

            plan["participants"][pid] = {
                "participant_id": pid,
                "participant_name": self._participant_name(participant),
                "relationship": "dependent" if deps else "independent",
                "depends_on": deps,
                "peer_results_injected": bool(deps),
            }
            for dep_id in deps:
                plan["edges"].append({"from": dep_id, "to": pid, "data_contract": "strict_json_safe_summary", "reason": "declared_or_clear_result_reference"})
        return plan

    def _execution_groups(self, participant_ids: list[str], edges: list[dict[str, Any]]) -> list[list[str]]:
        deps: dict[str, set[str]] = {pid: set() for pid in participant_ids}
        for edge in edges:
            src = str(edge.get("from") or "")
            dst = str(edge.get("to") or "")
            if src in deps and dst in deps:
                deps[dst].add(src)
        remaining = set(participant_ids)
        completed: set[str] = set()
        groups: list[list[str]] = []
        while remaining:
            ready = sorted(pid for pid in remaining if deps.get(pid, set()).issubset(completed))
            if not ready:
                # Cycle or invalid reference. Keep a stable terminal group so the
                # runtime can fail or execute conservatively without hanging.
                groups.append(sorted(remaining))
                break
            groups.append(ready)
            completed.update(ready)
            remaining.difference_update(ready)
        return groups

    def _participant_id(self, participant: dict[str, Any]) -> str:
        return str(participant.get("participant_id") or participant.get("id") or participant.get("name") or "").strip()

    def _participant_name(self, participant: dict[str, Any]) -> str:
        return str(participant.get("display_name") or participant.get("agent_name") or participant.get("name") or participant.get("participant_id") or participant.get("id") or "participant").strip()

    def _participant_objective(self, participant: dict[str, Any]) -> str:
        return str(
            participant.get("graph_display_objective")
            or participant.get("task_step_instruction")
            or participant.get("execution_objective")
            or participant.get("instruction")
            or participant.get("description")
            or ""
        ).strip()
