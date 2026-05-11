from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, AsyncGenerator
import json

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
        yield WorkflowEvent("node_start", node_id, f"Starting {node_type}", "running", {"node_id": node_id, "node_type": node_type})

        if node_type == "knowledge_lookup":
            hits = self.knowledge.search(state.get("user_input", ""))
            state.setdefault("knowledge_hits", {})[node_id] = hits
            yield WorkflowEvent("knowledge", "Knowledge lookup", f"Found {len(hits)} related records", "completed", {"node_id": node_id, "hits": hits})
            if self.approval.requires_review(node, state):
                yield WorkflowEvent("review", "Human review checkpoint", "Please confirm whether this knowledge context can be used for the next step.", "waiting", self.approval.create_checkpoint(node, hits))
            return

        if node_type == "llm_json":
            prompt_name = node.get("prompt", "")
            prompt = self.config.prompt(prompt_name)
            context = {k: v for k, v in state.items() if k != "events"}
            yield WorkflowEvent(
                "model_call",
                "Model routing",
                "Trying runtime-configured providers: Ollama -> HuggingFace -> OpenAI.",
                "running",
                {"node_id": node_id, "prompt": prompt_name},
            )
            chunks: list[str] = []
            provider_name = "unknown"
            try:
                async for provider, chunk in self.router.stream_complete(prompt, state.get("user_input", ""), context):
                    provider_name = provider
                    chunks.append(chunk)
                    yield WorkflowEvent(
                        "model_stream",
                        f"{node_id} streaming",
                        chunk,
                        "running",
                        {"node_id": node_id, "provider": provider_name, "chunk": chunk},
                    )
            except Exception as e:
                error = str(e)
                state.setdefault("errors", {})[node_id] = error
                yield WorkflowEvent("model_error", "Model unavailable", error, "blocked", {"node_id": node_id})
                yield WorkflowEvent(
                    "human_action",
                    "Configuration required",
                    "No valid runtime LLM provider completed this step. Configure Ollama, HuggingFace, or OpenAI in Settings, then retry.",
                    "blocked",
                    {"node_id": node_id},
                )
                return
            content = "".join(chunks).strip()
            if not content:
                state.setdefault("errors", {})[node_id] = "empty model response"
                yield WorkflowEvent("model_error", "Empty model response", "The selected provider returned no content.", "blocked", {"node_id": node_id})
                return
            state.setdefault("node_results", {})[node_id] = {"provider": provider_name, "content": content}
            yield WorkflowEvent("model_result", f"{node_id} result", f"Completed by {provider_name}", "completed", {"node_id": node_id, "provider": provider_name, "content": content})
            if self.approval.requires_review(node, state):
                yield WorkflowEvent("review", "Human review checkpoint", "Please review this step result. Approve to continue, or reject and add instructions.", "waiting", self.approval.create_checkpoint(node, content))
            return

        if node_type == "dynamic_execution":
            plan = state.get("node_results", {}).get("workflow_planning", {}).get("content", "")
            execution_result = {
                "status": "not_executed",
                "reason": "No side-effect tool was executed automatically. Runtime tools must be generated/configured and approved before execution.",
                "plan_preview": plan,
            }
            state.setdefault("node_results", {})[node_id] = execution_result
            yield WorkflowEvent("execution", "Dynamic execution", "Prepared execution decision. No fake tool result was produced.", "completed", {"node_id": node_id, **execution_result})
            if self.approval.requires_review(node, state):
                yield WorkflowEvent("review", "Human review checkpoint", "Please confirm whether execution planning is acceptable. Real side effects still require explicit tool configuration and approval.", "waiting", self.approval.create_checkpoint(node, execution_result))
            return

        if node_type == "learning":
            record = {
                "time": datetime.now(timezone.utc).isoformat(),
                "input": state.get("user_input"),
                "node_results": state.get("node_results", {}),
                "errors": state.get("errors", {}),
                "human_reviews": state.get("human_reviews", []),
            }
            self.knowledge.save_case(record)
            yield WorkflowEvent("learning", "Feedback learning", "Saved trace summary to runtime knowledge base", "completed", {"node_id": node_id})
            return

        if node_type == "final_output":
            final_text = self._build_final_output(state)
            state["final_output"] = final_text
            yield WorkflowEvent("output", "Final output", final_text, "completed", {"node_id": node_id, "final_output": final_text, "state_summary": state.get("node_results", {})})
            return

        yield WorkflowEvent("node_skip", node_id, f"Unknown node type: {node_type}", "skipped", {"node_id": node_id})

    def _build_final_output(self, state: dict[str, Any]) -> str:
        results = state.get("node_results", {})
        if not results:
            return "No executable result was produced. Please configure a local model or external API model and try again."
        parts = ["Workflow finished with human-reviewed steps."]
        for node_id, result in results.items():
            provider = result.get("provider") if isinstance(result, dict) else None
            content = result.get("content") if isinstance(result, dict) else result
            if isinstance(content, str):
                preview = content.strip()
                if len(preview) > 600:
                    preview = preview[:600] + "..."
            else:
                preview = json.dumps(content, ensure_ascii=False)[:600]
            prefix = f"- {node_id}"
            if provider:
                prefix += f" ({provider})"
            parts.append(f"{prefix}: {preview}")
        return "\n".join(parts)
