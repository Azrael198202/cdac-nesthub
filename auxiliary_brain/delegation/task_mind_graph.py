from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import re


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
                "input_contract": plan.get("input_contract") or {
                    "contract_type": "runtime_step_input_contract",
                    "bound_from_upstream": deps,
                    "accepts_verified_material": bool(deps),
                    "user_input_required_for_bound_material": False,
                },
                "output_contract": plan.get("output_contract") or {
                    "contract_type": "runtime_step_output_contract",
                    "produces_verified_material": True,
                    "planner_metadata_is_not_result_material": True,
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
        task_order = self._task_participant_order(task_graph, identities)
        alias_to_pid = self._dependency_alias_map(task_graph, identities)
        plan: dict[str, Any] = {
            "default_relationship": "independent",
            "participants": {},
            "edges": [],
            "dataflow_contracts": {},
            "self_check": {"status": "pending"},
        }

        explicit_by_task: dict[str, list[str]] = {}
        contract_by_task: dict[str, dict[str, Any]] = {}
        for task in task_graph.get("tasks") or []:
            if not isinstance(task, dict):
                continue
            target = self._resolve_dependency_alias(
                task.get("participant_id") or task.get("participant") or task.get("agent_id"),
                alias_to_pid,
            )
            if not target:
                continue
            raw_deps = self._task_dependency_candidates(task)
            deps: list[str] = []
            for item in raw_deps:
                dep_id = self._resolve_dependency_alias(item, alias_to_pid)
                if dep_id and dep_id != target and dep_id not in deps:
                    deps.append(dep_id)
            explicit_by_task.setdefault(target, []).extend(deps)
            contract_by_task[target] = {
                "input_contract": task.get("input_contract") if isinstance(task.get("input_contract"), dict) else {},
                "output_contract": task.get("output_contract") if isinstance(task.get("output_contract"), dict) else {},
                "source_step_id": task.get("source_step_id"),
                "source_instruction_fragment": task.get("source_instruction_fragment"),
            }

        for target, dep_id in self._workflow_variable_dependency_edges(task_graph, alias_to_pid):
            if target and dep_id and target != dep_id:
                explicit_by_task.setdefault(target, [])
                if dep_id not in explicit_by_task[target]:
                    explicit_by_task[target].append(dep_id)

        raw_plan: dict[str, list[str]] = {}
        has_task_dependencies = any(explicit_by_task.values())
        for pid, participant in identities.items():
            raw: list[str] = []
            raw.extend(explicit_by_task.get(pid) or [])
            if not raw:
                for item in self._task_dependency_candidates(participant):
                    dep_id = self._resolve_dependency_alias(item, alias_to_pid)
                    if dep_id and dep_id != pid and dep_id not in raw:
                        raw.append(dep_id)

            # Textual references are a last-resort structural signal only when
            # the task graph did not already declare dataflow.  This keeps the
            # source code domain-neutral while preventing inferred references
            # from overriding explicit step contracts.
            if not has_task_dependencies and not raw:
                objective = self._participant_objective(participant).lower()
                for alias, peer_id in alias_to_pid.items():
                    if peer_id == pid or peer_id in raw:
                        continue
                    if alias and alias in self._normalize_dependency_key(objective):
                        raw.append(peer_id)
            raw_plan[pid] = raw

        normalized_plan, removed_edges = self._normalize_dependency_map(raw_plan, task_order)
        for pid, participant in identities.items():
            deps = normalized_plan.get(pid) or []
            original_input_contract = (contract_by_task.get(pid) or {}).get("input_contract") or {}
            if original_input_contract:
                input_contract = dict(original_input_contract)
                input_contract["bound_from_upstream"] = deps
                input_contract["accepts_verified_material"] = bool(deps) or bool(input_contract.get("accepts_verified_material"))
                input_contract.setdefault("contract_type", "runtime_step_input_contract")
                input_contract.setdefault("user_input_required_for_bound_material", False)
            else:
                input_contract = {
                    "contract_type": "runtime_step_input_contract",
                    "bound_from_upstream": deps,
                    "accepts_verified_material": bool(deps),
                    "user_input_required_for_bound_material": False,
                }
            output_contract = (contract_by_task.get(pid) or {}).get("output_contract") or {
                "contract_type": "runtime_step_output_contract",
                "produces_verified_material": True,
                "planner_metadata_is_not_result_material": True,
            }
            plan["participants"][pid] = {
                "participant_id": pid,
                "participant_name": self._participant_name(participant),
                "relationship": "dependent" if deps else "independent",
                "depends_on": deps,
                "peer_results_injected": bool(deps),
                "input_contract": input_contract,
                "output_contract": output_contract,
            }
            plan["dataflow_contracts"][pid] = {"input_contract": input_contract, "output_contract": output_contract}
            for dep_id in deps:
                plan["edges"].append({
                    "from": dep_id,
                    "to": pid,
                    "data_contract": "verified_material",
                    "reason": "declared_dataflow_contract",
                })
        plan["self_check"] = {
            "status": "passed" if not removed_edges else "repaired",
            "removed_edges": removed_edges,
            "cycle_free": True,
            "participant_order": task_order,
            "repair_plan": [
                {"action": "remove_invalid_dependency", "from": item.get("from"), "to": item.get("to"), "reason": item.get("reason")}
                for item in removed_edges
            ],
        }
        return plan

    def _normalize_dependency_key(self, value: Any) -> str:
        text = str(value or "").strip().casefold()
        text = re.sub(r"\s+", "", text)
        text = text.replace("-", "_")
        text = re.sub(r"_+", "_", text)
        return text.strip("_")

    def _dependency_alias_map(self, task_graph: dict[str, Any], identities: dict[str, dict[str, Any]]) -> dict[str, str]:
        aliases: dict[str, str] = {}

        def add(value: Any, pid: str) -> None:
            key = self._normalize_dependency_key(value)
            if key and pid:
                aliases.setdefault(key, pid)

        for pid, participant in identities.items():
            add(pid, pid)
            add(self._participant_name(participant), pid)
            for key in ("source_step_id", "declared_step_id", "structural_step_id", "id", "task_id", "step_id", "participant_display_name", "display_name", "name"):
                add(participant.get(key), pid)

        for ordinal, task in enumerate(task_graph.get("tasks") or [], start=1):
            if not isinstance(task, dict):
                continue
            raw_pid = str(task.get("participant_id") or task.get("participant") or task.get("agent_id") or "").strip()
            pid = raw_pid if raw_pid in identities else self._resolve_dependency_alias(raw_pid, aliases)
            if not pid:
                continue
            values = [
                raw_pid,
                task.get("id"), task.get("task_id"), task.get("step_id"),
                task.get("source_step_id"), task.get("declared_step_id"), task.get("structural_step_id"),
                task.get("participant_display_name"), task.get("display_name"), task.get("name"), task.get("agent_name"),
                f"step{ordinal}", f"step_{ordinal}", f"step {ordinal}", f"step_{ordinal:03d}",
                f"stage{ordinal}", f"stage_{ordinal}", f"stage {ordinal}",
            ]
            for value in values:
                add(value, pid)
                match = re.search(r"(\d+)", str(value or ""))
                if match:
                    number = int(match.group(1))
                    for template in ("step{}", "step_{}", "step {}", "step_{:03d}", "stage{}", "stage_{}", "stage {}"):
                        try:
                            add(template.format(number), pid)
                        except Exception:
                            pass
        return aliases

    def _resolve_dependency_alias(self, value: Any, alias_to_pid: dict[str, str]) -> str:
        key = self._normalize_dependency_key(value)
        if not key:
            return ""
        if key in alias_to_pid:
            return alias_to_pid[key]
        # Some runtime-parameter keys append a field name to a participant or step
        # alias.  Resolve the longest structural prefix without relying on any
        # business-specific field names.
        for alias in sorted(alias_to_pid, key=len, reverse=True):
            if alias and (key.startswith(alias + "_") or key.startswith(alias + ".")):
                return alias_to_pid[alias]
        return ""

    def _task_dependency_candidates(self, item: dict[str, Any]) -> list[Any]:
        candidates: list[Any] = []
        for key in ("depends_on", "requires", "input_from"):
            value = item.get(key)
            if isinstance(value, list):
                candidates.extend(value)
            elif value not in (None, "", [], {}):
                candidates.append(value)
        input_contract = item.get("input_contract") if isinstance(item.get("input_contract"), dict) else {}
        bound = input_contract.get("bound_from_upstream")
        if isinstance(bound, list):
            candidates.extend(bound)
        elif bound not in (None, "", [], {}):
            candidates.append(bound)
        return candidates

    def _workflow_variable_dependency_edges(self, task_graph: dict[str, Any], alias_to_pid: dict[str, str]) -> list[tuple[str, str]]:
        contract = task_graph.get("workflow_variable_contract") if isinstance(task_graph.get("workflow_variable_contract"), dict) else {}
        bindings = contract.get("bindings") if isinstance(contract.get("bindings"), list) else []
        edges: list[tuple[str, str]] = []
        for binding in bindings:
            if not isinstance(binding, dict):
                continue
            target = self._resolve_dependency_alias(
                binding.get("target_step") or binding.get("target_step_id") or binding.get("to_step") or binding.get("target_path"),
                alias_to_pid,
            )
            source = self._resolve_dependency_alias(
                binding.get("source_step_id") or binding.get("source_step") or binding.get("from_step") or binding.get("source_alias") or str(binding.get("reference") or "").split(".", 1)[0],
                alias_to_pid,
            )
            if target and source and target != source and (target, source) not in edges:
                edges.append((target, source))
        return edges

    def _task_participant_order(self, task_graph: dict[str, Any], identities: dict[str, dict[str, Any]]) -> list[str]:
        order: list[str] = []
        names = {self._participant_name(p).lower(): pid for pid, p in identities.items()}
        for task in task_graph.get("tasks") or []:
            if not isinstance(task, dict):
                continue
            target = str(task.get("participant_id") or task.get("participant") or task.get("agent_id") or "").strip()
            if target and target not in identities:
                target = names.get(target.lower(), target)
            if target in identities and target not in order:
                order.append(target)
        for pid in identities:
            if pid not in order:
                order.append(pid)
        return order

    def _normalize_dependency_map(self, raw: dict[str, list[str]], order: list[str]) -> tuple[dict[str, list[str]], list[dict[str, str]]]:
        order_index = {pid: idx for idx, pid in enumerate(order)}
        normalized: dict[str, list[str]] = {pid: [] for pid in order}
        removed: list[dict[str, str]] = []
        for target, deps in raw.items():
            if target not in normalized:
                normalized[target] = []
            for dep in deps or []:
                if dep == target:
                    removed.append({"from": dep, "to": target, "reason": "self_dependency"})
                    continue
                if dep not in order_index or target not in order_index:
                    removed.append({"from": dep, "to": target, "reason": "unknown_endpoint"})
                    continue
                # A downstream step may depend only on material that is produced
                # earlier in the declared task order.  Backward edges create
                # waits that cannot be satisfied and are removed before runtime.
                if order_index[dep] >= order_index[target]:
                    removed.append({"from": dep, "to": target, "reason": "backward_dependency"})
                    continue
                candidate = list(normalized[target]) + [dep]
                normalized[target] = candidate
                if self._has_cycle(normalized):
                    normalized[target] = [x for x in normalized[target] if x != dep]
                    removed.append({"from": dep, "to": target, "reason": "cycle_prevention"})
        return normalized, removed

    def _has_cycle(self, graph: dict[str, list[str]]) -> bool:
        visiting: set[str] = set()
        visited: set[str] = set()
        def visit(node: str) -> bool:
            if node in visiting:
                return True
            if node in visited:
                return False
            visiting.add(node)
            for dep in graph.get(node) or []:
                if visit(dep):
                    return True
            visiting.remove(node)
            visited.add(node)
            return False
        return any(visit(node) for node in graph)

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
        return str(participant.get("name") or participant.get("participant_id") or participant.get("id") or "participant").strip()

    def _participant_objective(self, participant: dict[str, Any]) -> str:
        return str(participant.get("execution_objective") or participant.get("instruction") or participant.get("description") or "").strip()
