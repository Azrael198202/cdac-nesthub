from __future__ import annotations
from typing import AsyncGenerator
import json
import time

from ai_core.config.loader import ConfigLoader
from ai_core.config.paths import RUNTIME_CONFIGS_DIR, RUNTIME_TRACES_DIR
from ai_core.llm.model_router import ModelRouter
from ai_core.security.approval_service import ApprovalService
from ai_core.knowledge.knowledge_store import KnowledgeStore
from ai_core.utils.events import StreamEvent


class WorkflowEngine:
    """Generic workflow engine. No business-specific code."""

    def __init__(self, approval: ApprovalService):
        self.loader = ConfigLoader()
        self.approval = approval
        self.router = ModelRouter(approval)
        self.knowledge = KnowledgeStore()

    def _workflow(self) -> dict:
        return self.loader.read(RUNTIME_CONFIGS_DIR / "workflows" / "base_orchestration.yaml", default={}) or {"nodes": []}

    async def run(self, user_input: str) -> AsyncGenerator[StreamEvent, None]:
        run_id = str(int(time.time() * 1000))
        state: dict = {"run_id": run_id, "user_input": user_input, "steps": []}
        workflow = self._workflow()
        yield StreamEvent("run_started", "Run started", "Starting configurable orchestration.", {"run_id": run_id})

        for node in workflow.get("nodes", []):
            node_id = node.get("id")
            yield StreamEvent("node_started", node_id, "Executing node.", {"node": node})
            if node.get("type") == "llm_step":
                prompt = self._build_generic_prompt(node_id, state)
                async for ev in self.router.generate(node_id, prompt):
                    yield ev
                    if ev.type == "model_output":
                        state[node_id] = ev.message
                if node.get("review_required"):
                    req = self.approval.create(
                        "review_node_result",
                        f"Review result for node '{node_id}' before continuing.",
                        {"run_id": run_id, "node_id": node_id, "result": state.get(node_id, "")},
                    )
                    yield StreamEvent("human_review", "Human review required", req.message, {"approval_id": req.approval_id, "node_id": node_id})
                    return
            elif node.get("type") == "memory_step":
                yield StreamEvent("memory", node_id, "Loaded recent context and runtime knowledge index.")
                state[node_id] = "context_loaded"
            elif node.get("type") == "dynamic_execution":
                yield StreamEvent("execution", node_id, "Execution is configuration-driven. Waiting for generated workflow/tool definitions if required.")
                req = self.approval.create("review_execution_plan", "Approve execution phase plan before running generated tools.", {"run_id": run_id, "state": state})
                yield StreamEvent("human_review", "Human review required", req.message, {"approval_id": req.approval_id, "node_id": node_id})
                return
            elif node.get("type") == "learning_step":
                self.knowledge.save_case({"run_id": run_id, "input": user_input, "state": state})
                self.knowledge.append_finetune({"messages": [{"role": "user", "content": user_input}, {"role": "assistant", "content": json.dumps(state, ensure_ascii=False)}]})
                yield StreamEvent("learning", node_id, "Saved trace and learning sample.")
            elif node.get("type") == "output_step":
                final = self._final_output(state)
                yield StreamEvent("final", "Final Output", final, {"state": state})
            state["steps"].append(node_id)
            yield StreamEvent("node_completed", node_id, "Node completed.")

        self._save_trace(run_id, state)
        yield StreamEvent("run_completed", "Run completed", "Workflow completed.", {"run_id": run_id})

    def _build_generic_prompt(self, node_id: str, state: dict) -> str:
        return (
            "You are a configurable AI runtime node.\n"
            "Do not invent tool results.\n"
            "Return structured JSON where possible.\n"
            f"Node: {node_id}\n"
            f"Current state: {json.dumps(state, ensure_ascii=False)}\n"
        )

    def _final_output(self, state: dict) -> str:
        parts = []
        for key in ["input_parsing", "intent_recognition", "workflow_planning"]:
            if key in state:
                parts.append(f"[{key}]\n{state[key]}")
        return "\n\n".join(parts) if parts else "No final output was produced because the workflow is waiting for configuration, provider, or human review."

    def _save_trace(self, run_id: str, state: dict) -> None:
        RUNTIME_TRACES_DIR.mkdir(parents=True, exist_ok=True)
        (RUNTIME_TRACES_DIR / f"{run_id}.json").write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
