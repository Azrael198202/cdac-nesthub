from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, AsyncGenerator

from ai_core.llm.model_router import ModelRouter
from ai_core.runtime.runtime_config import RuntimeConfig
from ai_core.knowledge.knowledge_service import KnowledgeService
from ai_core.security.approval_service import ApprovalService
from ai_core.tools.dynamic_tool_executor import DynamicToolExecutor
from ai_core.orchestration.events import WorkflowEvent


class NodeExecutor:
    def __init__(self) -> None:
        self.config = RuntimeConfig()
        self.router = ModelRouter()
        self.knowledge = KnowledgeService()
        self.approval = ApprovalService()
        self.tools = DynamicToolExecutor()

    async def execute(self, node: dict[str, Any], state: dict[str, Any]) -> AsyncGenerator[WorkflowEvent, None]:
        node_id = node.get("id", "unknown")
        node_type = node.get("type", "unknown")
        yield WorkflowEvent("node_start", node_id, f"Starting {node_type}")

        if node_type == "knowledge_lookup":
            hits = self.knowledge.search(state.get("user_input", ""))
            state.setdefault("knowledge_hits", {})[node_id] = hits
            yield WorkflowEvent("knowledge", "Knowledge lookup", f"Found {len(hits)} related records", "completed", hits)
            return

        if node_type == "llm_json":
            prompt_name = node.get("prompt", "")
            prompt = self.config.prompt(prompt_name)
            context = {k: v for k, v in state.items() if k != "events"}
            yield WorkflowEvent("model_call", "Model routing", "Trying configured providers in runtime/configs/models/model_routes.yaml")
            result = await self.router.complete(prompt, state.get("user_input", ""), context)
            if not result.ok:
                state.setdefault("errors", {})[node_id] = result.error
                yield WorkflowEvent("model_error", "Model unavailable", result.error or "No model available", "blocked")
                yield WorkflowEvent("human_action", "Configuration required", "Configure a local model or external API key from the settings panel, then retry.", "blocked")
                return
            state.setdefault("node_results", {})[node_id] = {"provider": result.provider, "content": result.content}
            yield WorkflowEvent("model_result", f"{node_id} result", f"Completed by {result.provider}", "completed", result.content)
            if self.approval.requires_review(node, state):
                yield WorkflowEvent("review", "Human review checkpoint", "Review the result in the UI. The CLI/API demo auto-continues without approving external side effects.", "waiting", self.approval.create_checkpoint(node, result.content))
            return

        if node_type == "dynamic_execution":
            plan = state.get("node_results", {}).get("workflow_planning", {}).get("content", "")
            state.setdefault("node_results", {})[node_id] = {
                "status": "not_executed",
                "reason": "No runtime tool is executed unless a real generated tool exists and is explicitly selected by the plan.",
                "plan_preview": plan,
            }
            yield WorkflowEvent("execution", "Dynamic execution", "No fake tool result was produced. Runtime tools must be generated/configured before side-effect execution.", "completed", state["node_results"][node_id])
            return

        if node_type == "learning":
            record = {
                "time": datetime.now(timezone.utc).isoformat(),
                "input": state.get("user_input"),
                "node_results": state.get("node_results", {}),
                "errors": state.get("errors", {}),
            }
            self.knowledge.save_case(record)
            yield WorkflowEvent("learning", "Feedback learning", "Saved trace summary to runtime knowledge base", "completed")
            return

        if node_type == "final_output":
            yield WorkflowEvent("output", "Final output", "Workflow completed. Check node cards and trace for details.", "completed", state.get("node_results", {}))
            return

        yield WorkflowEvent("node_skip", node_id, f"Unknown node type: {node_type}", "skipped")
