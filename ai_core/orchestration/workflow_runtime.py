import uuid
import inspect
from collections.abc import Callable
from typing import Dict, Any

from ai_core.config.loader import ConfigLoader
from ai_core.config.paths import RUNTIME_CONFIGS
from ai_core.events.event_bus import event_bus
from ai_core.runtime.bootstrap import RuntimeBootstrap
from ai_core.runtime.checkpoint_store import CheckpointStore
from ai_core.runtime.trace_writer import TraceWriter
from auxiliary_brain.capability_acquisition.implementation_planner import CapabilityResolver
from ai_core.nodes.node_runner import NodeRunner
from ai_core.nodes.node_config_loader import NodeConfigLoader
from ai_core.knowledge.knowledge_service import KnowledgeService
from ai_core.evolution.finetune_dataset_builder import FinetuneDatasetBuilder
from ai_core.evolution.runtime_learning import RuntimeLearningService
from ai_core.runtime.runtime_template_generator import RuntimeTemplateGenerator
from ai_core.validation.recoverable_validation_error import RecoverableValidationError
from ai_core.execution.continuation_engine import ContinuationEngine
from ai_core.workflow.workflow_state_merger import WorkflowStateMerger
from ai_core.runtime.modeling.feedback_escalator import FeedbackEscalator
from auxiliary_brain.runtime.observability.stage_observer import RuntimeStageObserver


