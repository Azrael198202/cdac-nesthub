from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import json
import re

from ai_core.config.paths import RUNTIME_TRACES
from ai_core.knowledge.knowledge_service import KnowledgeService
from ai_core.llm.provider_router import ProviderRouter
from ai_core.runtime.modeling.user_model_selection import UserModelSelectionStore


class ConversationCoreRuntime:
    """Generic AI-core conversation pipeline for non-delegated messages.

    Ordinary messages still pass through the same conceptual stages as the main
    runtime: input parsing, intent recognition, context awareness, workflow
    planning, execution, and output.  This class is intentionally generic: it
    does not contain domain/task-specific routing words or business rules.
    """

    def __init__(self) -> None:
        self.router = ProviderRouter()
        self.knowledge = KnowledgeService()
        self.model_selection = UserModelSelectionStore()

    async def run(self, message: str, *, latest_task: str | None = None) -> dict[str, Any]:
        run_id = "conversation_core_" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
        state: dict[str, Any] = {
            "run_id": run_id,
            "input": str(message or ""),
            "latest_task": latest_task,
            "results": {},
            "progress_events": [],
        }

        self._event(state, "input_parsing", "running")
        parsed = await self._input_parsing(state["input"], run_id)
        state["results"]["input_parsing"] = parsed
        self._event(state, "input_parsing", "completed")

        self._event(state, "intent_recognition", "running")
        intent = await self._intent_recognition(state["input"], parsed, run_id)
        state["results"]["intent_recognition"] = intent
        self._event(state, "intent_recognition", "completed")

        self._event(state, "context_awareness", "running")
        context = self._context_awareness(state["input"], intent)
        state["results"]["context_awareness"] = context
        self._event(state, "context_awareness", "completed")

        self._event(state, "workflow_planning", "running")
        plan = await self._workflow_planning(state["input"], parsed, intent, context, run_id)
        state["results"]["workflow_planning"] = plan
        self._event(state, "workflow_planning", "completed")

        self._event(state, "execution", "running")
        execution = await self._execution(state["input"], parsed, intent, context, plan, run_id)
        state["results"]["execution"] = execution
        self._event(state, "execution", "completed")

        self._event(state, "output", "running")
        output = await self._output(state["input"], parsed, intent, context, plan, execution, run_id)
        state["results"]["output"] = output
        self._event(state, "output", "completed")

        self._write_trace(state)
        final_answer = str(output.get("final_answer") or output.get("message") or "").strip()
        return {
            "action": "conversation_message",
            "origin": "ai_core",
            "status": "completed",
            "run_id": run_id,
            "message": final_answer,
            "final_answer": final_answer,
            "conversation_intent": intent.get("intent_type", "generic_response"),
            "knowledge_used": bool(execution.get("knowledge_used")),
            "knowledge_status": context.get("knowledge_status", {}),
            "latest_task": latest_task,
            "workflow_results": state["results"],
            "progress_events": state["progress_events"],
            "user_facing": True,
        }

    async def _input_parsing(self, text: str, run_id: str) -> dict[str, Any]:
        schema = {
            "type": "object",
            "required": ["language", "normalized_input", "explicit_constraints", "missing_information"],
            "properties": {
                "language": {"type": "string"},
                "normalized_input": {"type": "string"},
                "explicit_constraints": {"type": "array", "items": {"type": "string"}},
                "missing_information": {"type": "array", "items": {"type": "string"}},
            },
            "additionalProperties": True,
        }
        prompt = {
            "id": "conversation_input_parsing",
            "system": (
                "Parse the user's message into generic runtime-ready fields. "
                "Do not infer private facts. Do not expose internal reasoning. "
                "Return only valid JSON matching the schema."
            ),
        }
        return await self._json_stage(
            run_id,
            "conversation_input_parsing",
            prompt,
            "User message:\n" + text,
            schema,
            fallback={
                "language": self._guess_language(text),
                "normalized_input": text.strip(),
                "explicit_constraints": [],
                "missing_information": [],
            },
        )

    async def _intent_recognition(self, text: str, parsed: dict[str, Any], run_id: str) -> dict[str, Any]:
        schema = {
            "type": "object",
            "required": ["intent_type", "confidence", "response_mode", "needs_external_execution"],
            "properties": {
                "intent_type": {"type": "string"},
                "confidence": {"type": "number"},
                "response_mode": {"type": "string"},
                "needs_external_execution": {"type": "boolean"},
                "reason": {"type": "string"},
            },
            "additionalProperties": True,
        }
        prompt = {
            "id": "conversation_intent_recognition",
            "system": (
                "Recognize the user's interaction intent using generic labels only. "
                "Choose whether the message can be answered directly or requires an external runtime action. "
                "Do not use domain-specific routing rules. Return only valid JSON matching the schema."
            ),
        }
        fallback = {
            "intent_type": "direct_response",
            "confidence": 0.5,
            "response_mode": "direct_answer",
            "needs_external_execution": False,
            "reason": "fallback_generic_intent",
        }
        return await self._json_stage(
            run_id,
            "conversation_intent_recognition",
            prompt,
            "Parsed input:\n" + json.dumps(parsed, ensure_ascii=False) + "\n\nUser message:\n" + text,
            schema,
            fallback=fallback,
        )

    def _context_awareness(self, text: str, intent: dict[str, Any]) -> dict[str, Any]:
        kb = self.knowledge.answer_from_knowledge(text)
        return {
            "knowledge_available": bool(kb),
            "knowledge_answer": kb if kb else None,
            "knowledge_status": self.knowledge.status(),
            "upstream_refs": ["input_parsing", "intent_recognition"],
            "intent_type": intent.get("intent_type"),
        }

    async def _workflow_planning(
        self,
        text: str,
        parsed: dict[str, Any],
        intent: dict[str, Any],
        context: dict[str, Any],
        run_id: str,
    ) -> dict[str, Any]:
        schema = {
            "type": "object",
            "required": ["planned_steps", "final_response_contract"],
            "properties": {
                "planned_steps": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["step_id", "step_type", "objective", "execution_ready"],
                        "properties": {
                            "step_id": {"type": "string"},
                            "step_type": {"type": "string"},
                            "objective": {"type": "string"},
                            "execution_ready": {"type": "boolean"},
                            "input_from": {"type": "array", "items": {"type": "string"}},
                        },
                        "additionalProperties": True,
                    },
                },
                "final_response_contract": {
                    "type": "object",
                    "required": ["user_facing", "no_internal_json"],
                    "properties": {
                        "user_facing": {"type": "boolean"},
                        "no_internal_json": {"type": "boolean"},
                        "language": {"type": "string"},
                    },
                    "additionalProperties": True,
                },
            },
            "additionalProperties": True,
        }
        prompt = {
            "id": "conversation_workflow_planning",
            "system": (
                "Create a minimal generic workflow for answering the user's message. "
                "The workflow is for ordinary conversation, not participant/task delegation. "
                "Return only valid JSON matching the schema."
            ),
        }
        fallback = {
            "planned_steps": [
                {
                    "step_id": "step_1",
                    "step_type": "response_generation",
                    "objective": "Produce a direct user-facing response that satisfies the parsed request.",
                    "execution_ready": True,
                    "input_from": ["input_parsing", "intent_recognition", "context_awareness"],
                }
            ],
            "final_response_contract": {
                "user_facing": True,
                "no_internal_json": True,
                "language": parsed.get("language") or "auto",
            },
        }
        payload = {
            "parsed": parsed,
            "intent": intent,
            "context_summary": {
                "knowledge_available": context.get("knowledge_available"),
                "knowledge_status": context.get("knowledge_status"),
            },
            "user_message": text,
        }
        return await self._json_stage(
            run_id,
            "conversation_workflow_planning",
            prompt,
            json.dumps(payload, ensure_ascii=False),
            schema,
            fallback=fallback,
        )

    async def _execution(
        self,
        text: str,
        parsed: dict[str, Any],
        intent: dict[str, Any],
        context: dict[str, Any],
        plan: dict[str, Any],
        run_id: str,
    ) -> dict[str, Any]:
        kb = context.get("knowledge_answer") if isinstance(context.get("knowledge_answer"), dict) else None
        if kb and kb.get("answer"):
            return {
                "status": "completed",
                "execution_mode": "knowledge_augmented_response",
                "answer_material": str(kb.get("answer") or ""),
                "knowledge_used": True,
                "source": "runtime_knowledge",
            }
        answer = await self._direct_answer(text, parsed, intent, plan, run_id)
        return {
            "status": "completed",
            "execution_mode": "model_response",
            "answer_material": answer,
            "knowledge_used": False,
        }

    async def _output(
        self,
        text: str,
        parsed: dict[str, Any],
        intent: dict[str, Any],
        context: dict[str, Any],
        plan: dict[str, Any],
        execution: dict[str, Any],
        run_id: str,
    ) -> dict[str, Any]:
        material = str(execution.get("answer_material") or "").strip()
        if not material:
            material = self._safe_fallback_answer(text)
        schema = {
            "type": "object",
            "required": ["final_answer"],
            "properties": {"final_answer": {"type": "string"}},
            "additionalProperties": True,
        }
        prompt = {
            "id": "conversation_output",
            "system": (
                "Convert the execution material into a clean final user-facing answer. "
                "Do not output JSON, runtime state, traces, node names, or implementation details. "
                "Respect the user's requested language and format. Return only valid JSON matching the schema."
            ),
        }
        payload = {
            "user_message": text,
            "parsed": parsed,
            "intent": intent,
            "plan_contract": plan.get("final_response_contract", {}),
            "execution_material": material,
        }
        result = await self._json_stage(
            run_id,
            "conversation_output",
            prompt,
            json.dumps(payload, ensure_ascii=False),
            schema,
            fallback={"final_answer": material},
        )
        final_answer = str(result.get("final_answer") or material).strip()
        return {
            "status": "completed",
            "final_answer": final_answer,
            "message": final_answer,
            "user_facing": True,
        }

    async def _direct_answer(self, text: str, parsed: dict[str, Any], intent: dict[str, Any], plan: dict[str, Any], run_id: str) -> str:
        schema = {
            "type": "object",
            "required": ["answer"],
            "properties": {"answer": {"type": "string"}},
            "additionalProperties": True,
        }
        prompt = {
            "id": "conversation_execution_response",
            "system": (
                "Answer the user's ordinary message directly. If the user asks for writing, planning, "
                "explanation, translation, or general help, provide the requested content. Do not expose "
                "internal JSON or runtime details. Return only valid JSON matching the schema."
            ),
        }
        payload = {
            "user_message": text,
            "parsed": parsed,
            "intent": intent,
            "plan": plan,
        }
        result = await self._json_stage(
            run_id,
            "conversation_execution_response",
            prompt,
            json.dumps(payload, ensure_ascii=False),
            schema,
            fallback={"answer": ""},
        )
        return str(result.get("answer") or "").strip()

    async def _json_stage(
        self,
        run_id: str,
        node_id: str,
        prompt: dict[str, Any],
        user_payload: str,
        schema: dict[str, Any],
        *,
        fallback: dict[str, Any],
    ) -> dict[str, Any]:
        adapter = self.model_selection.initial_adapter_overrides({
            "adapter_id": node_id + "_adapter",
            "provider_route": [],
            "max_prompt_tokens": 5000,
        })
        try:
            result = await self.router.generate_json(
                run_id=run_id,
                node_id=node_id,
                adapter=adapter,
                prompt=prompt,
                rendered_user_prompt=user_payload,
                schema=schema,
            )
            if isinstance(result, dict):
                result.setdefault("_executor_type", "llm_json")
                result.setdefault("_node_id", node_id)
                return result
        except Exception as exc:
            out = dict(fallback)
            out["_executor_type"] = "fallback"
            out["_node_id"] = node_id
            out["_fallback_reason"] = exc.__class__.__name__
            return out
        out = dict(fallback)
        out["_executor_type"] = "fallback"
        out["_node_id"] = node_id
        out["_fallback_reason"] = "empty_or_invalid_model_result"
        return out

    def _event(self, state: dict[str, Any], stage: str, status: str) -> None:
        state.setdefault("progress_events", []).append({
            "stage": stage,
            "status": status,
            "at": datetime.now(timezone.utc).isoformat(),
        })

    def _write_trace(self, state: dict[str, Any]) -> None:
        try:
            trace_dir = RUNTIME_TRACES / "conversation_core"
            trace_dir.mkdir(parents=True, exist_ok=True)
            path = trace_dir / (state["run_id"] + ".json")
            path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _guess_language(self, text: str) -> str:
        return "zh" if re.search(r"[\u4e00-\u9fff]", text or "") else "auto"

    def _safe_fallback_answer(self, text: str) -> str:
        if not text.strip():
            return "可以。请直接输入需要处理的内容。"
        return "收到。当前模型服务暂时不可用，因此无法生成完整内容。请切换到可用模型后再次发送。"
