from __future__ import annotations
from typing import AsyncGenerator, Any
import json
import time

from ai_core.config.loader import ConfigLoader
from ai_core.config.paths import RUNTIME_CONFIGS_DIR, RUNTIME_TRACES_DIR
from ai_core.llm.model_router import ModelRouter
from ai_core.security.approval_service import ApprovalService
from ai_core.knowledge.knowledge_store import KnowledgeStore
from ai_core.utils.events import StreamEvent
from ai_core.orchestration.checkpoint_manager import CheckpointManager


class WorkflowEngine:
    """Generic workflow engine with real suspend/resume checkpoints.

    This engine contains no business-specific logic. It only knows how to:
    - load a configurable workflow
    - execute generic node types
    - stream events
    - pause on human review
    - persist checkpoint state
    - resume after approval
    """

    def __init__(self, approval: ApprovalService):
        self.loader = ConfigLoader()
        self.approval = approval
        self.router = ModelRouter(approval)
        self.knowledge = KnowledgeStore()
        self.checkpoints = CheckpointManager()

    def _workflow(self) -> dict:
        return self.loader.read(RUNTIME_CONFIGS_DIR / "workflows" / "base_orchestration.yaml", default={}) or {"nodes": []}

    async def run(self, user_input: str) -> AsyncGenerator[StreamEvent, None]:
        run_id = str(int(time.time() * 1000))
        workflow = self._workflow()
        state: dict[str, Any] = {"run_id": run_id, "user_input": user_input, "steps": []}
        yield StreamEvent("run_started", "Run started", "Starting configurable orchestration.", {"run_id": run_id})
        async for ev in self._execute(workflow, state, user_input, 0):
            yield ev

    async def resume(self, run_id: str, approved: bool = True, comment: str = "") -> AsyncGenerator[StreamEvent, None]:
        checkpoint = self.checkpoints.load(run_id)
        if not checkpoint:
            yield StreamEvent("error", "Checkpoint not found", f"No checkpoint found for run_id={run_id}.", {"run_id": run_id})
            return
        if not approved:
            self.checkpoints.mark_rejected(run_id, comment)
            yield StreamEvent("run_rejected", "Run rejected", comment or "Human rejected the checkpoint.", {"run_id": run_id})
            return
        workflow = checkpoint["workflow"]
        state = checkpoint["state"]
        user_input = checkpoint["user_input"]
        start_index = int(checkpoint["next_index"])
        yield StreamEvent("run_resumed", "Run resumed", f"Continuing from node index {start_index}.", {"run_id": run_id, "start_index": start_index})
        async for ev in self._execute(workflow, state, user_input, start_index):
            yield ev

    async def _execute(self, workflow: dict, state: dict[str, Any], user_input: str, start_index: int) -> AsyncGenerator[StreamEvent, None]:
        run_id = state["run_id"]
        nodes = workflow.get("nodes", [])
        for index in range(start_index, len(nodes)):
            node = nodes[index]
            node_id = node.get("id", f"node_{index}")
            yield StreamEvent("node_started", node_id, "Executing node.", {"node": node, "run_id": run_id})

            if node.get("type") == "llm_step":
                prompt = self._build_generic_prompt(node_id, state)
                async for ev in self.router.generate(node_id, prompt):
                    if ev.data is None:
                        ev.data = {}
                    ev.data.setdefault("run_id", run_id)
                    ev.data.setdefault("node_id", node_id)
                    yield ev
                    if ev.type == "model_output":
                        state[node_id] = ev.message
                    if ev.type == "human_review":
                        self._pause(run_id, workflow, state, user_input, index, ev)
                        return
                    if ev.type == "error":
                        # Try next provider inside router already happened. If still error, pause for human decision.
                        self._pause(run_id, workflow, state, user_input, index, ev, status="waiting_error_review")
                        yield StreamEvent("human_review", "Human review required", "Provider/model failed. Approve retry after fixing environment or modify runtime config.", {"run_id": run_id, "node_id": node_id})
                        return

                if node.get("review_required"):
                    payload = {"run_id": run_id, "node_id": node_id, "result": state.get(node_id, "")}
                    if not self.approval.is_approved("review_node_result", payload):
                        req = self.approval.create(
                            "review_node_result",
                            f"Review result for node '{node_id}' before continuing.",
                            payload,
                        )
                        ev = StreamEvent("human_review", "Human review required", req.message, {"approval_id": req.approval_id, "node_id": node_id, "run_id": run_id})
                        yield ev
                        self._pause(run_id, workflow, state, user_input, index + 1, ev)
                        return

            elif node.get("type") == "memory_step":
                yield StreamEvent("memory", node_id, "Loaded recent context and runtime knowledge index.", {"run_id": run_id})
                state[node_id] = "context_loaded"

            elif node.get("type") == "dynamic_execution":
                yield StreamEvent("execution", node_id, "Execution is configuration-driven. Runtime will use generated workflow/tool definitions when available.", {"run_id": run_id})
                payload = {"run_id": run_id, "node_id": node_id, "state_digest": self._safe_state_digest(state)}
                if not self.approval.is_approved("review_execution_plan", payload):
                    req = self.approval.create("review_execution_plan", "Approve execution phase plan before running generated tools.", payload)
                    ev = StreamEvent("human_review", "Human review required", req.message, {"approval_id": req.approval_id, "node_id": node_id, "run_id": run_id})
                    yield ev
                    self._pause(run_id, workflow, state, user_input, index + 1, ev)
                    return
                state[node_id] = "execution_plan_approved"

            elif node.get("type") == "learning_step":
                self.knowledge.save_case({"run_id": run_id, "input": user_input, "state": state})
                self.knowledge.append_finetune({"messages": [{"role": "user", "content": user_input}, {"role": "assistant", "content": json.dumps(state, ensure_ascii=False)}]})
                yield StreamEvent("learning", node_id, "Saved trace and learning sample.", {"run_id": run_id})

            elif node.get("type") == "output_step":
                final = self._final_output(state)
                yield StreamEvent("final", "Final Output", final, {"state": state, "run_id": run_id})

            state["steps"].append(node_id)
            yield StreamEvent("node_completed", node_id, "Node completed.", {"run_id": run_id})

        self._save_trace(run_id, state)
        self.checkpoints.mark_completed(run_id)
        yield StreamEvent("run_completed", "Run completed", "Workflow completed.", {"run_id": run_id})

    def _pause(self, run_id: str, workflow: dict, state: dict[str, Any], user_input: str, next_index: int, ev: StreamEvent, status: str = "waiting_human") -> None:
        self.checkpoints.save({
            "run_id": run_id,
            "user_input": user_input,
            "workflow": workflow,
            "state": state,
            "next_index": next_index,
            "status": status,
            "approval_event": ev.data or {},
            "updated_at": time.time(),
        })

    def _build_generic_prompt(self, node_id: str, state: dict) -> str:
        return (
            "You are a configurable AI runtime node.\n"
            "Do not invent tool results.\n"
            "Return structured JSON where possible.\n"
            "If information is missing, list missing fields clearly.\n"
            f"Node: {node_id}\n"
            f"Current state: {json.dumps(state, ensure_ascii=False)}\n"
        )

    def _safe_state_digest(self, state: dict[str, Any]) -> dict[str, Any]:
        return {"run_id": state.get("run_id"), "steps": state.get("steps", []), "known_keys": list(state.keys())}

    def _final_output(self, state: dict) -> str:
        parts = []
        for key in ["input_parsing", "intent_recognition", "context_awareness", "workflow_planning", "execution"]:
            if key in state:
                parts.append(f"[{key}]\n{state[key]}")
        return "\n\n".join(parts) if parts else "No final output was produced because the workflow is waiting for configuration, provider, or human review."

    def _save_trace(self, run_id: str, state: dict) -> None:
        RUNTIME_TRACES_DIR.mkdir(parents=True, exist_ok=True)
        (RUNTIME_TRACES_DIR / f"{run_id}.json").write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