class WorkflowRuntime:
    def __init__(self) -> None:
        self.bootstrap = RuntimeBootstrap()
        self.loader = ConfigLoader()
        self.checkpoints = CheckpointStore()
        self.trace = TraceWriter()
        self.capabilities = CapabilityResolver()
        self.node_runner = NodeRunner()
        self.node_loader = NodeConfigLoader()
        self.knowledge = KnowledgeService()
        self.dataset = FinetuneDatasetBuilder()
        self.runtime_learning = RuntimeLearningService()
        self.template_generator = RuntimeTemplateGenerator()
        self.correction_learning = RuntimeLearningService()
        self.continuation_engine = ContinuationEngine()
        self.workflow_state_merger = WorkflowStateMerger()
        self.model_feedback = FeedbackEscalator()
        self.stage_observer = RuntimeStageObserver()
        self._event_listeners: dict[str, list[Callable[[dict], Any]]] = {}

    def _load_workflow(self) -> Dict[str, Any]:
        return self.loader.load_yaml(RUNTIME_CONFIGS / "workflows" / "base_orchestration.yaml")

    def _progress(self, workflow: dict, idx: int) -> int:
        weights = []
        for n in workflow.get("nodes", []):
            try:
                weights.append(int(self.node_loader.load(n).get("progress_weight", 1)))
            except Exception:
                weights.append(1)
        total = sum(weights) or 1
        return int(sum(weights[:idx]) / total * 100)

    async def prepare(self, message: str, local_model: str | None = None) -> tuple[str, dict]:
        self.bootstrap.ensure()
        run_id = uuid.uuid4().hex[:12]
        state = {
            "run_id": run_id,
            "input": message,
            "workflow": self._load_workflow(),
            "node_index": 0,
            "results": {},
            "progress": 0,
            "node_attempts": {},
            "runtime_options": {
                "local_model": local_model or "qwen3.5:2b",
            },
        }
        await self._emit(run_id, {
            "type": "RUN_CREATED",
            "title": "Run created",
            "message": "Run id created. Event stream can connect now.",
            "progress": 0,
            "node_attempts": {},
            "runtime_options": {
                "local_model": local_model or "qwen3.5:2b",
            },
        })
        return run_id, state

    async def run_prepared(self, state: dict) -> None:
        run_id = state["run_id"]
        await self._emit(run_id, {
            "type": "RUN_STARTED",
            "title": "Run started",
            "message": "Starting config-driven node orchestration.",
            "progress": 0,
            "node_attempts": {},
            "runtime_options": state.get("runtime_options", {}),
        })
        await self._continue(state)

    async def start(self, message: str) -> str:
        run_id, state = await self.prepare(message)
        await self.run_prepared(state)
        return run_id

    async def resume(self, run_id: str, decision: str = "approve", modified_result: dict | None = None, feedback: str | None = None) -> None:
        state = self.checkpoints.load(run_id)
        if not state:
            await self._emit(run_id, {
                "type": "RUN_FAILED",
                "title": "Resume failed",
                "message": "Checkpoint not found."
            })
            return

        pending = state.get("pending_action", {})
        self.checkpoints.delete(run_id)

        if pending.get("kind") == "human_information_required":
            if decision not in {"approve", "modify"} or not modified_result:
                await self._emit(run_id, {
                    "type": "RUN_CANCELLED",
                    "title": "Human information cancelled",
                    "message": "Required information was not provided.",
                })
                return

            current_plan = state.get("results", {}).get("workflow_planning", {})
            merged_plan = self.workflow_state_merger.merge_human_information(
                current_plan,
                modified_result,
                interaction_request=pending.get("request"),
            )
            state.setdefault("results", {})["workflow_planning"] = merged_plan
            state.get("results", {}).pop(pending.get("node_id", ""), None)
            state.setdefault("human_information_history", []).append({
                "node_id": pending.get("node_id"),
                "provided": modified_result,
            })

            node_id = pending.get("node_id")
            if node_id:
                state["node_index"] = self._node_index_by_id(state.get("workflow", {}), node_id)

            await self._emit(run_id, {
                "type": "HUMAN_INFORMATION_MERGED",
                "title": "Human information merged",
                "message": "Merged provided values into workflow state and resuming execution.",
                "workflow_planning": merged_plan,
                "progress": state.get("progress", 0),
            })
            await self._continue(state)
            return

        if pending.get("kind") == "generated_capability_review":
            if decision == "reject":
                await self._emit(run_id, {
                    "type": "RUN_CANCELLED",
                    "title": "Generated capability rejected",
                    "message": feedback or "Generated capability request was rejected.",
                })
                return

            node_id = pending.get("node_id")
            retry_index = pending.get("retry_node_index")
            if retry_index is None and node_id:
                retry_index = self._node_index_by_id(state.get("workflow", {}), node_id)

            state.setdefault("approved_generation_requests", []).append({
                "node_id": node_id,
                "missing_tools": pending.get("missing_tools", []),
                "feedback": feedback or "",
            })

            # v50: approval of a generated capability review is not terminal.
            # It means the execution node may now reuse or execute the generated
            # registered module/tool. Remove the stale execution result and
            # dispatch the same node again immediately.
            if node_id:
                state.get("results", {}).pop(node_id, None)
                state["node_index"] = int(retry_index if retry_index is not None else self._node_index_by_id(state.get("workflow", {}), node_id))

            await self._emit(run_id, {
                "type": "GENERATION_REQUEST_APPROVED",
                "title": "Generation request approved",
                "message": "Approval recorded. Re-dispatching the blocked node to execute registered/generated runtime components.",
                "node_id": node_id,
                "missing_tools": pending.get("missing_tools", []),
                "progress": state.get("progress", 0),
            })
            await self._emit(run_id, {
                "type": "RESUME_REDISPATCH_STARTED",
                "title": "Resume redispatch started",
                "message": f"Re-running node={node_id} after generated capability approval.",
                "node_id": node_id,
                "progress": state.get("progress", 0),
            })
            await self._continue(state)
            return

        if pending.get("kind") == "human_confirmation_required":
            if decision != "approve":
                await self._emit(run_id, {
                    "type": "RUN_CANCELLED",
                    "title": "Human confirmation rejected",
                    "message": feedback or "Human confirmation was not granted.",
                })
                return
            state.setdefault("human_confirmations", []).append({
                "node_id": pending.get("node_id"),
                "safety_holds": pending.get("safety_holds", []),
                "feedback": feedback or "",
            })
            await self._emit(run_id, {
                "type": "HUMAN_CONFIRMATION_ACCEPTED",
                "title": "Human confirmation accepted",
                "message": "Confirmation recorded. Runtime can continue when executable implementation is available.",
                "progress": state.get("progress", 0),
            })
            await self._continue(state)
            return

        if pending.get("kind") == "optional_credential_choice":
            action = decision
            if modified_result and isinstance(modified_result, dict):
                action = str(modified_result.get("action") or modified_result.get("choice") or decision)

            node_id = pending.get("node_id")
            retry_index = pending.get("retry_node_index")
            if retry_index is None and node_id:
                retry_index = self._node_index_by_id(state.get("workflow", {}), node_id)

            if action in {"provide_credential", "approve"}:
                secret_value = None
                secret_key = "runtime_optional_credential"
                if modified_result and isinstance(modified_result, dict):
                    secret_value = modified_result.get("credential") or modified_result.get("api_key") or modified_result.get("value")
                    secret_key = str(modified_result.get("secret_key") or modified_result.get("provider") or secret_key)
                if not secret_value:
                    await self._emit(run_id, {
                        "type": "OPTIONAL_CREDENTIAL_INPUT_INVALID",
                        "title": "API key was not provided",
                        "message": "Please provide an API key or choose Continue without API key.",
                    })
                    self.checkpoints.save(run_id, state)
                    return
                from ai_core.secrets.secret_store import SecretStore
                SecretStore().set(secret_key, str(secret_value))
                state.setdefault("runtime_credentials", {})[secret_key] = "***"
                state.setdefault("runtime_execution_preferences", {})["credential_mode"] = "provided"
                await self._emit(run_id, {
                    "type": "OPTIONAL_CREDENTIAL_SAVED",
                    "title": "API key saved",
                    "message": "API key saved. Resuming workflow with the credential-protected candidate available.",
                    "progress": state.get("progress", 0),
                })
            else:
                state.setdefault("runtime_execution_preferences", {})["credential_mode"] = "skip"
                state.setdefault("runtime_execution_preferences", {})["skip_credential_candidates"] = True
                await self._emit(run_id, {
                    "type": "OPTIONAL_CREDENTIAL_SKIPPED",
                    "title": "Continuing without API key",
                    "message": "Credential-protected candidates were skipped. Runtime will continue with no-key or evidence-based methods when available.",
                    "progress": state.get("progress", 0),
                })

            if node_id:
                state.get("results", {}).pop(node_id, None)
                state["node_index"] = int(retry_index if retry_index is not None else self._node_index_by_id(state.get("workflow", {}), node_id))

            await self._continue(state)
            return

        if pending.get("kind") == "secret_input":
            modified = modified_result if isinstance(modified_result, dict) else {}
            action = str(modified.get("action") or modified.get("choice") or decision or "").strip().lower()
            skip_requested = bool(modified.get("skip_credential")) or action in {"skip", "skip_credential", "continue_without_key", "continue_without_credential"}
            node_id = pending.get("node_id")
            retry_index = pending.get("retry_node_index")
            if retry_index is None and node_id:
                retry_index = self._node_index_by_id(state.get("workflow", {}), node_id)

            if skip_requested or decision in {"skip", "continue"}:
                prefs = state.setdefault("runtime_execution_preferences", {})
                prefs["credential_mode"] = "skip"
                prefs["skip_credential_candidates"] = True
                secret_key = str(pending.get("secret_key") or modified.get("secret_key") or "runtime_access_key")
                prefs.setdefault("skipped_secret_keys", [])
                if secret_key not in prefs["skipped_secret_keys"]:
                    prefs["skipped_secret_keys"].append(secret_key)
                await self._emit(run_id, {
                    "type": "SECRET_SKIPPED",
                    "title": "Continuing without API key",
                    "message": "The credential-protected method was skipped. Runtime will continue with another allowed method when available.",
                    "progress": state.get("progress", 0),
                })
            else:
                if decision != "approve" or not modified_result:
                    await self._emit(run_id, {
                        "type": "RUN_CANCELLED",
                        "title": "Secret input cancelled",
                        "message": "API key was not provided.",
                    })
                    return

                from ai_core.secrets.secret_store import SecretStore
                secret_key = pending.get("secret_key") or modified.get("secret_key")
                secret_value = modified.get("value") or modified.get("credential") or modified.get("api_key")

                if not secret_key or not secret_value:
                    await self._emit(run_id, {
                        "type": "RUN_FAILED",
                        "title": "Secret input failed",
                        "message": "Missing secret key or value.",
                    })
                    return

                SecretStore().set(secret_key, secret_value)
                state.setdefault("runtime_credentials", {})[str(secret_key)] = "***"
                state.setdefault("runtime_execution_preferences", {})["credential_mode"] = "provided"

                await self._emit(run_id, {
                    "type": "SECRET_SAVED",
                    "title": "API key saved",
                    "message": f"{secret_key} saved to runtime config.",
                    "progress": state.get("progress", 0),
                })

            state.pop("pending_action", None)
            state.pop("missing_inputs", None)
            state.pop("waiting_input", None)
            state.pop("requires_key", None)
            if node_id:
                state.get("results", {}).pop(node_id, None)
                state["node_index"] = int(retry_index if retry_index is not None else self._node_index_by_id(state.get("workflow", {}), node_id))
            await self._continue(state)
            return

        if decision == "reject":
            node_id = pending.get("node_id")
            feedback_text = feedback or "Rejected by human."
            original_output = state.get("results", {}).get(node_id, {})
            executor_type = None

            if node_id:
                try:
                    workflow_node = state["workflow"]["nodes"][max(0, state.get("node_index", 1) - 1)]
                    node_config = self.node_loader.load(workflow_node)
                    executor_type = node_config.get("executor_type", "llm_json")
                except Exception:
                    executor_type = "llm_json"

            validation_error = pending.get("validation_error")
            combined_feedback = feedback_text
            if validation_error:
                combined_feedback = feedback_text + "\nValidation error:\n" + validation_error

            state.setdefault("human_feedback", []).append({
                "node_id": node_id,
                "feedback": combined_feedback,
                "original_output": original_output,
                "validation_error": validation_error,
            })

            if node_id:
                self.runtime_learning.record_reject_feedback(
                    run_id=run_id,
                    node_id=node_id,
                    user_input=state.get("input", ""),
                    original_output=original_output,
                    feedback=combined_feedback,
                )
                self.model_feedback.record_event(
                    node_id=node_id,
                    adapter={"runtime_role": executor_type or "llm_json"},
                    event={"kind": "dissatisfied", "feedback": combined_feedback},
                )

                evolution = self.template_generator.evolve_from_feedback(
                    node_id=node_id,
                    executor_type=executor_type or "llm_json",
                    feedback=combined_feedback,
                    original_output=original_output,
                    user_input=state.get("input", ""),
                )

                state["results"].pop(node_id, None)
            else:
                evolution = {}

            retry_index = pending.get("retry_node_index")
            if retry_index is None:
                retry_index = max(0, state.get("node_index", 1) - 1)
            state["node_index"] = int(retry_index)
            attempt_number = self._begin_retry_attempt(state, node_id) if node_id else 1

            await self._emit(run_id, {
                "type": "NODE_RETRY_STARTED",
                "title": "Retry started",
                "message": f"Retrying node={node_id} with human feedback.",
                "node_id": node_id,
                "attempt_number": attempt_number,
                "feedback": combined_feedback,
                "progress": state.get("progress", 0),
            })

            await self._emit(run_id, {
                "type": "RUNTIME_TEMPLATE_EVOLVED",
                "title": "Runtime template evolved",
                "message": f"Updated generated prompt/schema for node={node_id}. Changes: {evolution.get('changes', [])}",
                "node_id": node_id,
                "evolution": evolution,
                "progress": state.get("progress", 0),
            })

            await self._emit(run_id, {
                "type": "REJECTED_RETRY",
                "title": "Rejected. Retrying node",
                "message": combined_feedback,
                "node_id": node_id,
                "attempt_number": attempt_number,
                "progress": state.get("progress", 0)
            })
            await self._continue(state)
            return

        if decision == "modify":
            node_id = pending.get("node_id")
            if not node_id or modified_result is None:
                await self._emit(run_id, {
                    "type": "RUN_FAILED",
                    "title": "Modify failed",
                    "message": "Missing node_id or modified result."
                })
                return

            original_output = state.get("results", {}).get(node_id, {})

            self.runtime_learning.record_correction(
                run_id=run_id,
                node_id=node_id,
                user_input=state.get("input", ""),
                original_output=original_output,
                modified_output=modified_result,
                feedback=feedback,
            )

            await self._emit(run_id, {
                "type": "CORRECTION_RECORDED",
                "title": "Correction recorded",
                "message": "Saved to runtime/datasets/corrections.jsonl and prompt optimization memory.",
                "node_id": node_id,
            })

            state["results"][node_id] = modified_result
            state.setdefault("human_modifications", []).append({
                "node_id": node_id,
                "original_output": original_output,
                "modified_result": modified_result,
                "feedback": feedback or "",
            })

            await self._emit(run_id, {
                "type": "MODIFIED_CONTINUE",
                "title": "Modified result accepted",
                "message": f"Using human-modified result for {node_id}.",
                "progress": state.get("progress", 0)
            })
            await self._continue(state)
            return

        await self._emit(run_id, {
            "type": "APPROVED_CONTINUE",
            "title": "Approved",
            "message": "Continuing workflow.",
            "progress": state.get("progress", 0)
        })
        await self._continue(state)

    async def _continue(self, state: Dict[str, Any]) -> None:
        workflow = state["workflow"]
        nodes = workflow["nodes"]
        run_id = state["run_id"]

        while state["node_index"] < len(nodes):
            idx = state["node_index"]
            workflow_node = nodes[idx]
            node_id = workflow_node["id"]
            node_config = self.node_loader.load(workflow_node)
            attempt_number = self._attempt_number(state, node_id)
            progress = self._progress(workflow, idx)
            state["progress"] = progress

            await self._emit(run_id, {
                "type": "NODE_STARTED",
                "title": node_id,
                "node_id": node_id,
                "attempt_number": attempt_number,
                "message": f"Loading runtime node config: {workflow_node.get('node_config')}",
                "progress": progress
            })
            stage_started_at = __import__("time").perf_counter()
            self.stage_observer.emit(
                run_id=run_id,
                stage_id=node_id,
                area="workflow",
                event="node_started",
                status="running",
                message=f"node started: {node_id}",
                duration_ms=0,
                model_id=state.get("runtime_options", {}).get("local_model") if isinstance(state.get("runtime_options"), dict) else None,
                provider=None,
                metadata={"attempt_number": attempt_number, "executor_type": node_config.get("executor_type")},
            )

            ok, cap_result = await self.capabilities.ensure_capabilities(
                run_id,
                node_config,
                {
                    "input": state.get("input"),
                    "previous_results": state.get("results", {})
                }
            )

            if not ok:
                if cap_result.get("approval_required"):
                    auto_approve_reviews = bool(
                        state.get("runtime_options", {}).get("auto_approve_reviews")
                        or state.get("runtime_options", {}).get("delegation_mode")
                    )
                    pending_kind = cap_result.get("pending_kind")
                    if auto_approve_reviews and pending_kind not in {"secret_input", "optional_credential_choice", "human_information_required"}:
                        state.setdefault("approved_generation_requests", []).append({
                            "node_id": node_id,
                            "missing_tools": cap_result.get("missing_tools", []),
                            "feedback": "auto-approved by non-interactive delegated execution policy",
                        })
                        await self._emit(run_id, {
                            "type": "CAPABILITY_REVIEW_AUTO_APPROVED",
                            "title": "Capability review auto-approved",
                            "message": "Capability approval gate bypassed for delegated primary-runtime execution.",
                            "node_id": node_id,
                            "origin": "ai_core",
                            "progress": progress,
                        })
                    else:
                        state["pending_action"] = {
                            "kind": pending_kind,
                            "node_id": node_id,
                            "spec": cap_result.get("spec"),
                            "request": cap_result.get("request"),
                            "message": cap_result.get("message"),
                        }
                        self.checkpoints.save(run_id, state)
                        await self._emit(run_id, {
                            "type": "HUMAN_REVIEW",
                            "title": "Capability approval required",
                            "message": cap_result.get("message"),
                            "spec": cap_result.get("spec"),
                            "run_id": run_id,
                            "progress": progress
                        })
                        return

                else:
                    state["status"] = "failed"
                    state["error"] = str(cap_result.get("message", ""))
                    state.setdefault("results", {})[node_id] = {
                        "status": "failed",
                        "message": state["error"],
                    }
                    await self._emit(run_id, {
                        "type": "RUN_FAILED",
                        "title": "Capability unavailable",
                        "message": cap_result.get("message", "")
                    })
                    return

            await self._emit(run_id, {
                "type": "NODE_EXECUTING",
                "title": node_id,
                "node_id": node_id,
                "attempt_number": attempt_number,
                "message": f"Capability ready. Dispatching to executor_type={node_config.get('executor_type')}.",
                "progress": progress
            })

            try:
                result = await self.node_runner.run(workflow_node, state, cap_result)
            except RecoverableValidationError as exc:
                state["results"][node_id] = exc.result
                state["pending_action"] = {
                    "kind": "validation_recovery",
                    "node_id": node_id,
                    "validation_error": exc.message,
                    "schema_path": exc.schema_path,
                    "retry_node_index": idx,
                }
                self.checkpoints.save(run_id, state)
                await self._emit(run_id, {
                    "type": "VALIDATION_RECOVERY_REQUIRED",
                    "title": "Validation failed. Human recovery required",
                    "message": f"{node_id}: {exc.message}",
                    "node_id": node_id,
                    "attempt_number": attempt_number,
                    "result": exc.result,
                    "schema_path": exc.schema_path,
                    "run_id": run_id,
                    "progress": progress,
                })
                await self._emit(run_id, {
                    "type": "HUMAN_REVIEW",
                    "title": "Validation recovery",
                    "node_id": node_id,
                    "attempt_number": attempt_number,
                    "message": (
                        f"Node '{node_id}' produced JSON but schema validation failed. "
                        "Reject & Retry to evolve prompt/schema, or Modify JSON & Continue."
                    ),
                    "result": exc.result,
                    "validation_error": exc.message,
                    "run_id": run_id,
                    "progress": progress,
                })
                return
            except Exception as exc:
                message = str(exc)
                if "MISSING_SECRET:" in message:
                    secret_key = message.split("MISSING_SECRET:", 1)[1].split()[0].strip()
                    state["pending_action"] = {
                        "kind": "secret_input",
                        "node_id": node_id,
                        "attempt_number": attempt_number,
                        "secret_key": secret_key,
                    "retry_node_index": idx,
                    }
                    self.checkpoints.save(run_id, state)
                    await self._emit(run_id, {
                        "type": "SECRET_REQUIRED",
                        "title": "API key required",
                        "message": f"Please input {secret_key}. It will be saved to runtime/configs/secrets/secrets.json.",
                        "secret_key": secret_key,
                        "run_id": run_id,
                        "progress": progress,
                    })
                    return

                state["status"] = "failed"
                state["error"] = f"{node_id}: {exc}"
                state.setdefault("results", {})[node_id] = {
                    "status": "failed",
                    "message": state["error"],
                }
                await self._emit(run_id, {
                    "type": "RUN_FAILED",
                    "title": "Node execution failed",
                    "message": f"{node_id}: {exc}",
                    "progress": progress,
                })
                return

            state["results"][node_id] = result

            # v5.0: validation failure is not allowed to flow into execution.
            # The runtime loops back to workflow_planning/execution_preparation
            # with generic repair hints until validation passes or retry budget is
            # exhausted. This keeps execution deterministic and prevents delivery
            # from exposing earlier stage messages as final answers.
            if node_id == "pre_execution_validation" and isinstance(result, dict):
                record = result.get("validation_record") if isinstance(result.get("validation_record"), dict) else result
                validation_needs_runtime_input = bool(result.get("human_interactions") or record.get("human_interactions"))
                if record.get("status") != "passed" and not validation_needs_runtime_input:
                    repair_count = int(state.setdefault("repair_attempts", {}).get("pre_execution_validation", 0) or 0)
                    if repair_count < 3:
                        state["repair_attempts"]["pre_execution_validation"] = repair_count + 1
                        state.setdefault("repair_hints", []).append({
                            "from_stage": "pre_execution_validation",
                            "retry_from": "workflow_planning",
                            "reason": "validation_failed",
                            "validation_record": record,
                        })
                        for stale in ("execution_preparation", "pre_execution_validation", "execution", "result_verification", "feedback_repair", "final_synthesis", "output"):
                            state.get("results", {}).pop(stale, None)
                        state["node_index"] = self._node_index_by_id(workflow, "workflow_planning")
                        await self._emit(run_id, {
                            "type": "VALIDATION_REPAIR_LOOP",
                            "title": "Validation repair loop",
                            "node_id": node_id,
                            "attempt_number": repair_count + 1,
                            "message": "Pre-execution validation failed. Re-running workflow planning and preparation with repair hints.",
                            "validation_record": record,
                            "progress": progress,
                        })
                        continue
                    state["status"] = "blocked"
                    state["node_index"] += 1
                else:
                    state["node_index"] += 1
            else:
                state["node_index"] += 1
            done = self._progress(workflow, state["node_index"])
            state["progress"] = done

            elapsed_ms = int((__import__("time").perf_counter() - stage_started_at) * 1000)
            self.stage_observer.emit(
                run_id=run_id,
                stage_id=node_id,
                area="workflow",
                event="node_completed",
                status="completed",
                message=f"node completed: {node_id}",
                duration_ms=elapsed_ms,
                model_id=result.get("_model_id") if isinstance(result, dict) else None,
                provider=result.get("_provider") if isinstance(result, dict) else None,
                prompt_trace_path=result.get("_prompt_trace_path") if isinstance(result, dict) else None,
                output_trace_path=result.get("_output_trace_path") if isinstance(result, dict) else None,
                metadata={"attempt_number": attempt_number, "executor_type": node_config.get("executor_type")},
            )

            await self._emit(run_id, {
                "type": "NODE_RESULT",
                "title": f"{node_id} result",
                "node_id": node_id,
                "attempt_number": attempt_number,
                "message": "Node executed by generic executor.",
                "result": result,
                "duration_ms": elapsed_ms,
                "progress": done
            })

            continuation_action = self.continuation_engine.build_pending_action(node_id, result, state)
            if continuation_action:
                continuation_action.setdefault("node_id", node_id)
                continuation_action.setdefault("retry_node_index", idx)
                auto_approve_reviews = bool(
                    state.get("runtime_options", {}).get("auto_approve_reviews")
                    or state.get("runtime_options", {}).get("delegation_mode")
                )
                action_kind = continuation_action.get("kind")

                if auto_approve_reviews and action_kind == "generated_capability_review":
                    state.setdefault("approved_generation_requests", []).append({
                        "node_id": node_id,
                        "missing_tools": continuation_action.get("missing_tools", []),
                        "feedback": "auto-approved by non-interactive delegated execution policy",
                    })
                    state.get("results", {}).pop(node_id, None)
                    state["node_index"] = int(continuation_action.get("retry_node_index", idx))
                    await self._emit(run_id, {
                        "type": "GENERATION_REQUEST_AUTO_APPROVED",
                        "title": "Generated capability request auto-approved",
                        "node_id": node_id,
                        "attempt_number": attempt_number,
                        "message": "Generated capability review was auto-approved for delegated primary-runtime execution.",
                        "missing_tools": continuation_action.get("missing_tools", []),
                        "origin": "ai_core",
                        "progress": done,
                    })
                    continue

                if auto_approve_reviews and action_kind == "human_confirmation_required":
                    state.setdefault("human_confirmations", []).append({
                        "node_id": node_id,
                        "safety_holds": continuation_action.get("safety_holds", []),
                        "feedback": "auto-confirmed by non-interactive delegated execution policy",
                    })
                    await self._emit(run_id, {
                        "type": "HUMAN_CONFIRMATION_AUTO_APPROVED",
                        "title": "Human confirmation auto-approved",
                        "node_id": node_id,
                        "attempt_number": attempt_number,
                        "message": "Confirmation gate bypassed for delegated primary-runtime execution.",
                        "origin": "ai_core",
                        "progress": done,
                    })
                    continue

                state["pending_action"] = continuation_action
                request_fields = []
                request_payload = continuation_action.get("request") if isinstance(continuation_action.get("request"), dict) else {}
                if isinstance(request_payload.get("fields"), list):
                    request_fields = request_payload.get("fields") or []
                state["missing_inputs"] = request_fields
                self.checkpoints.save(run_id, state)

                if action_kind in {"collect_runtime_parameters", "runtime_parameter_input", "uploaded_artifact_parameters"}:
                    await self._emit(run_id, {
                        "type": "HUMAN_INPUT_REQUIRED",
                        "title": "Runtime input required",
                        "node_id": node_id,
                        "attempt_number": attempt_number,
                        "message": continuation_action.get("request", {}).get("message") or continuation_action.get("message"),
                        "request": continuation_action.get("request"),
                        "run_id": run_id,
                        "progress": done,
                    })
                    await self._emit(run_id, {
                        "type": "RUN_PAUSED",
                        "workflow_state": "waiting_runtime_parameters",
                        "title": "Workflow paused for runtime input",
                        "node_id": node_id,
                        "message": continuation_action.get("message") or "Runtime input is required before execution can continue.",
                        "run_id": run_id,
                        "progress": done,
                    })
                    return

                if action_kind == "human_information_required":
                    await self._emit(run_id, {
                        "type": "HUMAN_INPUT_REQUIRED",
                        "title": "Additional information required",
                        "node_id": node_id,
                        "attempt_number": attempt_number,
                        "message": continuation_action.get("request", {}).get("message"),
                        "request": continuation_action.get("request"),
                        "run_id": run_id,
                        "progress": done,
                    })
                    return

                if action_kind == "generated_capability_review":
                    await self._emit(run_id, {
                        "type": "CAPABILITY_GENERATION_REQUESTED",
                        "title": "Missing capability request generated",
                        "node_id": node_id,
                        "attempt_number": attempt_number,
                        "message": continuation_action.get("message"),
                        "missing_tools": continuation_action.get("missing_tools", []),
                        "run_id": run_id,
                        "progress": done,
                    })
                    await self._emit(run_id, {
                        "type": "HUMAN_REVIEW",
                        "title": "Review generated tool/module request",
                        "node_id": node_id,
                        "attempt_number": attempt_number,
                        "message": "Review the generated request before implementation and registration.",
                        "result": result,
                        "run_id": run_id,
                        "progress": done,
                    })
                    return

                if action_kind == "human_confirmation_required":
                    await self._emit(run_id, {
                        "type": "HUMAN_REVIEW",
                        "title": "Human confirmation required",
                        "node_id": node_id,
                        "attempt_number": attempt_number,
                        "message": continuation_action.get("message"),
                        "result": result,
                        "run_id": run_id,
                        "progress": done,
                    })
                    return

                if action_kind == "optional_credential_choice":
                    request = continuation_action.get("request") or {}
                    await self._emit(run_id, {
                        "type": "INTERACTION_REQUEST",
                        "interaction_type": "optional_credential_choice",
                        "workflow_state": "waiting_optional_credential_choice",
                        "title": request.get("title") or "Optional API Key Available",
                        "node_id": node_id,
                        "attempt_number": attempt_number,
                        "message": request.get("message") or "A credential-protected provider may improve the result. You can provide an API key or continue without it.",
                        "request": request,
                        "result": result,
                        "run_id": run_id,
                        "progress": done,
                    })
                    await self._emit(run_id, {
                        "type": "RUN_PAUSED",
                        "workflow_state": "waiting_optional_credential_choice",
                        "title": "Workflow paused for optional API key choice",
                        "node_id": node_id,
                        "message": "Please choose whether to continue without an API key or provide one.",
                        "run_id": run_id,
                        "progress": done,
                    })
                    return

            auto_approve_reviews = bool(
                state.get("runtime_options", {}).get("auto_approve_reviews")
                or state.get("runtime_options", {}).get("delegation_mode")
            )
            if node_config.get("review_required") and not auto_approve_reviews:
                state["pending_action"] = {
                    "kind": "node_review",
                    "node_id": node_id,
                    "retry_node_index": idx
                }
                self.checkpoints.save(run_id, state)
                await self._emit(run_id, {
                    "type": "HUMAN_REVIEW",
                    "title": "Human review required",
                    "node_id": node_id,
                    "attempt_number": attempt_number,
                    "message": f"Review result for node '{node_id}'. Approve, reject, or modify JSON.",
                    "result": result,
                    "run_id": run_id,
                    "progress": done
                })
                return

            if node_config.get("review_required") and auto_approve_reviews:
                await self._emit(run_id, {
                    "type": "NODE_REVIEW_AUTO_APPROVED",
                    "title": "Node review auto-approved",
                    "node_id": node_id,
                    "attempt_number": attempt_number,
                    "message": "Review gate bypassed for delegated primary-runtime execution.",
                    "progress": done,
                    "origin": "ai_core",
                })

        state["status"] = "completed"
        self.knowledge.save_success_case(run_id, state["results"])
        output_result = state.get("results", {}).get("output", {}) if isinstance(state.get("results", {}).get("output"), dict) else {}
        final_message = output_result.get("final_answer") or output_result.get("message") or "Workflow completed."
        self.dataset.append_case(
            state.get("input", ""),
            str(final_message),
            {
                "run_id": run_id,
                "results": state["results"]
            }
        )

        await self._emit(run_id, {
            "type": "RUN_COMPLETED",
            "title": "Final output",
            "message": str(final_message),
            "results": state["results"],
            "final_status": output_result.get("status", "completed"),
            "progress": 100
        })


    def _attempt_number(self, state: dict, node_id: str) -> int:
        attempts = state.setdefault("node_attempts", {})
        try:
            return int(attempts.get(node_id, 1) or 1)
        except Exception:
            return 1

    def _begin_retry_attempt(self, state: dict, node_id: str) -> int:
        attempts = state.setdefault("node_attempts", {})
        current = self._attempt_number(state, node_id)
        next_attempt = current + 1
        attempts[node_id] = next_attempt
        return next_attempt

    def _node_index_by_id(self, workflow: dict, node_id: str) -> int:
        for index, node in enumerate(workflow.get("nodes", []) or []):
            if node.get("id") == node_id:
                return index
        return max(0, int(workflow.get("node_index", 0) or 0))

    def add_event_listener(self, run_id: str, listener: Callable[[dict], Any]) -> None:
        self._event_listeners.setdefault(run_id, []).append(listener)

    def remove_event_listener(self, run_id: str, listener: Callable[[dict], Any]) -> None:
        listeners = self._event_listeners.get(run_id, [])
        if listener in listeners:
            listeners.remove(listener)
        if not listeners and run_id in self._event_listeners:
            self._event_listeners.pop(run_id, None)

    async def _emit(self, run_id: str, event: dict) -> None:
        self.trace.write(run_id, event)
        enriched = dict(event)
        enriched.setdefault("run_id", run_id)
        enriched.setdefault("origin", "ai_core")
        for listener in list(self._event_listeners.get(run_id, [])):
            try:
                result = listener(enriched)
                if inspect.isawaitable(result):
                    await result
            except Exception:
                pass
        await event_bus.emit(run_id, event)
