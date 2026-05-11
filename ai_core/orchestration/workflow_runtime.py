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
from ai_core.knowledge.knowledge_service import KnowledgeService
from ai_core.evolution.finetune_dataset_builder import FinetuneDatasetBuilder


class WorkflowRuntime:
    def __init__(self) -> None:
        self.bootstrap = RuntimeBootstrap()
        self.loader = ConfigLoader()
        self.checkpoints = CheckpointStore()
        self.trace = TraceWriter()
        self.capabilities = CapabilityResolver()
        self.node_runner = NodeRunner()
        self.knowledge = KnowledgeService()
        self.dataset = FinetuneDatasetBuilder()

    def _load_workflow(self) -> Dict[str, Any]:
        return self.loader.load_yaml(RUNTIME_CONFIGS / "workflows" / "base_orchestration.yaml")

    def _progress(self, workflow: dict, idx: int) -> int:
        nodes = workflow.get("nodes", [])
        total = sum(int(n.get("progress_weight", 1)) for n in nodes) or 1
        done = sum(int(n.get("progress_weight", 1)) for n in nodes[:idx])
        return int(done / total * 100)

    async def start(self, message: str) -> str:
        self.bootstrap.ensure()
        run_id = uuid.uuid4().hex[:12]
        state = {"run_id": run_id, "input": message, "workflow": self._load_workflow(), "node_index": 0, "results": {}, "review_payload": None, "progress": 0}
        await self._emit(run_id, {"type": "RUN_STARTED", "title": "Run started", "message": "Starting dynamic capability orchestration.", "progress": 0})
        await self._continue(state)
        return run_id

    async def resume(self, run_id: str, decision: str = "approve", modified_result: dict | None = None, feedback: str | None = None) -> None:
        state = self.checkpoints.load(run_id)
        if not state:
            await self._emit(run_id, {"type": "RUN_FAILED", "title": "Resume failed", "message": "Checkpoint not found."})
            return

        pending = state.get("pending_action", {})
        self.checkpoints.delete(run_id)

        if decision == "reject":
            node_id = pending.get("node_id")
            state.setdefault("human_feedback", []).append({"node_id": node_id, "feedback": feedback or "Rejected by human."})
            if node_id:
                state["results"].pop(node_id, None)
            state["node_index"] = max(0, state.get("node_index", 1) - 1)
            await self._emit(run_id, {"type": "REJECTED_RETRY", "title": "Rejected. Retrying node", "message": feedback or "No reason provided.", "progress": state.get("progress", 0)})
            await self._continue(state)
            return

        if decision == "modify":
            node_id = pending.get("node_id")
            if not node_id or modified_result is None:
                await self._emit(run_id, {"type": "RUN_FAILED", "title": "Modify failed", "message": "Missing node_id or modified result."})
                return
            state["results"][node_id] = modified_result
            state.setdefault("human_modifications", []).append({"node_id": node_id, "modified_result": modified_result})
            await self._emit(run_id, {"type": "MODIFIED_CONTINUE", "title": "Modified result accepted", "message": f"Using human-modified result for {node_id}.", "progress": state.get("progress", 0)})
            await self._continue(state)
            return

        await self._emit(run_id, {"type": "APPROVED_CONTINUE", "title": "Approved", "message": "Continuing workflow.", "progress": state.get("progress", 0)})
        await self._continue(state)

    async def _continue(self, state: Dict[str, Any]) -> None:
        workflow = state["workflow"]
        nodes = workflow["nodes"]
        run_id = state["run_id"]

        while state["node_index"] < len(nodes):
            idx = state["node_index"]
            node = nodes[idx]
            node_id = node["id"]
            state["progress"] = self._progress(workflow, idx)

            await self._emit(run_id, {"type": "NODE_STARTED", "title": node_id, "message": f"Stage: {node.get('type')} - preparing capability.", "progress": state["progress"]})

            ok, cap = await self.capabilities.ensure_for_node(run_id, node_id, {"input": state.get("input"), "node": node, "previous_results": state.get("results", {})})
            if not ok:
                if cap.get("approval_required"):
                    state["pending_action"] = {"kind": cap.get("pending_kind", "capability_review"), "node_id": node_id, "spec": cap.get("spec")}
                    self.checkpoints.save(run_id, state)
                    await self._emit(run_id, {"type": "HUMAN_REVIEW", "title": "Capability approval required", "message": cap.get("message"), "spec": cap.get("spec"), "run_id": run_id, "progress": state["progress"]})
                    return
                await self._emit(run_id, {"type": "RUN_FAILED", "title": "Capability unavailable", "message": cap.get("message", "")})
                return

            await self._emit(run_id, {"type": "NODE_EXECUTING", "title": node_id, "message": "Capability is ready. Now executing the node logic.", "progress": state["progress"]})
            result = await self.node_runner.run(node, state, cap)
            state["results"][node_id] = result

            done_progress = self._progress(workflow, idx + 1)
            await self._emit(run_id, {"type": "NODE_RESULT", "title": f"{node_id} result", "message": "Node execution completed.", "result": result, "progress": done_progress})

            state["node_index"] += 1
            state["progress"] = done_progress

            if node.get("review_required"):
                state["pending_action"] = {"kind": "node_review", "node_id": node_id}
                self.checkpoints.save(run_id, state)
                await self._emit(run_id, {"type": "HUMAN_REVIEW", "title": "Human review required", "message": f"Review the result for node '{node_id}'. Approve, reject with reason, or modify JSON.", "result": result, "run_id": run_id, "progress": done_progress})
                return

        self.knowledge.save_success_case(run_id, state["results"])
        self.dataset.append_case(state.get("input", ""), "Workflow completed.", {"run_id": run_id, "results": state["results"]})
        await self._emit(run_id, {"type": "RUN_COMPLETED", "title": "Final output", "message": "Workflow completed. Results were saved to runtime knowledge and finetune dataset.", "results": state["results"], "progress": 100})

    async def _emit(self, run_id: str, event: dict) -> None:
        self.trace.write(run_id, event)
        await event_bus.emit(run_id, event)
