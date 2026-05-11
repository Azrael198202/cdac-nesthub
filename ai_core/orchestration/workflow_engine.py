from __future__ import annotations
import asyncio, json
from pathlib import Path
from typing import AsyncIterator
from ai_core.config_loader import ConfigLoader, ROOT
from ai_core.events import Event
from ai_core.state import CoreState
from ai_core.llm.model_router import ModelRouter
from ai_core.tools.tool_registry import ToolRegistry

class WorkflowEngine:
    def __init__(self):
        self.loader = ConfigLoader()
        self.workflow = self.loader.load_yaml("workflows/default_orchestration.yaml")
        self.model_router = ModelRouter()
        self.tool_registry = ToolRegistry()

    async def run_stream(self, user_input: str) -> AsyncIterator[Event]:
        state = CoreState(user_input=user_input)
        yield Event("start", "Request received", user_input, {"request_id": state.request_id})

        for node in self.workflow.get("nodes", []):
            yield Event("node_start", f"Start: {node['id']}", node.get("description", ""), {"node": node})
            await asyncio.sleep(0.2)

            if node["type"] == "intent":
                prompt = self.loader.load_yaml(node["prompt"])["system"]
                state.intent = await self.model_router.generate_json("intent_recognition", prompt, state.user_input)
                yield Event("thinking", "Intent recognized", json.dumps(state.intent, ensure_ascii=False, indent=2), {"intent": state.intent})

            elif node["type"] == "context":
                state.context = {"conversation_id": "demo", "memory_used": ["short_term", "long_term"]}
                yield Event("thinking", "Context loaded", "Loaded short-term and long-term memory context.", state.context)

            elif node["type"] == "planner":
                prompt = self.loader.load_yaml(node["prompt"])["system"]
                plan_json = await self.model_router.generate_json("workflow_planning", prompt, state.user_input)
                state.plan = plan_json.get("steps", [])
                yield Event("plan", "Execution plan generated", json.dumps(state.plan, ensure_ascii=False, indent=2), {"plan": state.plan})

            elif node["type"] == "executor":
                for step in state.plan:
                    tool_name = step["tool"]
                    if step.get("approval_required"):
                        approval = {"step_id": step["id"], "tool": tool_name, "status": "auto_demo_approved", "note": "Demo mode only. Real booking must require human confirmation."}
                        state.approvals.append(approval)
                        yield Event("approval", "Human approval checkpoint", "真实订票属于高风险动作。Demo 模式自动标记为草案审批通过，不会提交真实订单。", approval)
                        await asyncio.sleep(0.3)
                    yield Event("tool_start", f"Calling tool: {tool_name}", json.dumps(step.get("args", {}), ensure_ascii=False), {"step": step})
                    result = await self.tool_registry.get(tool_name).run(step.get("args", {}))
                    state.tool_results.append(result)
                    yield Event("tool_result", f"Tool result: {tool_name}", json.dumps(result, ensure_ascii=False, indent=2), result)
                    await asyncio.sleep(0.2)

            elif node["type"] == "feedback":
                yield Event("feedback", "Feedback learning", "Saved trace and generated learning sample candidate.", {"learning": "candidate_saved"})

            elif node["type"] == "output":
                state.final_answer = await self.model_router.generate_text("final_response", "Summarize result.", state.user_input, {"tool_results": state.tool_results})
                yield Event("final", "Final answer", state.final_answer, {"answer": state.final_answer})

            yield Event("node_end", f"End: {node['id']}", "", {"node_id": node["id"]})

        self._save_trace(state)
        yield Event("done", "Done", "Workflow completed.", {"request_id": state.request_id})

    def _save_trace(self, state: CoreState) -> None:
        path = ROOT / "runtime" / "traces" / f"{state.request_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(state.model_dump_json(indent=2), encoding="utf-8")
