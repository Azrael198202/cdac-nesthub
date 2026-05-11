import uuid
from typing import Dict, Any

from ai_core.config.loader import ConfigLoader
from ai_core.config.paths import RUNTIME_CONFIGS
from ai_core.events.event_bus import event_bus
from ai_core.runtime.bootstrap import RuntimeBootstrap
from ai_core.runtime.checkpoint_store import CheckpointStore
from ai_core.runtime.trace_writer import TraceWriter
from ai_core.capabilities.capability_resolver import CapabilityResolver
from ai_core.nodes.node_runner import NodeRunner
from ai_core.nodes.node_config_loader import NodeConfigLoader
from ai_core.knowledge.knowledge_service import KnowledgeService
from ai_core.evolution.finetune_dataset_builder import FinetuneDatasetBuilder
from ai_core.evolution.correction_learning import CorrectionLearningService


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
        self.correction_learning = CorrectionLearningService()

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

    async def prepare(self, message: str) -> tuple[str, dict]:
        self.bootstrap.ensure()
        run_id = uuid.uuid4().hex[:12]
        state = {
            "run_id": run_id,
            "input": message,
            "workflow": self._load_workflow(),
            "node_index": 0,
            "results": {},
            "progress": 0,
        }
        await self._emit(run_id, {
            "type": "RUN_CREATED",
            "title": "Run created",
            "message": "Run id created. Event stream can connect now.",
            "progress": 0,
        })
        return run_id, state

    async def run_prepared(self, state: dict) -> None:
        run_id = state["run_id"]
        await self._emit(run_id, {
            "type": "RUN_STARTED",
            "title": "Run started",
            "message": "Starting config-driven node orchestration.",
            "progress": 0,
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

        if pending.get("kind") == "secret_input":
            if decision != "approve" or not modified_result:
                await self._emit(run_id, {
                    "type": "RUN_CANCELLED",
                    "title": "Secret input cancelled",
                    "message": "API key was not provided.",
                })
                return

            from ai_core.secrets.secret_store import SecretStore
            secret_key = pending.get("secret_key")
            secret_value = modified_result.get("value")

            if not secret_key or not secret_value:
                await self._emit(run_id, {
                    "type": "RUN_FAILED",
                    "title": "Secret input failed",
                    "message": "Missing secret key or value.",
                })
                return

            SecretStore().set(secret_key, secret_value)

            await self._emit(run_id, {
                "type": "SECRET_SAVED",
                "title": "API key saved",
                "message": f"{secret_key} saved to runtime config.",
                "progress": state.get("progress", 0),
            })

            await self._continue(state)
            return

        if decision == "reject":
            node_id = pending.get("node_id")
            state.setdefault("human_feedback", []).append({
                "node_id": node_id,
                "feedback": feedback or "Rejected by human."
            })
            if node_id:
                state["results"].pop(node_id, None)
            state["node_index"] = max(0, state.get("node_index", 1) - 1)

            await self._emit(run_id, {
                "type": "REJECTED_RETRY",
                "title": "Rejected. Retrying node",
                "message": feedback or "No reason provided.",
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

            self.correction_learning.record_correction(
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
            progress = self._progress(workflow, idx)
            state["progress"] = progress

            await self._emit(run_id, {
                "type": "NODE_STARTED",
                "title": node_id,
                "message": f"Loading runtime node config: {workflow_node.get('node_config')}",
                "progress": progress
            })

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
                    state["pending_action"] = {
                        "kind": cap_result.get("pending_kind"),
                        "node_id": node_id,
                        "spec": cap_result.get("spec")
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

                await self._emit(run_id, {
                    "type": "RUN_FAILED",
                    "title": "Capability unavailable",
                    "message": cap_result.get("message", "")
                })
                return

            await self._emit(run_id, {
                "type": "NODE_EXECUTING",
                "title": node_id,
                "message": f"Capability ready. Dispatching to executor_type={node_config.get('executor_type')}.",
                "progress": progress
            })

            try:
                result = await self.node_runner.run(workflow_node, state, cap_result)
            except Exception as exc:
                message = str(exc)
                if "MISSING_SECRET:" in message:
                    secret_key = message.split("MISSING_SECRET:", 1)[1].split()[0].strip()
                    state["pending_action"] = {
                        "kind": "secret_input",
                        "node_id": node_id,
                        "secret_key": secret_key,
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

                await self._emit(run_id, {
                    "type": "RUN_FAILED",
                    "title": "Node execution failed",
                    "message": f"{node_id}: {exc}",
                    "progress": progress,
                })
                return

            state["results"][node_id] = result
            state["node_index"] += 1
            done = self._progress(workflow, state["node_index"])
            state["progress"] = done

            await self._emit(run_id, {
                "type": "NODE_RESULT",
                "title": f"{node_id} result",
                "message": "Node executed by generic executor.",
                "result": result,
                "progress": done
            })

            if node_config.get("review_required"):
                state["pending_action"] = {
                    "kind": "node_review",
                    "node_id": node_id
                }
                self.checkpoints.save(run_id, state)
                await self._emit(run_id, {
                    "type": "HUMAN_REVIEW",
                    "title": "Human review required",
                    "message": f"Review result for node '{node_id}'. Approve, reject, or modify JSON.",
                    "result": result,
                    "run_id": run_id,
                    "progress": done
                })
                return

        self.knowledge.save_success_case(run_id, state["results"])
        self.dataset.append_case(
            state.get("input", ""),
            "Workflow completed.",
            {
                "run_id": run_id,
                "results": state["results"]
            }
        )

        await self._emit(run_id, {
            "type": "RUN_COMPLETED",
            "title": "Final output",
            "message": "Workflow completed. Results were saved to runtime knowledge and finetune dataset.",
            "results": state["results"],
            "progress": 100
        })

    async def _emit(self, run_id: str, event: dict) -> None:
        self.trace.write(run_id, event)
        await event_bus.emit(run_id, event)
