from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import json
import os
import re

from ai_core.config.paths import RUNTIME_TRACES, RUNTIME_GENERATED
from ai_core.context.session_memory_store import SessionMemoryStore
from ai_core.context.vector_memory_store import VectorMemoryStore
from ai_core.knowledge.knowledge_service import KnowledgeService
from ai_core.llm.provider_router import ProviderRouter
from auxiliary_brain.research.web_research_tool import GenericWebResearchTool
from ai_core.web_evidence_optimizer import WebEvidenceOptimizer
from auxiliary_brain.capability_acquisition import RuntimeCapabilityGapImplementer
from ai_core.events.need_capability_event import NeedCapabilityEvent
from ai_core.runtime.modeling.user_model_selection import UserModelSelectionStore
from ai_core.runtime.state import runtime_state_manager
from ai_core.runtime.semantic import SourceRelevanceSelector, EvidenceClaimRanker
from ai_core.runtime.reasoning import EvidenceNormalizationLayer, ClaimResolutionLayer, AnswerPlanningLayer, ContentExtractionLayer, AnswerQualityGate
from presentation_brain import PresentationBrain, PresentationRequest


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
        self.sessions = SessionMemoryStore()
        self.vector_memory = VectorMemoryStore()
        self.web_research = GenericWebResearchTool()
        self.web_evidence_optimizer = WebEvidenceOptimizer()
        self.capability_implementer = RuntimeCapabilityGapImplementer()
        self.source_relevance_selector = SourceRelevanceSelector()
        self.evidence_claim_ranker = EvidenceClaimRanker()
        self.evidence_normalizer = EvidenceNormalizationLayer()
        self.claim_resolver = ClaimResolutionLayer()
        self.answer_planner = AnswerPlanningLayer()
        self.content_extractor = ContentExtractionLayer()
        self.answer_quality_gate = AnswerQualityGate()
        self.presentation_brain = PresentationBrain()

    async def run(self, message: str, *, latest_task: str | None = None, session_id: str | None = None, runtime_state_run_id: str | None = None) -> dict[str, Any]:
        conversation_trace_id = "conversation_core_" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
        run_id = str(runtime_state_run_id or conversation_trace_id)
        active_session_id = self.sessions.start_or_get_session(session_id, metadata={"latest_task": latest_task or ""})
        context_window = self.sessions.load_context_window(active_session_id)
        state: dict[str, Any] = {
            "run_id": run_id,
            "conversation_trace_id": conversation_trace_id,
            "session_id": active_session_id,
            "input": str(message or ""),
            "latest_task": latest_task,
            "session_id": active_session_id,
            "context_window": {
                "rolling_summary": context_window.rolling_summary,
                "recent_turns": context_window.recent_turns,
                "open_items": context_window.open_items,
                "boundary": context_window.boundary,
            },
            "results": {},
            "progress_events": [],
        }

        self._event(state, "input_parsing", "running")
        parsed = await self._input_parsing(state["input"], run_id)
        state["results"]["input_parsing"] = parsed
        self._event(state, "input_parsing", "completed")
        self._write_stage_trace(run_id, "input_parsing", "completed", parsed)

        self._event(state, "intent_recognition", "running")
        intent = await self._intent_recognition(state["input"], parsed, run_id)
        state["results"]["intent_recognition"] = intent
        self._event(state, "intent_recognition", "completed")
        self._write_stage_trace(run_id, "intent_recognition", "completed", intent)

        self._event(state, "knowledge_evaluation", "running")
        knowledge_eval = await self._knowledge_evaluation(state["input"], parsed, intent, run_id)
        intent = self._apply_knowledge_evaluation_to_intent(intent, knowledge_eval)
        state["results"]["knowledge_evaluation"] = knowledge_eval
        state["results"]["intent_recognition"] = intent
        self._event(state, "knowledge_evaluation", "completed")
        self._write_stage_trace(run_id, "knowledge_evaluation", "completed", knowledge_eval)
        self._write_stage_trace(run_id, "intent_recognition", "completed", intent)

        self._event(state, "context_awareness", "running")
        context = self._context_awareness(state["input"], intent, state.get("context_window", {}), knowledge_eval, session_id=active_session_id)
        state["results"]["context_awareness"] = context
        self._event(state, "context_awareness", "completed")
        self._write_stage_trace(run_id, "context_awareness", "completed", context)

        self._event(state, "workflow_planning", "running")
        plan = await self._workflow_planning(state["input"], parsed, intent, context, run_id)
        state["results"]["workflow_planning"] = plan
        self._event(state, "workflow_planning", "completed")
        self._write_stage_trace(run_id, "workflow_planning", "completed", plan)

        self._event(state, "execution", "running")
        execution = await self._execution(state["input"], parsed, intent, context, plan, run_id)
        state["results"]["execution"] = execution
        self._event(state, "execution", "completed")
        self._write_stage_trace(run_id, "execution", "completed", execution)

        self._event(state, "result_verification", "running")
        verification = self._result_verification(execution, plan)
        state["results"]["result_verification"] = verification
        self._event(state, "result_verification", "completed" if verification.get("passed") else "needs_review")
        self._write_stage_trace(run_id, "result_verification", "completed" if verification.get("passed") else "needs_review", verification)

        self._event(state, "final_synthesis", "running")
        output = await self._output(state["input"], parsed, intent, context, plan, execution, run_id, verification)
        state["results"]["final_synthesis"] = output
        self._event(state, "final_synthesis", "completed")
        self._write_stage_trace(run_id, "final_synthesis", "completed", output)

        final_answer = str(output.get("final_answer") or output.get("message") or "").strip()
        self._persist_conversation_turn(active_session_id, run_id, state["input"], final_answer, state.get("results", {}))
        state["session_boundary"] = self.sessions.boundary_status(active_session_id)
        self._write_trace(state)
        return {
            "action": "conversation_message",
            "origin": "ai_core",
            "status": "completed",
            "run_id": run_id,
            "message": final_answer,
            "final_answer": final_answer,
            "conversation_intent": intent.get("intent_type", "generic_response"),
            "knowledge_used": bool(execution.get("knowledge_used") or execution.get("external_evidence_used")),
            "knowledge_status": context.get("knowledge_status", {}),
            "latest_task": latest_task,
            "session_id": active_session_id,
            "context_window": {
                "rolling_summary": context_window.rolling_summary,
                "recent_turns": context_window.recent_turns,
                "open_items": context_window.open_items,
                "boundary": context_window.boundary,
            },
            "workflow_results": state["results"],
            "progress_events": state["progress_events"],
            "session_boundary": state.get("session_boundary", {}),
            "evaluation_prompt": "Evaluate the response quality. High-quality results may be promoted into reusable local experience.",
            "user_facing": True,
        }

    async def _presentation_render(
        self,
        *,
        run_id: str,
        original_input: str,
        answer_material: str,
        execution: dict[str, Any],
        verification: dict[str, Any],
    ) -> str:
        materials = [{
            "source": "conversation_execution",
            "status": execution.get("status"),
            "answer_material": answer_material,
            "evidence": execution.get("evidence") if isinstance(execution.get("evidence"), dict) else {},
        }]
        try:
            result = await self.presentation_brain.synthesize(PresentationRequest(
                run_id=run_id,
                node_id="conversation_final_presentation",
                original_input=original_input,
                state={
                    "original_input": original_input,
                    "language": self._guess_language(original_input),
                    "execution": execution,
                    "verification": verification,
                    "runtime": {"presentation_only": True, "model_synthesis_enabled": False},
                },
                materials=materials,
                trust_summary=verification if isinstance(verification, dict) else {},
                output_policy={"delivery_format": "text"},
            ))
            rendered = str(result.final_answer or "").strip()
            return rendered or str(answer_material or "").strip()
        except Exception:
            try:
                from presentation_brain.link_renderer import LinkRenderer
                return LinkRenderer().render(str(answer_material or ""))
            except Exception:
                return str(answer_material or "")

    async def _input_parsing(self, text: str, run_id: str) -> dict[str, Any]:
        """Deterministic, compact input normalization.

        This stage intentionally avoids local LLM calls for the ordinary
        conversation runtime.  It only preserves the original message, a
        normalized text field, and explicit constraint-like lines.  It does not
        decide how a task should be executed.
        """
        raw = str(text or "")
        lines = [line.strip() for line in raw.splitlines() if line.strip()]
        explicit_constraints: list[str] = []
        for line in lines:
            compact = re.sub(r"\s+", " ", line).strip()
            if not compact:
                continue
            if compact.startswith(("-", "*")) or re.match(r"^\d+[.)]\s+", compact) or ":" in compact[:80]:
                explicit_constraints.append(compact[:500])
            if len(explicit_constraints) >= 24:
                break
        return {
            "language": self._guess_language(raw),
            "normalized_input": raw.strip(),
            "explicit_constraints": explicit_constraints,
            "missing_information": [],
            "original_input_preserved": True,
            "_executor_type": "deterministic",
            "_node_id": "conversation_input_parsing",
        }

    async def _intent_recognition(self, text: str, parsed: dict[str, Any], run_id: str) -> dict[str, Any]:
        direct_guard = self._direct_conversation_signal(text)
        if direct_guard:
            return {
                "intent_type": "direct_response",
                "confidence": 0.9,
                "response_mode": "direct_answer",
                "needs_external_execution": False,
                "requires_external_information": False,
                "required_capabilities": [],
                "source_policy": {
                    "requires_source_material": False,
                    "external_access": "not_required",
                    "min_sources": 0,
                },
                "external_information_signals": [],
                "capability_gap_detected": False,
                "capability_gap_reason": "",
                "reason": direct_guard,
                "missing_information": [],
                "_executor_type": "deterministic",
                "_node_id": "conversation_intent_recognition",
            }
        # Fast path for system-level runtime self-extension requests.  This
        # improves accuracy and latency because ai_core only recognizes the
        # control intent here; concrete capability details are still generated
        # later by the acquisition planner and validated by contracts.
        capability_gap = self._generic_capability_gap_signal(text)
        if capability_gap:
            external_signals = self._external_information_signals(text)
            return {
                "intent_type": "capability_gap_resolution",
                "confidence": 0.92,
                "response_mode": "runtime_capability_acquisition",
                "needs_external_execution": True,
                "requires_external_information": bool(external_signals),
                "required_capabilities": ["runtime_capability_acquisition"],
                "source_policy": {
                    "requires_source_material": False,
                    "web_as_fallback_only": True,
                    "min_sources": 0,
                    "max_results": 5,
                },
                "external_information_signals": external_signals,
                "capability_gap_detected": True,
                "capability_gap_reason": "runtime_self_extension_requested",
                "reason": "system_command_skeleton_detected",
                "missing_information": [],
                "research_resolvable_missing_information": [],
                "user_value_collection_policy": {
                    "during_capability_acquisition": "do_not_block_for_implementation_or_runtime_values",
                    "after_registration": "collect_runtime_values_from_generated_schemas",
                },
                "capability_acquisition_policy": {
                    "decision_mode": "runtime_autonomous",
                    "complexity_level": "basic",
                    "allow_research_based_decisions": True,
                    "allow_generated_schemas": True,
                    "allow_generated_tests": True,
                    "allow_runtime_registration": True,
                    "block_on_missing_runtime_values": False,
                    "block_on_missing_implementation_details": False,
                    "runtime_values_collection": "agent_studio_schema_forms_after_registration",
                },
                "_executor_type": "deterministic",
                "_node_id": "conversation_intent_recognition",
            }
        schema = {
            "type": "object",
            "required": ["intent_type", "confidence", "response_mode", "needs_external_execution"],
            "properties": {
                "intent_type": {"type": "string"},
                "confidence": {"type": "number"},
                "response_mode": {"type": "string"},
                "needs_external_execution": {"type": "boolean"},
                "requires_external_information": {"type": "boolean"},
                "required_capabilities": {"type": "array", "items": {"type": "string"}},
                "source_policy": {"type": "object"},
                "external_information_signals": {"type": "array", "items": {"type": "string"}},
                "capability_gap_detected": {"type": "boolean"},
                "capability_gap_reason": {"type": "string"},
                "reason": {"type": "string"},
                "web_search_decision": {"type": "object"},
            },
            "additionalProperties": True,
        }
        prompt = {
            "id": "conversation_intent_recognition",
            "system": (
                "Recognize the user's interaction intent using generic labels only. "
                "Choose whether the message can be answered directly or requires an external runtime action. "
                "First judge whether the user needs web search or other external source material. "
                "Set requires_external_information=true only when the answer cannot be responsibly answered from the current conversation, local knowledge, or uploaded/runtime context and needs outside source-backed material. "
                "Do not set requires_external_information merely because a generic freshness/source word appears; use the whole request meaning. "
                "When external material is needed, include web_search_decision={needs_web_search, reason, search_strategy, evidence_required, source_requirements}. "
                "Set capability_gap_detected=true only when the user explicitly asks to create, acquire, implement, register, install, integrate, configure, or fix a runtime capability/tool/module, and external implementation knowledge should be collected first. "
                "Do not treat greetings, language preference changes, assistant capability questions, or simple conversation as capability gaps. "
                "Use generic signal names only, such as freshness_required, external_source_required, evidence_required, local_context_insufficient, verification_required, and capability_gap_resolution. "
                "Do not use domain-specific routing rules. Return only valid JSON matching the schema."
            ),
        }
        external_signals = self._external_information_signals(text)
        capability_gap = self._generic_capability_gap_signal(text)
        # Fallback is conservative: deterministic lexical signals are recorded as
        # observations, but ordinary web search is not forced unless the LLM
        # decision is unavailable and the request explicitly asks for external
        # lookup/source use. Capability acquisition remains a separate structural
        # runtime-extension path.
        fallback_requires_external = bool(capability_gap or "external_source_required" in external_signals or "external_source_required" in external_signals)
        fallback = {
            "intent_type": "capability_gap_resolution" if capability_gap else ("external_information_request" if fallback_requires_external else "direct_response"),
            "confidence": 0.45,
            "response_mode": "external_solution_guidance" if capability_gap else ("source_grounded_answer" if fallback_requires_external else "direct_answer"),
            "needs_external_execution": fallback_requires_external,
            "requires_external_information": fallback_requires_external,
            "required_capabilities": ["web_retrieval"] if fallback_requires_external else [],
            "source_policy": {
                "requires_source_material": fallback_requires_external,
                "min_sources": 1 if fallback_requires_external else 0,
                "external_access": "required" if fallback_requires_external else "not_required",
                "trusted_sources_preferred": bool(capability_gap),
                "verification_required": bool(fallback_requires_external),
            },
            "web_search_decision": {
                "needs_web_search": bool(fallback_requires_external and not capability_gap),
                "reason": "fallback_explicit_external_lookup_signal" if fallback_requires_external else "fallback_no_external_lookup_required",
                "search_strategy": "search_engine" if fallback_requires_external else "none",
                "evidence_required": bool(fallback_requires_external),
            },
            "external_information_signals": external_signals + (["capability_gap_resolution"] if capability_gap else []),
            "capability_gap_detected": capability_gap,
            "capability_gap_reason": "current_runtime_may_need_external_implementation_knowledge" if capability_gap else "",
            "reason": "fallback_generic_intent",
        }
        result = await self._json_stage(
            run_id,
            "conversation_intent_recognition",
            prompt,
            "Parsed input:\n" + json.dumps(parsed, ensure_ascii=False) + "\n\nUser message:\n" + text,
            schema,
            fallback=fallback,
        )
        external_signals = self._external_information_signals(text)
        capability_gap = self._generic_capability_gap_signal(text)
        if not capability_gap and bool(result.get("capability_gap_detected")):
            # LLMs can over-generalize ordinary chat or assistant capability questions
            # into runtime self-extension.  ai_core only accepts a capability gap
            # when the generic structural runtime-extension signal is present.
            result["capability_gap_detected"] = False
            result["capability_gap_reason"] = ""
            result["intent_type"] = "direct_response"
            result["response_mode"] = "direct_answer"
            result["needs_external_execution"] = False
            result["requires_external_information"] = False
            result["required_capabilities"] = []
            result["source_policy"] = {"requires_source_material": False, "external_access": "not_required", "min_sources": 0}
            result["reason"] = "capability_gap_rejected_without_runtime_extension_signal"
        decision = result.get("web_search_decision") if isinstance(result.get("web_search_decision"), dict) else {}
        llm_requires_external = bool(result.get("requires_external_information") or result.get("needs_external_execution") or decision.get("needs_web_search"))
        requires_external = bool(capability_gap or llm_requires_external)
        if not capability_gap and llm_requires_external:
            result["requires_external_information"] = True
            result["needs_external_execution"] = True
            caps = result.get("required_capabilities") if isinstance(result.get("required_capabilities"), list) else []
            if "web_retrieval" not in caps:
                caps.append("web_retrieval")
            result["required_capabilities"] = caps
            policy = result.get("source_policy") if isinstance(result.get("source_policy"), dict) else {}
            policy.setdefault("requires_source_material", True)
            policy.setdefault("min_sources", 1)
            policy.setdefault("external_access", "required")
            policy.setdefault("verification_required", True)
            result["source_policy"] = policy
            decision.setdefault("needs_web_search", True)
            decision.setdefault("search_strategy", "search_engine")
            decision.setdefault("evidence_required", True)
            result["web_search_decision"] = decision
        elif capability_gap:
            result["requires_external_information"] = bool(result.get("requires_external_information"))
            result["needs_external_execution"] = True
        merged_signals = result.get("external_information_signals") if isinstance(result.get("external_information_signals"), list) else []
        for signal in external_signals + (["capability_gap_resolution"] if capability_gap else []):
            if signal not in merged_signals:
                merged_signals.append(signal)
        result["external_information_signals"] = merged_signals
        if capability_gap:
            result["capability_gap_detected"] = True
            result["capability_gap_reason"] = result.get("capability_gap_reason") or "current_runtime_may_need_external_implementation_knowledge"
            result["intent_type"] = "capability_gap_resolution"
            result["response_mode"] = result.get("response_mode") or "external_solution_guidance"
            # Missing protocol/library/auth/config details are implementation knowledge or
            # runtime values for generated schemas.  They must not block capability
            # acquisition.  Actual user-specific values are collected after registration
            # by dynamic UI forms generated from the registered schema.
            raw_missing = result.get("missing_information") if isinstance(result.get("missing_information"), list) else []
            if raw_missing:
                result["research_resolvable_missing_information"] = raw_missing
            result["missing_information"] = []
            result["user_value_collection_policy"] = {
                "during_capability_acquisition": "do_not_block_for_implementation_or_runtime_values",
                "after_registration": "collect_runtime_values_from_generated_schemas",
            }
            result["capability_acquisition_policy"] = {
                "decision_mode": "runtime_autonomous",
                "complexity_level": "basic",
                "allow_research_based_decisions": True,
                "allow_generated_schemas": True,
                "allow_generated_tests": True,
                "allow_runtime_registration": True,
                "block_on_missing_runtime_values": False,
                "block_on_missing_implementation_details": False,
                "runtime_values_collection": "agent_studio_schema_forms_after_registration",
            }
        return result


    async def _knowledge_evaluation(self, text: str, parsed: dict[str, Any], intent: dict[str, Any], run_id: str) -> dict[str, Any]:
        """Generic knowledge confidence and verification gate.

        This layer does not know domains or providers. It asks whether the
        response can be responsibly produced from already available material, or
        whether source-backed external evidence is required before answering.
        """
        direct_guard = self._direct_conversation_signal(text)
        if direct_guard:
            return {
                "can_answer_from_current_material": True,
                "confidence": 0.9,
                "requires_verification": False,
                "requires_external_information": False,
                "needs_web_search": False,
                "search_strategy": "none",
                "evidence_required": False,
                "source_requirements": {},
                "reason": direct_guard,
                "external_information_signals": [],
                "_executor_type": "deterministic",
                "_node_id": "conversation_knowledge_evaluation",
            }
        external_signals = self._external_information_signals(text)
        source_or_verification_requested = any(sig in external_signals for sig in ("external_source_required", "evidence_required", "verification_required"))
        freshness_observed = "freshness_required" in external_signals
        schema = {
            "type": "object",
            "required": [
                "can_answer_from_current_material",
                "confidence",
                "requires_verification",
                "requires_external_information",
                "needs_web_search",
                "search_strategy",
                "evidence_required",
                "reason",
            ],
            "properties": {
                "can_answer_from_current_material": {"type": "boolean"},
                "confidence": {"type": "number"},
                "requires_verification": {"type": "boolean"},
                "requires_external_information": {"type": "boolean"},
                "needs_web_search": {"type": "boolean"},
                "search_strategy": {"type": "string"},
                "evidence_required": {"type": "boolean"},
                "source_requirements": {"type": "object"},
                "reason": {"type": "string"},
                "external_information_signals": {"type": "array", "items": {"type": "string"}},
            },
            "additionalProperties": True,
        }
        prompt = {
            "id": "conversation_knowledge_evaluation",
            "system": (
                "Evaluate whether the assistant can responsibly answer from current conversation, local model knowledge, uploaded/runtime context, and stable general knowledge. "
                "Do not answer the user. Return only a routing/evidence decision as JSON. "
                "If the user explicitly asks for sources, official sources, citations, URLs, verification, checking, browsing, searching, or up-to-date/current/latest material that cannot be guaranteed from current material, set requires_external_information=true and needs_web_search=true. "
                "A freshness/source signal is an observation, not an automatic decision; use the whole request and the ability to verify. "
                "If the answer requires source-backed evidence, set evidence_required=true and search_strategy=search_engine unless the user supplied a direct URL. "
                "Use generic terms only; do not use domain-specific routing rules. Return only valid JSON matching the schema."
            ),
        }
        fallback_external = bool(source_or_verification_requested or (freshness_observed and not bool(intent.get("confidence", 0) and float(intent.get("confidence") or 0) >= 0.85)))
        fallback = {
            "can_answer_from_current_material": not fallback_external,
            "confidence": 0.55 if fallback_external else 0.75,
            "requires_verification": bool(source_or_verification_requested or freshness_observed),
            "requires_external_information": fallback_external,
            "needs_web_search": fallback_external,
            "search_strategy": "direct_url" if re.search(r"https?://", str(text or ""), flags=re.I) else ("search_engine" if fallback_external else "none"),
            "evidence_required": fallback_external,
            "source_requirements": {
                "required": fallback_external,
                "min_verified_sources": 1 if fallback_external else 0,
                "preferred_source_types": ["official", "high_reputation", "general_web"] if fallback_external else [],
            },
            "reason": "fallback_source_or_verification_requirement" if fallback_external else "fallback_current_material_sufficient",
            "external_information_signals": external_signals,
        }
        result = await self._json_stage(
            run_id,
            "conversation_knowledge_evaluation",
            prompt,
            json.dumps({"parsed": parsed, "intent": intent, "user_message": text, "external_information_signals": external_signals}, ensure_ascii=False),
            schema,
            fallback=fallback,
        )
        if not isinstance(result.get("external_information_signals"), list):
            result["external_information_signals"] = external_signals
        else:
            for sig in external_signals:
                if sig not in result["external_information_signals"]:
                    result["external_information_signals"].append(sig)
        # Explicit source/verification requirements are a hard evidence contract.
        # The LLM may still mark current material sufficient; ai_core must not let
        # final_synthesis fabricate source-backed answers without retrieved evidence.
        if source_or_verification_requested and not self._direct_conversation_signal(text):
            result["requires_verification"] = True
            result["requires_external_information"] = True
            result["needs_web_search"] = True
            result["evidence_required"] = True
            result["search_strategy"] = "direct_url" if re.search(r"https?://", str(text or ""), flags=re.I) else "search_engine"
            result["can_answer_from_current_material"] = False
            source_requirements = result.get("source_requirements") if isinstance(result.get("source_requirements"), dict) else {}
            source_requirements.setdefault("required", True)
            source_requirements.setdefault("min_verified_sources", 1)
            result["source_requirements"] = source_requirements
        return result

    def _apply_knowledge_evaluation_to_intent(self, intent: dict[str, Any], knowledge_eval: dict[str, Any]) -> dict[str, Any]:
        result = dict(intent or {})
        if not isinstance(knowledge_eval, dict):
            return result
        capability_gap = bool(result.get("capability_gap_detected"))
        needs_web = bool(knowledge_eval.get("needs_web_search") or knowledge_eval.get("requires_external_information"))
        evidence_required = bool(knowledge_eval.get("evidence_required") or knowledge_eval.get("requires_verification"))
        if needs_web and not capability_gap:
            result["requires_external_information"] = True
            result["needs_external_execution"] = True
            result["response_mode"] = "source_grounded_answer"
            caps = result.get("required_capabilities") if isinstance(result.get("required_capabilities"), list) else []
            if "web_retrieval" not in caps:
                caps.append("web_retrieval")
            result["required_capabilities"] = caps
            policy = result.get("source_policy") if isinstance(result.get("source_policy"), dict) else {}
            policy["requires_source_material"] = True
            policy["external_access"] = "required"
            policy["verification_required"] = True
            policy["min_sources"] = max(1, int(policy.get("min_sources") or 0))
            source_req = knowledge_eval.get("source_requirements") if isinstance(knowledge_eval.get("source_requirements"), dict) else {}
            if source_req.get("min_verified_sources"):
                try:
                    policy["min_sources"] = max(policy["min_sources"], int(source_req.get("min_verified_sources") or 1))
                except Exception:
                    pass
            result["source_policy"] = policy
            decision = result.get("web_search_decision") if isinstance(result.get("web_search_decision"), dict) else {}
            decision["needs_web_search"] = True
            decision["reason"] = knowledge_eval.get("reason") or decision.get("reason") or "knowledge_evaluation_requires_external_evidence"
            decision["search_strategy"] = knowledge_eval.get("search_strategy") or decision.get("search_strategy") or "search_engine"
            decision["evidence_required"] = evidence_required
            decision["source_requirements"] = source_req
            result["web_search_decision"] = decision
        result["knowledge_evaluation"] = knowledge_eval
        merged = result.get("external_information_signals") if isinstance(result.get("external_information_signals"), list) else []
        for sig in knowledge_eval.get("external_information_signals", []) if isinstance(knowledge_eval.get("external_information_signals"), list) else []:
            if sig not in merged:
                merged.append(sig)
        result["external_information_signals"] = merged
        return result

    def _context_awareness(self, text: str, intent: dict[str, Any], context_window: dict[str, Any] | None = None, knowledge_evaluation: dict[str, Any] | None = None, *, session_id: str | None = None) -> dict[str, Any]:
        kb = self.knowledge.answer_from_knowledge(text)
        raw_vector_hits = self.vector_memory.search(text, limit=12, usage_scope="retrieval_context")
        vector_hits = self._filter_retrieved_context_for_session(raw_vector_hits, session_id=session_id, limit=5)
        knowledge_eval = knowledge_evaluation if isinstance(knowledge_evaluation, dict) else {}
        return {
            "knowledge_available": bool(kb),
            "knowledge_answer": kb if kb else None,
            "knowledge_status": self.knowledge.status(),
            "knowledge_evaluation": knowledge_eval,
            "session_context": context_window or {},
            "retrieved_context": [
                {"text": str(item.get("text") or "")[:1200], "score": item.get("score"), "metadata": item.get("metadata", {})}
                for item in vector_hits
            ],
            "retrieved_context_policy": {
                "scope": "current_session_only",
                "session_id": str(session_id or ""),
                "discarded_cross_session_count": max(0, len(raw_vector_hits) - len(vector_hits)),
            },
            "upstream_refs": ["input_parsing", "intent_recognition", "knowledge_evaluation"],
            "intent_type": intent.get("intent_type"),
        }

    def _filter_retrieved_context_for_session(self, hits: list[dict[str, Any]], *, session_id: str | None, limit: int = 5) -> list[dict[str, Any]]:
        """Keep retrieval context isolated to the active session.

        Vector memory is useful for continuing a task, but it must not inject
        previous independent sessions into a new session. Cross-session reuse
        should be an explicit workflow decision, not an automatic context side
        effect.
        """
        sid = str(session_id or "").strip()
        if not sid:
            return []
        kept: list[dict[str, Any]] = []
        for item in hits or []:
            if not isinstance(item, dict):
                continue
            metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            if str(metadata.get("session_id") or "") != sid:
                continue
            kept.append(item)
            if len(kept) >= max(1, int(limit)):
                break
        return kept

    def _build_need_capability_payload(
        self,
        *,
        text: str,
        parsed: dict[str, Any],
        intent: dict[str, Any],
        context: dict[str, Any],
        planned_step: dict[str, Any] | None = None,
        plan: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build the ai_core -> auxiliary_brain capability contract.

        ai_core owns understanding, missing-information handling, context, and
        workflow planning.  auxiliary_brain must consume this contract and must
        not restart intent recognition from the raw user message.
        """
        step = planned_step if isinstance(planned_step, dict) else {}
        missing = []
        for source in (parsed, intent, context, plan or {}, step):
            if isinstance(source, dict):
                for key in ("blocking_missing_information", "missing_information", "missing_required", "missing_fields"):
                    values = source.get(key)
                    if isinstance(values, list):
                        for item in values:
                            if item not in missing:
                                missing.append(item)
        known_parameters: dict[str, Any] = {}
        for source in (parsed, intent, context, step):
            if not isinstance(source, dict):
                continue
            for key in ("parameters", "known_parameters", "extracted_fields", "explicit_fields"):
                values = source.get(key)
                if isinstance(values, dict):
                    known_parameters.update(values)
        return {
            "contract_version": "need_capability_event.v2",
            "original_user_input": text,
            "input_contract": {
                "language": parsed.get("language"),
                "normalized_input": parsed.get("normalized_input"),
                "explicit_constraints": parsed.get("explicit_constraints") if isinstance(parsed.get("explicit_constraints"), list) else [],
                "original_input_preserved": bool(parsed.get("original_input_preserved")),
            },
            "intent_contract": {
                "intent_type": intent.get("intent_type"),
                "response_mode": intent.get("response_mode"),
                "confidence": intent.get("confidence"),
                "required_capabilities": intent.get("required_capabilities") if isinstance(intent.get("required_capabilities"), list) else [],
                "capability_gap_detected": bool(intent.get("capability_gap_detected")),
                "capability_gap_reason": intent.get("capability_gap_reason"),
                "source_policy": intent.get("source_policy") if isinstance(intent.get("source_policy"), dict) else {},
                "capability_acquisition_policy": intent.get("capability_acquisition_policy") if isinstance(intent.get("capability_acquisition_policy"), dict) else {},
                "user_value_collection_policy": intent.get("user_value_collection_policy") if isinstance(intent.get("user_value_collection_policy"), dict) else {},
            },
            "workflow_contract": {
                "planned_step": step,
                "locked_execution": (plan or {}).get("locked_execution") if isinstance((plan or {}).get("locked_execution"), dict) else {},
                "final_response_contract": (plan or {}).get("final_response_contract") if isinstance((plan or {}).get("final_response_contract"), dict) else {},
                "blocking_missing_information": missing,
                "known_parameters": known_parameters,
            },
            "capability_constraints": parsed.get("explicit_constraints") if isinstance(parsed.get("explicit_constraints"), list) else [],
            "acquisition_boundary": {
                "intent_source": "ai_core.intent_recognition",
                "workflow_source": "ai_core.workflow_planning",
                "auxiliary_brain_must_not_reinfer_intent": True,
                "schema_source": "workflow_contract_and_capability_constraints",
            },
        }

    async def _workflow_planning(
        self,
        text: str,
        parsed: dict[str, Any],
        intent: dict[str, Any],
        context: dict[str, Any],
        run_id: str,
    ) -> dict[str, Any]:
        # System-level capability acquisition uses a fixed generic skeleton.
        # The skeleton only locks the execution method; it does not decide
        # concrete tools, fields, providers, or runtime values.  That work is
        # delegated to the capability acquisition pipeline.
        if intent.get("capability_gap_detected"):
            initial_step = {
                "step_id": "step_1",
                "step_type": "resolve_capability_gap",
                "objective": "Generate, validate, register, and verify a runtime capability through the acquisition pipeline.",
                "execution_ready": True,
                "input_from": ["input_parsing", "intent_recognition", "context_awareness"],
                "execution_method": "capability_acquisition",
                "capability": "runtime_capability_acquisition",
                "source_policy": {
                    "requires_source_material": False,
                    "web_as_fallback_only": True,
                    "min_sources": 0,
                    "max_results": 5,
                },
            }
            initial_plan = {
                "locked_execution": {
                    "execution_method": "capability_acquisition",
                    "capability": "runtime_capability_acquisition",
                    "reason": "capability_gap_resolution",
                },
                "final_response_contract": {
                    "user_facing": True,
                    "no_internal_json": True,
                    "language": parsed.get("language") or "auto",
                },
                "blocking_missing_information": [],
            }
            need_event = NeedCapabilityEvent(
                run_id=run_id,
                required_capability="runtime_capability_acquisition",
                available=False,
                payload=self._build_need_capability_payload(
                    text=text,
                    parsed=parsed,
                    intent=intent,
                    context=context,
                    planned_step=initial_step,
                    plan=initial_plan,
                ),
            ).to_dict()
            return {
                "required_capability": "runtime_capability_acquisition",
                "available": False,
                "need_capability_event": need_event,
                "planned_steps": [initial_step],
                "locked_execution": initial_plan["locked_execution"],
                "final_response_contract": initial_plan["final_response_contract"],
                "_executor_type": "deterministic",
                "_node_id": "conversation_workflow_planning",
            }
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
                            "execution_method": {"type": "string"},
                            "capability": {"type": "string"},
                            "source_policy": {"type": "object"},
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
                "If intent.web_search_decision.needs_web_search is true or intent.requires_external_information is true, lock execution_method=web_search and capability=web_retrieval in the planned step. "
                "If intent.capability_gap_detected is true, plan a generic resolve_capability_gap step before any implementation step; do not silently execute untrusted external code. "
                "Do not use domain-specific routing rules. Return only valid JSON matching the schema."
            ),
        }
        fallback = {
            "planned_steps": [
                {
                    "step_id": "step_1",
                    "step_type": "resolve_capability_gap" if intent.get("capability_gap_detected") else "response_generation",
                    "objective": "Collect trusted external implementation guidance for a runtime capability gap." if intent.get("capability_gap_detected") else "Produce a direct user-facing response that satisfies the parsed request.",
                    "execution_ready": True,
                    "input_from": ["input_parsing", "intent_recognition", "context_awareness"],
                    "execution_method": "web_search" if (intent.get("requires_external_information") or intent.get("needs_external_execution")) else "model_response",
                    "capability": "web_retrieval" if (intent.get("requires_external_information") or intent.get("needs_external_execution")) else "stable_synthesis",
                    "source_policy": intent.get("source_policy") if isinstance(intent.get("source_policy"), dict) else {},
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
                "session_context": context.get("session_context", {}),
                "retrieved_context": context.get("retrieved_context", []),
            },
            "user_message": text,
        }
        plan = await self._json_stage(
            run_id,
            "conversation_workflow_planning",
            prompt,
            json.dumps(payload, ensure_ascii=False),
            schema,
            fallback=fallback,
        )
        intent_web_decision = intent.get("web_search_decision") if isinstance(intent.get("web_search_decision"), dict) else {}
        if intent.get("requires_external_information") or intent.get("needs_external_execution") or intent_web_decision.get("needs_web_search"):
            steps = plan.get("planned_steps") if isinstance(plan.get("planned_steps"), list) else []
            if not steps:
                steps = fallback["planned_steps"]
            capability_gap = bool(intent.get("capability_gap_detected"))
            for step in steps[:1]:
                if isinstance(step, dict):
                    if capability_gap:
                        step["execution_method"] = "capability_acquisition"
                        step["capability"] = "runtime_capability_acquisition"
                        step["step_type"] = "resolve_capability_gap"
                        step.setdefault("objective", "Generate, validate, register, and verify a runtime capability through the acquisition pipeline.")
                        policy = step.get("source_policy") if isinstance(step.get("source_policy"), dict) else {}
                        policy.setdefault("requires_source_material", False)
                        policy.setdefault("web_as_fallback_only", True)
                        policy.setdefault("min_sources", 0)
                        step["source_policy"] = policy
                    else:
                        step["execution_method"] = "web_search"
                        step["capability"] = "web_retrieval"
                        policy = step.get("source_policy") if isinstance(step.get("source_policy"), dict) else {}
                        policy.setdefault("requires_source_material", True)
                        policy.setdefault("min_sources", 2)
                        step["source_policy"] = policy
            plan["planned_steps"] = steps
            plan["locked_execution"] = {
                "execution_method": "capability_acquisition" if capability_gap else "web_search",
                "capability": "runtime_capability_acquisition" if capability_gap else "web_retrieval",
                "reason": "capability_gap_resolution" if capability_gap else "external_information_required",
            }
            if capability_gap:
                plan["required_capability"] = "runtime_capability_acquisition"
                plan["available"] = False
                first_step = steps[0] if steps and isinstance(steps[0], dict) else {}
                plan["need_capability_event"] = NeedCapabilityEvent(
                    run_id=run_id,
                    required_capability="runtime_capability_acquisition",
                    available=False,
                    payload=self._build_need_capability_payload(
                        text=text, parsed=parsed, intent=intent, context=context, planned_step=first_step, plan=plan
                    ),
                ).to_dict()
        return plan

    async def _execution(
        self,
        text: str,
        parsed: dict[str, Any],
        intent: dict[str, Any],
        context: dict[str, Any],
        plan: dict[str, Any],
        run_id: str,
    ) -> dict[str, Any]:
        selected = self._selected_step(plan)
        if str(selected.get("execution_method") or "") == "capability_acquisition" or str(selected.get("capability") or "") == "runtime_capability_acquisition":
            evidence = {
                "query": self._capability_gap_query(text),
                "original_user_input": text,
                "search_status": "not_required_before_planner",
                "source_count": 0,
                "fetched_count": 0,
                "urls": [],
                "results": [],
                "fetched_documents": [],
                "attempts": [],
                "planner_input_source": "input_intent_workflow",
                "need_capability_event": plan.get("need_capability_event") if isinstance(plan.get("need_capability_event"), dict) else {},
            }
            runtime_impl = self.capability_implementer.implement_if_requested(
                user_input=text,
                evidence=evidence,
                run_id=run_id,
                allow_implementation=self._implementation_requested(text),
            )
            # If the planner explicitly asks for external evidence, use web only
            # as a fallback material source, then retry the same acquisition
            # contract. A missing web result must not block a policy-backed basic
            # capability whose planner says evidence is not required.
            if runtime_impl.get("status") in {"planner_failed", "planner_low_confidence", "evidence_missing"}:
                planned_queries = self.web_evidence_optimizer.plan_queries(user_input=text, capability="runtime_capability_acquisition", objective=evidence.get("query", ""))
                evidence["planned_queries"] = planned_queries
                search_query = str((planned_queries[0] or {}).get("query") or evidence["query"]) if planned_queries else evidence["query"]
                search = await self.web_research.search(query=search_query, max_results=5)
                evidence_items = search.get("results") if isinstance(search.get("results"), list) else []
                fetched = []
                for item in evidence_items[:5]:
                    url = str(item.get("url") or "").strip() if isinstance(item, dict) else ""
                    if not url:
                        continue
                    doc = await self.web_research.fetch(url=url, max_chars=8000)
                    if isinstance(doc, dict) and doc.get("status") == "success":
                        fetched.append(doc)
                optimized = self.web_evidence_optimizer.optimize(
                    user_input=text,
                    capability="runtime_capability_acquisition",
                    objective=evidence.get("query", ""),
                    search_results=evidence_items,
                    documents=[{"document": d, "source_search_result": next((r for r in evidence_items if isinstance(r, dict) and r.get("url") == d.get("url")), {})} for d in fetched if isinstance(d, dict)],
                )
                evidence.update({
                    "search_status": search.get("status"),
                    "source_count": len(evidence_items),
                    "fetched_count": len(fetched),
                    "urls": [str(x.get("url") or "") for x in evidence_items if isinstance(x, dict) and x.get("url")],
                    "results": evidence_items,
                    "fetched_documents": fetched,
                    "attempts": search.get("attempts") if isinstance(search.get("attempts"), list) else [],
                    "optimized_evidence": optimized,
                    "planner_input_source": "input_intent_workflow_plus_optimized_web_fallback",
                })
                runtime_impl = self.capability_implementer.implement_if_requested(
                    user_input=text,
                    evidence=evidence,
                    run_id=run_id,
                    allow_implementation=self._implementation_requested(text),
                )
            implementation = self._capability_gap_resolution_artifact(
                user_input=text,
                query=evidence.get("query", ""),
                evidence=evidence,
                material="",
                run_id=run_id,
                runtime_implementation=runtime_impl,
            )
            material = self._capability_gap_answer_material(
                user_input=text,
                evidence=evidence,
                implementation=implementation,
                material="",
            )
            runtime_registered = runtime_impl.get("status") == "registered"
            return {
                "status": "completed" if runtime_registered else "capability_acquisition_failed",
                "execution_mode": "capability_acquisition",
                "capability": "runtime_capability_acquisition",
                "answer_material": material,
                "external_evidence_used": bool(evidence.get("urls")),
                "policy_backed_runtime_registration": bool(runtime_registered and not evidence.get("urls")),
                "capability_gap_resolution": True,
                "capability_implementation": implementation,
                "evidence": evidence,
                "knowledge_used": False,
            }
        if str(selected.get("execution_method") or "") == "web_search" or str(selected.get("capability") or "") == "web_retrieval":
            policy = selected.get("source_policy") if isinstance(selected.get("source_policy"), dict) else {}
            max_results = int(policy.get("max_results") or 5)
            capability_gap = bool(intent.get("capability_gap_detected") or str(selected.get("step_type") or "") == "resolve_capability_gap")
            query = self._capability_gap_query(text) if capability_gap else text
            planned_queries = self.web_evidence_optimizer.plan_queries(user_input=text, capability=str(selected.get("capability") or ""), objective=query)
            search_query = str((planned_queries[0] or {}).get("query") or query) if planned_queries else query
            search = await self.web_research.search(query=search_query, max_results=max_results)
            evidence_items = search.get("results") if isinstance(search.get("results"), list) else []
            fetched = []
            for item in evidence_items[:max(2, min(max_results, 5))]:
                url = str(item.get("url") or "").strip() if isinstance(item, dict) else ""
                if not url:
                    continue
                doc = await self.web_research.fetch(url=url, max_chars=8000)
                if isinstance(doc, dict) and doc.get("status") == "success":
                    fetched.append(doc)
            verification_policy = selected.get("source_policy") if isinstance(selected.get("source_policy"), dict) else {}
            min_sources = int(verification_policy.get("min_sources") or 1)
            web_verification = self._verify_web_evidence(text, search, fetched, min_sources=min_sources)
            verified_urls = set(web_verification.get("verified_urls") if isinstance(web_verification.get("verified_urls"), list) else [])
            verified_results = [x for x in evidence_items if isinstance(x, dict) and str(x.get("url") or "") in verified_urls]
            verified_fetched = [x for x in fetched if isinstance(x, dict) and str(x.get("url") or "") in verified_urls]
            verified_search = dict(search)
            verified_search["results"] = verified_results
            if web_verification.get("passed"):
                material = await self._web_answer_material(text, verified_search, verified_fetched, run_id)
            else:
                material = self._external_retrieval_failure_material({
                    "query": query,
                    "search_query_used": search_query,
                    "search_status": search.get("status"),
                    "source_count": len(evidence_items),
                    "fetched_count": len(fetched),
                    "urls": [str(x.get("url") or "") for x in evidence_items if isinstance(x, dict) and x.get("url")],
                    "attempts": search.get("attempts") if isinstance(search.get("attempts"), list) else [],
                    "verification": web_verification,
                    "failure_reason": "web_evidence_verification_failed",
                })
            optimized = self.web_evidence_optimizer.optimize(
                user_input=text,
                capability=str(selected.get("capability") or ""),
                objective=query,
                search_results=evidence_items,
                documents=[{"document": d, "source_search_result": next((r for r in evidence_items if isinstance(r, dict) and r.get("url") == d.get("url")), {})} for d in fetched if isinstance(d, dict)],
            )
            evidence = {
                "query": query,
                "search_query_used": search_query,
                "planned_queries": planned_queries,
                "original_user_input": text,
                "search_status": search.get("status"),
                "source_count": len(evidence_items),
                "fetched_count": len(fetched),
                "urls": [str(x.get("url") or "") for x in evidence_items if isinstance(x, dict) and x.get("url")],
                "results": evidence_items,
                "fetched_documents": fetched,
                "optimized_evidence": optimized,
                "verification": web_verification,
                "verification_status": web_verification.get("status"),
                "search_strategy": "direct_url" if re.search(r"https?://", query) else "search_engine",
                "search_provider_config": search.get("provider_config") if isinstance(search.get("provider_config"), dict) else {},
                "attempts": search.get("attempts") if isinstance(search.get("attempts"), list) else [],
                "need_capability_event": plan.get("need_capability_event") if isinstance(plan.get("need_capability_event"), dict) else {},
            }
            implementation = None
            if capability_gap:
                # Capability acquisition must not be blocked merely because the
                # web search adapter returned no verified URLs.  For basic,
                # policy-backed templates, the runtime implementer may still
                # generate, sandbox-test, verify, and register a capability
                # using only the local generated template contract.  This keeps
                # ai_core generic: the concrete fields and behavior still come
                # from runtime capability templates, not from fixed core logic.
                runtime_impl = self.capability_implementer.implement_if_requested(
                    user_input=text,
                    evidence=evidence,
                    run_id=run_id,
                    allow_implementation=self._implementation_requested(text),
                )
                policy_backed_registration = False
                if (not evidence.get("urls")) and runtime_impl.get("status") == "registered":
                    evidence["urls"] = ["runtime-policy://basic-generated-capability-contract"]
                    evidence["source_count"] = 1
                    evidence["source_note"] = "Policy-backed basic acquisition used because external retrieval did not provide source URLs."
                    policy_backed_registration = True
                implementation = self._capability_gap_resolution_artifact(
                    user_input=text,
                    query=query,
                    evidence=evidence,
                    material=material,
                    run_id=run_id,
                    runtime_implementation=runtime_impl,
                )
                material = self._capability_gap_answer_material(
                    user_input=text,
                    evidence=evidence,
                    implementation=implementation,
                    material=material,
                )
            elif not material and not evidence_items:
                material = self._external_retrieval_failure_material(evidence)
            runtime_registered = False
            if implementation and isinstance(implementation.get("runtime_implementation"), dict):
                runtime_registered = implementation["runtime_implementation"].get("status") == "registered"
            completed = bool(runtime_registered) or (bool(evidence_items) and (capability_gap or bool(evidence.get("verification", {}).get("passed"))))
            return {
                "status": "completed" if completed else "blocked_no_verified_web_evidence",
                "execution_mode": "capability_gap_resolution" if capability_gap else "web_search",
                "capability": "web_retrieval",
                "answer_material": material,
                "external_evidence_used": bool(evidence_items) and bool(capability_gap or evidence.get("verification", {}).get("passed")),
                "policy_backed_runtime_registration": bool(runtime_registered and not evidence_items),
                "capability_gap_resolution": capability_gap,
                "capability_implementation": implementation,
                "evidence": evidence,
                "knowledge_used": False,
            }
        kb = context.get("knowledge_answer") if isinstance(context.get("knowledge_answer"), dict) else None
        if kb and kb.get("answer"):
            return {
                "status": "completed",
                "execution_mode": "knowledge_augmented_response",
                "answer_material": str(kb.get("answer") or ""),
                "knowledge_used": True,
                "source": "runtime_knowledge",
            }
        answer = await self._direct_answer(text, parsed, intent, context, plan, run_id)
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
        verification: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        material = str(execution.get("answer_material") or "").strip()
        if not material:
            material = self._safe_fallback_answer(text)
        # Capability acquisition answers are lifecycle/status reports. Do not let
        # a later language model rewrite a registered runtime capability into a
        # misleading missing-configuration block. Runtime values are collected by
        # Agent Studio schema forms after registration.
        if bool(execution.get("capability_gap_resolution")):
            return {
                "status": "completed",
                "final_answer": material,
                "message": material,
                "user_facing": True,
            }
        evidence = execution.get("evidence") if isinstance(execution.get("evidence"), dict) else {}
        evidence_verification = evidence.get("verification") if isinstance(evidence.get("verification"), dict) else {}
        if str(execution.get("execution_mode") or "") == "web_search":
            # Source-required web answers are already synthesized from verified
            # evidence in the execution layer. Presentation Brain may only render
            # the expression layer, such as clickable links; it must not execute
            # or invent facts.
            rendered = await self._presentation_render(
                run_id=run_id,
                original_input=text,
                answer_material=material,
                execution=execution,
                verification=verification or {},
            )
            return {
                "status": "completed",
                "final_answer": rendered,
                "message": rendered,
                "user_facing": True,
            }
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
                "Respect the user's requested language and format. If source_urls are provided, include the URLs visibly in the final answer. Return only valid JSON matching the schema."
            ),
        }
        payload = {
            "user_message": text,
            "parsed": parsed,
            "intent": intent,
            "plan_contract": plan.get("final_response_contract", {}),
            "execution_material": material,
            "verification": verification or {},
            "source_urls": ((execution.get("evidence") or {}).get("urls") if isinstance(execution.get("evidence"), dict) else []),
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


    def _capability_gap_resolution_artifact(
        self,
        *,
        user_input: str,
        query: str,
        evidence: dict[str, Any],
        material: str,
        run_id: str,
        runtime_implementation: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a generic, non-executing capability implementation record.

        The core does not hard-code a concrete feature.  It records the
        discovered evidence and a safe implementation lifecycle so a runtime
        generated adapter/tool can be created outside ai_core after evidence is
        verified.  If source material is missing, the record is explicitly
        blocked and no implementation is claimed.
        """
        urls = evidence.get("urls") if isinstance(evidence.get("urls"), list) else []
        runtime_impl = runtime_implementation if isinstance(runtime_implementation, dict) else {}
        runtime_status = str(runtime_impl.get("status") or "").strip()
        if runtime_status:
            artifact_status = runtime_status
        elif urls:
            artifact_status = "implementation_candidate_created"
        else:
            artifact_status = "blocked_without_verified_evidence"
        base = {
            "run_id": run_id,
            "status": artifact_status,
            "user_input": str(user_input or ""),
            "resolution_query": query,
            "source_urls": urls,
            "evidence_required": bool(not runtime_status and not urls),
            "safe_execution_policy": "do_not_execute_external_code_without_validation",
            "lifecycle": [
                "resolve_capability_gap",
                "verify_external_evidence",
                "generate_runtime_artifact_outside_ai_core",
                "run_schema_and_unit_validation",
                "register_runtime_capability_candidate",
                "execute_original_request_after_validation",
            ],
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        if runtime_impl:
            base["runtime_implementation"] = runtime_impl
            if isinstance(runtime_impl.get("interaction_request"), dict):
                base["interaction_request"] = runtime_impl["interaction_request"]
        out_dir = RUNTIME_GENERATED / "capability_gap_resolutions"
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
            path = out_dir / f"{run_id}.json"
            path.write_text(json.dumps({**base, "evidence_excerpt": str(material or "")[:4000]}, ensure_ascii=False, indent=2), encoding="utf-8")
            base["artifact_path"] = str(path)
        except Exception as exc:
            base["artifact_write_error"] = exc.__class__.__name__
        return base

    def _capability_gap_answer_material(
        self,
        *,
        user_input: str,
        evidence: dict[str, Any],
        implementation: dict[str, Any],
        material: str,
    ) -> str:
        urls = evidence.get("urls") if isinstance(evidence.get("urls"), list) else []
        runtime_impl = implementation.get("runtime_implementation") if isinstance(implementation.get("runtime_implementation"), dict) else {}
        runtime_status = str(runtime_impl.get("status") or "not_requested")
        if not urls and runtime_status == "not_requested":
            return (
                self._external_retrieval_failure_material(evidence)
                + "\n\nCapability gap status: blocked_without_verified_evidence. No implementation was generated or registered."
            )
        if runtime_status in {"registered", "registered_verified"}:
            headline = "Capability gap resolution completed. Runtime capability was implemented, sandbox-tested, registered, and verified by execution."
        elif runtime_status in {"code_generation_failed", "planner_failed", "planner_low_confidence"}:
            headline = "Capability acquisition reached runtime code generation, but no registerable implementation artifact was produced."
        elif runtime_status in {"blocked", "generated_but_validation_failed"}:
            headline = "Capability gap resolution collected verified material, but implementation was not registered."
        elif runtime_status in {"sandbox_failed", "not_registered", "generated_but_verification_failed"}:
            headline = "Capability acquisition generated an artifact, but sandbox validation or registration gate blocked it."
        else:
            headline = "Capability gap resolution completed with verified external material; implementation was not requested or no matching runtime template was available."
        lines = [
            headline,
            "",
            "Implementation lifecycle:",
        ]
        for item in implementation.get("lifecycle", []):
            lines.append(f"- {item}")
        lines.append("")
        lines.append("Resolution artifact:")
        lines.append(str(implementation.get("artifact_path") or "runtime_generated_candidate_record"))
        lines.append("")
        if runtime_impl:
            lines.append("Runtime implementation status:")
            lines.append(f"- status: {runtime_status}")
            artifact = runtime_impl.get("artifact") if isinstance(runtime_impl.get("artifact"), dict) else {}
            validation = runtime_impl.get("validation") if isinstance(runtime_impl.get("validation"), dict) else {}
            registration = runtime_impl.get("registration") if isinstance(runtime_impl.get("registration"), dict) else {}
            if artifact.get("tool_dir"):
                lines.append(f"- artifact_dir: {artifact.get('tool_dir')}")
            if validation:
                lines.append(f"- sandbox_validation_passed: {bool(validation.get('passed'))}")
            if registration:
                lines.append(f"- registry_path: {registration.get('registry_path')}")
                tool_record = registration.get("tool_record") if isinstance(registration.get("tool_record"), dict) else {}
                if isinstance(tool_record.get("connection_schema"), dict) and tool_record.get("connection_schema"):
                    lines.append("- configuration_ui: Agent Studio Runtime Registry -> Configure profile")
                if isinstance(tool_record.get("secret_schema"), dict) and tool_record.get("secret_schema"):
                    lines.append("- secret_ui: Agent Studio Runtime Registry -> Configure profile -> Secret values")
                if isinstance(tool_record.get("approval_policy"), dict) and tool_record.get("approval_policy", {}).get("required"):
                    lines.append("- approval_ui: Agent Studio Run registered tool -> confirmation preview")
            reason = runtime_impl.get("reason") or runtime_impl.get("diagnosis")
            if reason:
                lines.append(f"- reason: {str(reason)[:1000]}")
            if isinstance(runtime_impl.get("interaction_request"), dict):
                request = runtime_impl["interaction_request"]
                fields = request.get("fields") if isinstance(request.get("fields"), list) else []
                lines.append("- live_verification: waiting_for_user_runtime_values")
                if fields:
                    lines.append(f"- live_verification_fields: {len(fields)}")
            lines.append("")
        lines.append("Source URLs:")
        for url in urls:
            lines.append(f"- {url}")
        if material:
            lines.append("\nEvidence summary material:")
            lines.append(material)
        return "\n".join(lines).strip()


    def _implementation_requested(self, text: str) -> bool:
        value = " " + str(text or "").strip().casefold() + " "
        if re.search(r"\bacquire\s+runtime\s+capability\b", value, flags=re.I):
            return True
        markers = (
            " acquire runtime capability ", " capability acquisition ", " acquire capability ",
            " generate implementation ", " generate tests ", " verify capability acquisition ",
            " implement ", " build ", " generate ", " create capability ", " add support ",
            " register ", "实装", "实现", "生成", "注册", "構築", "実装", "登録",
        )
        return any(marker in value for marker in markers)

    def _external_retrieval_failure_material(self, evidence: dict[str, Any]) -> str:
        attempts = evidence.get("attempts") if isinstance(evidence.get("attempts"), list) else []
        lines = [
            "External information was required, but no verified source material was retrieved.",
            "The workflow stopped before implementation to avoid generating or registering an unsupported capability.",
        ]
        query = str(evidence.get("query") or "").strip()
        if query:
            lines.append(f"Query: {query}")
        if attempts:
            lines.append("Retrieval attempts:")
            for attempt in attempts[:5]:
                if isinstance(attempt, dict):
                    provider = str(attempt.get("provider") or "retrieval")
                    status = str(attempt.get("status") or "unknown")
                    error = str(attempt.get("error") or "")[:300]
                    lines.append(f"- {provider}: {status}" + (f" ({error})" if error else ""))
        return "\n".join(lines).strip()

    def _selected_step(self, plan: dict[str, Any]) -> dict[str, Any]:
        steps = plan.get("planned_steps") if isinstance(plan.get("planned_steps"), list) else []
        selected: dict[str, Any] = {}
        for step in steps:
            if isinstance(step, dict) and step.get("execution_ready", True):
                selected = dict(step)
                break
        locked = plan.get("locked_execution") if isinstance(plan.get("locked_execution"), dict) else {}
        if locked:
            # workflow_planning is the only layer allowed to lock execution.
            # execution/result_verification must obey it even if an LLM-produced
            # planned step is incomplete or inconsistent.
            selected.update({k: v for k, v in locked.items() if v is not None})
        return selected

    def _result_verification(self, execution: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
        selected = self._selected_step(plan)
        expects_web = str(selected.get("execution_method") or "") == "web_search" or str(selected.get("capability") or "") == "web_retrieval"
        evidence = execution.get("evidence") if isinstance(execution.get("evidence"), dict) else {}
        urls = evidence.get("urls") if isinstance(evidence.get("urls"), list) else []
        runtime_impl = None
        capability_impl = execution.get("capability_implementation") if isinstance(execution.get("capability_implementation"), dict) else {}
        if isinstance(capability_impl, dict):
            runtime_impl = capability_impl.get("runtime_implementation") if isinstance(capability_impl.get("runtime_implementation"), dict) else None
        evidence_verification = evidence.get("verification") if isinstance(evidence.get("verification"), dict) else {}
        passed = bool(execution.get("answer_material")) and (not expects_web or (bool(urls) and bool(evidence_verification.get("passed"))))
        if runtime_impl and runtime_impl.get("status") in {
            "sandbox_failed",
            "not_registered",
            "generated_but_validation_failed",
            "generated_but_verification_failed",
            "dependency_resolution_failed",
            "code_generation_failed",
            "planner_failed",
            "planner_low_confidence",
            "evidence_missing",
        }:
            passed = False
        return {
            "status": "completed" if passed else "failed",
            "passed": passed,
            "expected_execution_method": selected.get("execution_method") or "model_response",
            "actual_execution_mode": execution.get("execution_mode"),
            "expected_capability": selected.get("capability") or "stable_synthesis",
            "actual_capability": execution.get("capability") or execution.get("execution_mode"),
            "evidence_required": expects_web,
            "evidence_present": bool(urls),
            "source_count": len(urls),
            "source_urls": urls,
            "capability_gap_resolution": bool(execution.get("capability_gap_resolution")),
            "runtime_implementation_status": runtime_impl.get("status") if runtime_impl else "not_applicable",
            "runtime_capability_registered": bool((runtime_impl or {}).get("registration")),
            "safe_implementation_policy": "external_code_not_executed_without_validation" if execution.get("capability_gap_resolution") else "not_applicable",
        }

    def _verify_web_evidence(self, user_input: str, search: dict[str, Any], fetched: list[dict[str, Any]], *, min_sources: int = 1) -> dict[str, Any]:
        """Generic evidence verification for web retrieval.

        The verifier is domain-neutral but strict: a web answer may proceed only
        when fetched source text is relevant to the user's concrete request.  It
        requires distinctive request anchors (proper nouns, product/library
        names, place names, codes, or long technical tokens) to appear in the
        source text when such anchors exist.  This prevents unrelated search
        hits from passing merely because they contain generic words such as
        "latest", "version", "official", or "source".
        """
        results = search.get("results") if isinstance(search.get("results"), list) else []
        fetched_docs = [d for d in fetched if isinstance(d, dict) and d.get("status") == "success"]
        terms = self._query_terms(user_input)
        anchors = self._evidence_anchor_terms(user_input)
        meta_terms = self._evidence_meta_terms(user_input)

        by_url: dict[str, dict[str, Any]] = {}
        for item in results:
            if isinstance(item, dict) and item.get("url"):
                by_url.setdefault(str(item.get("url")), {}).update({
                    "url": str(item.get("url") or ""),
                    "title": str(item.get("title") or ""),
                    "snippet": str(item.get("snippet") or ""),
                })
        for doc in fetched_docs:
            url = str(doc.get("url") or "").strip()
            if not url:
                continue
            current = by_url.setdefault(url, {"url": url})
            current.update({
                "title": str(doc.get("title") or current.get("title") or ""),
                "text": " ".join(str(x or "") for x in [
                    current.get("snippet"),
                    doc.get("text_excerpt"),
                    doc.get("visible_text_excerpt"),
                    doc.get("dom_evidence_text"),
                ]),
                "fetched": True,
            })

        verified_sources: list[dict[str, Any]] = []
        rejected_sources: list[dict[str, Any]] = []
        for url, item in by_url.items():
            text = " ".join(str(x or "") for x in [item.get("title"), item.get("snippet"), item.get("text")])
            folded = text.casefold()
            matched_anchors = [a for a in anchors if a.casefold() in folded]
            matched_terms = [t for t in terms if t.casefold() in folded]
            matched_meta = [t for t in meta_terms if t.casefold() in folded]
            has_fetched_text = bool(item.get("fetched")) and len(str(item.get("text") or "").strip()) >= 80
            has_factual_material = bool(re.search(r"\d|°|%|[A-Za-z]{3,}|[\u3040-\u30ff\u3400-\u9fff]{2,}", text))
            anchor_required = bool(anchors)
            anchor_passed = bool(matched_anchors) if anchor_required else bool(matched_terms)
            # Require at least one non-anchor/meta term when possible, but keep
            # short entity-only questions workable.
            non_anchor_terms = [t for t in terms if t not in anchors and t not in meta_terms]
            term_passed = bool(set(matched_terms).intersection(non_anchor_terms)) if non_anchor_terms else bool(matched_terms or matched_anchors)
            passed_source = bool(has_fetched_text and has_factual_material and anchor_passed and term_passed)
            record = {
                "url": url,
                "title": str(item.get("title") or "")[:300],
                "matched_anchors": matched_anchors,
                "matched_terms": matched_terms[:12],
                "matched_meta_terms": matched_meta[:12],
                "has_fetched_text": has_fetched_text,
                "has_factual_material": has_factual_material,
            }
            if passed_source:
                verified_sources.append(record)
            else:
                rejected_sources.append({**record, "reason": "source_text_not_relevant_to_request_anchors"})

        required_count = max(1, int(min_sources or 1))
        passed = len(verified_sources) >= required_count
        return {
            "status": "passed" if passed else "failed",
            "passed": passed,
            "min_sources": required_count,
            "candidate_source_count": len([x for x in results if isinstance(x, dict) and x.get("url")]),
            "fetched_source_count": len(fetched_docs),
            "verified_source_count": len(verified_sources),
            "verified_sources": verified_sources,
            "verified_urls": [x["url"] for x in verified_sources],
            "rejected_sources_sample": rejected_sources[:5],
            "anchor_terms": anchors,
            "query_terms_sample": terms,
            "meta_terms": meta_terms,
            "reason": "verified_fetched_source_text_matches_request_anchors" if passed else "no_verified_fetched_source_text_matched_request_anchors",
        }

    def _evidence_anchor_terms(self, text: str) -> list[str]:
        """Extract distinctive request anchors without domain-specific rules."""
        raw = str(text or "")
        tokens = re.findall(r"[A-Za-z][A-Za-z0-9_+.#/-]{2,}|[A-Z]{2,}|[\u3040-\u30ff\u3400-\u9fff]{2,}", raw)
        stop = {
            "what", "which", "when", "where", "who", "why", "how", "the", "and", "for", "with", "from", "that", "this",
            "latest", "newest", "current", "recent", "version", "versions", "official", "source", "sources", "provide",
            "search", "find", "information", "today", "tomorrow", "city", "date",
        }
        anchors: list[str] = []
        for token in tokens:
            clean = token.strip(" .,:;()[]{}<>\"'`")
            if not clean or clean.casefold() in stop:
                continue
            # Prefer distinctive tokens: mixed case, all caps, contains digits or
            # separators, non-Latin terms, or long uncommon words.
            distinctive = (
                bool(re.search(r"[A-Z].*[a-z]|[a-z].*[A-Z]", clean))
                or clean.isupper()
                or bool(re.search(r"[0-9_+.#/-]", clean))
                or bool(re.search(r"[\u3040-\u30ff\u3400-\u9fff]", clean))
                or len(clean) >= 6
            )
            if distinctive and clean not in anchors:
                anchors.append(clean)
            if len(anchors) >= 8:
                break
        if not anchors:
            # Fall back to the longest content terms when no obvious named
            # entity exists.  This remains generic and avoids business keywords.
            candidates = [t for t in self._query_terms(raw) if t.casefold() not in stop]
            for term in sorted(candidates, key=len, reverse=True):
                if term not in anchors:
                    anchors.append(term)
                if len(anchors) >= 3:
                    break
        return anchors

    def _evidence_meta_terms(self, text: str) -> list[str]:
        raw_terms = re.findall(r"[A-Za-z0-9_\-]+", str(text or "").casefold())
        meta_vocab = {
            "latest", "newest", "current", "recent", "version", "versions", "official", "source", "sources",
            "citation", "citations", "reference", "references", "verify", "verified", "update", "updated",
        }
        out: list[str] = []
        for term in raw_terms:
            if term in meta_vocab and term not in out:
                out.append(term)
        return out

    async def _web_answer_material(self, user_input: str, search: dict[str, Any], fetched: list[dict[str, Any]], run_id: str) -> str:
        """Create concise user-facing material from web evidence.

        The runtime must keep raw source excerpts in traces/evidence, but the
        final answer should be easy to read.  This method is intentionally
        domain-neutral: it does not know what the user asked about.  It asks the
        model to answer from retrieved text fields and falls back to compact
        snippet bullets when the model is unavailable.
        """
        results = search.get("results") if isinstance(search.get("results"), list) else []
        urls = []
        for item in results[:8]:
            if isinstance(item, dict) and item.get("url"):
                url = str(item.get("url") or "").strip()
                if url and url not in urls:
                    urls.append(url)

        evidence_cards: list[dict[str, str]] = []
        for item in results[:5]:
            if isinstance(item, dict):
                evidence_cards.append({
                    "title": str(item.get("title") or item.get("url") or "source")[:240],
                    "url": str(item.get("url") or "")[:500],
                    "text": " ".join(str(item.get("snippet") or "").split())[:900],
                })
        for doc in fetched[:5]:
            if isinstance(doc, dict):
                evidence_cards.append({
                    "title": str(doc.get("title") or doc.get("url") or "source")[:240],
                    "url": str(doc.get("url") or "")[:500],
                    "text": " ".join(str(doc.get("text_excerpt") or doc.get("visible_text_excerpt") or doc.get("snippet") or "").split())[:1500],
                })
        extracted_records = self.content_extractor.extract(fetched_documents=fetched, max_records=40)
        for rec in extracted_records[:20]:
            if isinstance(rec, dict):
                evidence_cards.append({
                    "title": str(rec.get("title") or rec.get("source_title") or rec.get("url") or "source")[:240],
                    "url": str(rec.get("url") or rec.get("source_url") or "")[:500],
                    "text": " ".join(str(rec.get("text") or "").split())[:1500],
                })

        relevance = self.source_relevance_selector.select(
            user_input=user_input,
            source_cards=evidence_cards,
            max_sources=5,
            min_score=0.28,
        )
        selected_cards = relevance.get("selected_sources") if isinstance(relevance.get("selected_sources"), list) else []
        selected_urls = relevance.get("selected_urls") if isinstance(relevance.get("selected_urls"), list) else []
        if not selected_cards:
            normalized = self.evidence_normalizer.normalize(user_input=user_input, source_cards=evidence_cards)
            resolved = self.claim_resolver.resolve(user_input=user_input, normalized_evidence=normalized)
            plan = self.answer_planner.plan(user_input=user_input, resolved_claims=resolved)
            return self.answer_planner.render(plan)

        normalized = self.evidence_normalizer.normalize(user_input=user_input, source_cards=selected_cards)
        resolved = self.claim_resolver.resolve(user_input=user_input, normalized_evidence=normalized)
        plan = self.answer_planner.plan(user_input=user_input, resolved_claims=resolved)
        fallback_answer = self.answer_planner.render(plan)

        schema = {
            "type": "object",
            "required": ["answer"],
            "properties": {
                "answer": {"type": "string"},
                "used_source_urls": {"type": "array", "items": {"type": "string"}},
                "confidence": {"type": "string"},
            },
            "additionalProperties": True,
        }
        prompt = {
            "id": "web_evidence_user_answer_synthesis",
            "system": (
                "Answer the user's question using only the provided retrieved source text fields. "
                "Do not dump raw excerpts. Keep the answer concise and easy to understand. "
                "If the requested facts are not clearly supported, say that the evidence is insufficient. "
                "Include only the most relevant source URLs at the end. Return only valid JSON matching the schema."
            ),
        }
        payload = {
            "user_message": user_input,
            "retrieved_source_text_fields": selected_cards[:8],
            "source_urls": selected_urls[:8],
            "output_style": {
                "summary_first": True,
                "avoid_raw_excerpts": True,
                "max_user_visible_sources": 5,
                "must_use_selected_sources_only": True,
            },
        }
        synthesized = await self._json_stage(
            run_id,
            "web_evidence_user_answer_synthesis",
            prompt,
            json.dumps(payload, ensure_ascii=False),
            schema,
            fallback={"answer": fallback_answer, "used_source_urls": selected_urls[:5], "confidence": "fallback"},
        )
        answer = str(synthesized.get("answer") or "").strip()
        used_source_urls = [str(u).strip() for u in synthesized.get("used_source_urls", []) if str(u).strip()] if isinstance(synthesized, dict) else []
        confidence = str(synthesized.get("confidence") or "").casefold() if isinstance(synthesized, dict) else ""
        allowed_urls = {str(u) for u in selected_urls}
        used_selected_urls = [u for u in used_source_urls if u in allowed_urls]

        candidate_claims = self.evidence_claim_ranker.extract_from_materials(selected_cards)
        consistency = self.evidence_claim_ranker.answer_consistent(answer, candidate_claims) if answer else {"passed": False}

        # Hard grounding gate: generated answers may pass only when they cite at
        # least one selected source, are not marked insufficient, and do not
        # contradict stronger comparable evidence from the selected sources.
        plan_ready = isinstance(plan, dict) and plan.get("status") == "ready"
        generated_grounded = bool(plan_ready and answer and used_selected_urls and confidence not in {"insufficient", "low", "none"} and consistency.get("passed") is True)
        if not generated_grounded:
            answer = fallback_answer

        quality = self.answer_quality_gate.evaluate(answer=answer, answer_plan=plan, resolved_claims=resolved)
        if quality.get("passed") is not True:
            answer = self.answer_planner.render(plan)

        # Keep source visibility bound to selected relevant sources only.
        if selected_urls and not any(str(u) in answer for u in selected_urls[:3]):
            answer = answer.rstrip() + "\n\nSources:\n" + "\n".join(f"- {u}" for u in selected_urls[:5])
        return answer.strip()

    def _compact_web_evidence_material(self, user_input: str, evidence_cards: list[dict[str, str]], urls: list[str], relevance: dict[str, Any] | None = None) -> str:
        """Fallback material that is readable without model synthesis.

        It selects short evidence snippets from generic text fields instead of
        printing full fetched pages.  No domain-specific keywords are used.
        """
        terms = self._query_terms(user_input)
        scored: list[tuple[int, dict[str, str]]] = []
        for card in evidence_cards:
            text = " ".join(str(card.get("text") or "").split())
            haystack = (str(card.get("title") or "") + " " + text).casefold()
            score = sum(1 for term in terms if term and term in haystack)
            if re.search(r"\d", text):
                score += 1
            scored.append((score, card))
        scored.sort(key=lambda x: x[0], reverse=True)
        lines = ["I found source material, but could not confidently synthesize a final answer automatically.", "", "Most relevant extracted text fields:"]
        if relevance is not None and relevance.get("passed") is False:
            lines.insert(1, "No candidate source passed the query relevance gate.")
        kept = 0
        for score, card in scored[:4]:
            text = " ".join(str(card.get("text") or "").split())[:420]
            title = str(card.get("title") or card.get("url") or "source").strip()
            url = str(card.get("url") or "").strip()
            if not text and not title:
                continue
            kept += 1
            lines.append(f"- {title}" + (f" ({url})" if url else ""))
            if text:
                lines.append(f"  {text}")
        if not kept:
            lines.append("- No compact text field was available from the fetched pages.")
        if urls:
            lines.append("")
            lines.append("Sources:")
            for url in urls[:5]:
                lines.append(f"- {url}")
        return "\n".join(lines).strip()

    def _query_terms(self, text: str) -> list[str]:
        raw_terms = re.findall(r"[A-Za-z0-9_\-]+|[\u3040-\u30ff\u3400-\u9fff]+", str(text or "").casefold())
        stop = {
            "the", "and", "for", "with", "from", "that", "this", "please", "including", "information",
            "について", "ください", "お願いします", "查询", "搜索", "信息", "内容",
        }
        terms: list[str] = []
        for term in raw_terms:
            if len(term) < 2 or term in stop:
                continue
            if term not in terms:
                terms.append(term)
        return terms[:20]


    def _generic_capability_terms(self, text: str) -> list[str]:
        """Extract neutral implementation terms from a request.

        This helper is intentionally generic: it removes common orchestration
        words and keeps compact technical nouns/phrases that can be used for
        evidence retrieval. It must not encode any concrete capability domain.
        """
        raw = str(text or "")
        tokens = re.findall(r"[A-Za-z][A-Za-z0-9_+.#/-]{1,}|[\u3040-\u30ff\u3400-\u9fff]{2,}", raw)
        stop = {
            "runtime", "capability", "acquire", "create", "generate", "register",
            "implementation", "constraints", "schema", "secret", "connection",
            "approval", "policy", "sandbox", "validation", "verify", "verified",
            "complete", "only", "after", "prefer", "language", "complexity",
            "store", "values", "through", "local", "system", "using", "with",
            "without", "should", "must", "required", "please", "user", "mode",
        }
        terms: list[str] = []
        for token in tokens:
            clean = token.strip(" .,:;()[]{}<>\"'`")
            if not clean:
                continue
            low = clean.casefold()
            if low in stop or len(clean) < 2:
                continue
            if clean not in terms:
                terms.append(clean)
            if len(terms) >= 20:
                break
        return terms

    def _direct_conversation_signal(self, text: str) -> str:
        """Return a neutral direct-chat reason when no runtime action is requested.

        This is a structural guard, not a business/domain route.  It protects
        short interpersonal messages, language preference/capability questions,
        and simple conversational turns from being escalated into capability
        acquisition when the user has not asked to create or operate a runtime
        tool.
        """
        raw = str(text or "").strip()
        if not raw:
            return ""
        value = " " + re.sub(r"\s+", " ", raw).casefold() + " "
        if self._external_information_signals(raw) or self._generic_capability_gap_signal(raw):
            return ""
        if len(raw) <= 180 and not re.search(r"\b(create|acquire|register|implement|install|integrate|configure|generate code|fix|execute|run|schedule|send|download|upload|delete|update)\b", value):
            question_like = "?" in raw or re.search(r"\b(can|could|would|do|are|is|what|who|where|when|why|how)\b", value)
            assistant_reference = re.search(r"\b(you|your|assistant|chatgpt|model|speak|language|conversation|talk)\b", value)
            social_or_short = len(raw.split()) <= 12
            if question_like and assistant_reference:
                return "direct_conversation_or_assistant_capability_question"
            if social_or_short and re.search(r"[A-Za-z\u3040-\u30ff\u3400-\u9fff]", raw):
                return "simple_conversation"
        return ""

    def _generic_external_signal(self, text: str) -> bool:
        return bool(self._external_information_signals(text) or self._generic_capability_gap_signal(text))

    def _external_information_signals(self, text: str) -> list[str]:
        # Generic recency/source-demand signals only. They are not tied to any
        # business domain or concrete task provider.
        value = " " + str(text or "").strip().casefold() + " "
        signals: list[str] = []
        if re.search(r"https?://", value):
            signals.append("external_source_required")
        marker_groups = {
            "freshness_required": (" latest ", " newest ", " current ", " recent ", " today ", " now ", " stable ", " version ", "最新", "現在", "最近", "今日", "今", "版本", "当前"),
            "external_source_required": (" search ", " look up ", " lookup ", " web ", " internet ", " browse ", "検索", "調べ", "搜索", "检索", "查询", "网页"),
            "evidence_required": (" official ", " source ", " url ", " citation ", " reference ", " documentation ", " docs ", "公式", "出典", "引用", "参照", "官方", "来源", "网址", "文档"),
            "verification_required": (" verify ", " check ", " confirm ", " compare ", " validate ", "確認", "検証", "比較", "核实", "确认", "验证", "比较"),
        }
        for signal, markers in marker_groups.items():
            if any(marker in value for marker in markers) and signal not in signals:
                signals.append(signal)
        return signals

    def _generic_capability_gap_signal(self, text: str) -> bool:
        # Generic self-extension signal: the user is asking the runtime to find
        # a way to handle or implement an operation rather than merely answer.
        value = " " + str(text or "").strip().casefold() + " "
        if re.search(r"\bacquire\s+runtime\s+capability\b", value, flags=re.I):
            return True
        if re.search(r"\bruntime\s+capability\b", value, flags=re.I) and re.search(r"\b(acquire|create|generate|register|implement|build)\b", value, flags=re.I):
            return True
        action_markers = (
            " acquire runtime capability ", " runtime capability ", " capability acquisition ",
            " acquire capability ", " generate implementation ", " generate tests ",
            " register capability ", " verify capability acquisition ",
            " implement ", " add support ", " support ", " integrate ", " install ",
            " configure ", " generate code ", " fix ", " cannot handle ", " unable to ",
            " not supported ", " how to build ", " how to create ", " how to implement ",
            "実装", "対応", "導入", "構築", "修正", "できない", "サポート",
            "实现", "实装", "支持", "接入", "集成", "安装", "配置", "修复", "无法处理", "不能处理", "怎么实现",
        )
        discovery_markers = (
            " find a solution ", " solution ", " method ", " approach ", " guide ",
            " documentation ", " example ", "按照说明", "解决办法", "处理方法", "方法", "说明", "参考",
            "解決方法", "手順", "ガイド", "参考",
        )
        has_action = any(marker in value for marker in action_markers)
        has_discovery = any(marker in value for marker in discovery_markers)
        return bool(has_action and (has_discovery or self._external_information_signals(text)))

    def _capability_gap_query(self, text: str) -> str:
        """Build a compact evidence query for capability acquisition.

        The full user request can contain UI/storage/validation constraints.
        Sending that whole text to a web search adapter often produces a 200
        response with zero kept results.  This method keeps the logic generic:
        it extracts neutral capability terms and appends evidence-purpose terms.
        Concrete implementation remains in runtime planners/templates.
        """
        raw = str(text or "").strip()
        folded = raw.casefold()
        terms: list[str] = []
        for line in raw.splitlines():
            clean = re.sub(r"[^A-Za-z0-9_+.#/-]+", " ", line).strip()
            if not clean:
                continue
            low = clean.casefold()
            if any(marker in low for marker in ("capability", "runtime", "constraints", "complete only", "schema", "registry", "sandbox")):
                continue
            if len(clean) <= 80:
                terms.append(clean)
        if not terms:
            terms = self._generic_capability_terms(raw)[:6]
        base = " ".join(terms[:8]).strip()
        if not base:
            base = "runtime capability implementation"
        purpose = "official documentation implementation guide example validation"
        return (base + " " + purpose).strip()[:300]

    async def _direct_answer(self, text: str, parsed: dict[str, Any], intent: dict[str, Any], context: dict[str, Any], plan: dict[str, Any], run_id: str) -> str:
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
            "session_context": context.get("session_context", {}) if isinstance(context, dict) else {},
            "retrieved_context": context.get("retrieved_context", []) if isinstance(context, dict) else [],
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

    def _stage_llm_limits(self, node_id: str) -> dict[str, int | float]:
        """Small per-stage budgets for weak local machines.

        Environment variables may override these values, but defaults are short
        by design so the browser/API request is not held by a slow local model.
        """
        node = str(node_id or "")
        defaults = {
            "conversation_input_parsing": {"timeout_seconds": 3.0, "max_prompt_tokens": 180, "max_prompt_chars": 900, "max_schema_chars": 500, "num_predict": 96, "num_ctx": 768},
            "conversation_intent_recognition": {"timeout_seconds": 8.0, "max_prompt_tokens": 320, "max_prompt_chars": 1400, "max_schema_chars": 900, "num_predict": 160, "num_ctx": 1024},
            "conversation_knowledge_evaluation": {"timeout_seconds": 8.0, "max_prompt_tokens": 340, "max_prompt_chars": 1500, "max_schema_chars": 900, "num_predict": 180, "num_ctx": 1024},
            "conversation_workflow_planning": {"timeout_seconds": 12.0, "max_prompt_tokens": 420, "max_prompt_chars": 1600, "max_schema_chars": 1000, "num_predict": 220, "num_ctx": 1536},
            "conversation_execution_response": {"timeout_seconds": 15.0, "max_prompt_tokens": 520, "max_prompt_chars": 2200, "max_schema_chars": 800, "num_predict": 320, "num_ctx": 2048},
            "conversation_output": {"timeout_seconds": 8.0, "max_prompt_tokens": 360, "max_prompt_chars": 1600, "max_schema_chars": 600, "num_predict": 220, "num_ctx": 1536},
            "web_evidence_user_answer_synthesis": {"timeout_seconds": 15.0, "max_prompt_tokens": 600, "max_prompt_chars": 2600, "max_schema_chars": 700, "num_predict": 360, "num_ctx": 2048},
        }
        base = dict(defaults.get(node, {"timeout_seconds": 15.0, "max_prompt_tokens": 500, "max_prompt_chars": 2000, "max_schema_chars": 900, "num_predict": 300, "num_ctx": 2048}))
        prefix = "AI_CORE_STAGE_" + re.sub(r"[^A-Z0-9]+", "_", node.upper()).strip("_")
        for key in list(base.keys()):
            env = os.environ.get(prefix + "_" + key.upper()) or os.environ.get("AI_CORE_STAGE_" + key.upper())
            if env is None or str(env).strip() == "":
                continue
            try:
                base[key] = float(env) if key == "timeout_seconds" else int(float(env))
            except Exception:
                pass
        return base

    def _compact_stage_payload(self, node_id: str, payload: str, limit: int | float) -> str:
        limit_int = max(200, int(limit or 1600))
        text = str(payload or "")
        if len(text) <= limit_int:
            return text
        try:
            obj = json.loads(text)
        except Exception:
            return text[: max(0, limit_int - 28)] + "\n...[stage_payload_compacted]"
        node = str(node_id or "")
        if node == "conversation_workflow_planning":
            compact = {
                "intent": self._compact_value(obj.get("intent") if isinstance(obj, dict) else {}, max_depth=2, max_items=12),
                "parsed": self._compact_value(obj.get("parsed") if isinstance(obj, dict) else {}, max_depth=1, max_items=8),
                "context_summary": self._compact_value(obj.get("context_summary") if isinstance(obj, dict) else {}, max_depth=1, max_items=6),
                "user_message_excerpt": str((obj or {}).get("user_message") if isinstance(obj, dict) else "")[:700],
            }
        elif node in {"conversation_intent_recognition", "conversation_knowledge_evaluation", "conversation_execution_response", "conversation_output"}:
            compact = self._compact_value(obj, max_depth=2, max_items=10)
        else:
            compact = self._compact_value(obj, max_depth=1, max_items=8)
        out = json.dumps(compact, ensure_ascii=False)
        if len(out) > limit_int:
            out = out[: max(0, limit_int - 28)] + "\n...[stage_payload_compacted]"
        return out

    def _compact_value(self, value: Any, *, max_depth: int = 2, max_items: int = 10) -> Any:
        if max_depth <= 0:
            if isinstance(value, (dict, list)):
                return "...[compact]"
            if isinstance(value, str):
                return value[:500]
            return value
        if isinstance(value, dict):
            out: dict[str, Any] = {}
            for idx, (k, v) in enumerate(value.items()):
                if idx >= max_items:
                    out["_truncated"] = True
                    break
                out[str(k)] = self._compact_value(v, max_depth=max_depth - 1, max_items=max_items)
            return out
        if isinstance(value, list):
            return [self._compact_value(v, max_depth=max_depth - 1, max_items=max_items) for v in value[:max_items]]
        if isinstance(value, str):
            return value[:700]
        return value

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
        stage_limits = self._stage_llm_limits(node_id)
        adapter = self.model_selection.initial_adapter_overrides({
            "adapter_id": node_id + "_adapter",
            "provider_route": [],
            "max_prompt_tokens": stage_limits["max_prompt_tokens"],
            "max_prompt_chars": stage_limits["max_prompt_chars"],
            "provider_timeout_seconds": stage_limits["timeout_seconds"],
            "max_schema_chars": stage_limits["max_schema_chars"],
            "provider_options": {
                "temperature": 0,
                "num_predict": stage_limits["num_predict"],
                "num_ctx": stage_limits["num_ctx"],
                "think": False,
            },
        })
        user_payload = self._compact_stage_payload(node_id, user_payload, stage_limits["max_prompt_chars"])
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

    def _persist_conversation_turn(self, session_id: str, run_id: str, user_input: str, final_answer: str, results: dict[str, Any]) -> None:
        try:
            self.sessions.append_turn(
                session_id=session_id,
                run_id=run_id,
                user_input=user_input,
                final_answer=final_answer,
                stage_results=results,
                metadata={"source": "conversation_core"},
            )
            compact = self._compact_summary_text(user_input, final_answer)
            self.sessions.save_summary(
                session_id=session_id,
                summary_text=compact,
                open_items=[],
                source_run_id=run_id,
            )
            self.vector_memory.add_text(
                text=compact,
                metadata={"session_id": session_id, "run_id": run_id},
                memory_type="conversation_summary",
                usage_scope="retrieval_context",
            )
        except Exception:
            pass

    def _compact_summary_text(self, user_input: str, final_answer: str, *, max_chars: int = 1600) -> str:
        text = "User input:\n" + str(user_input or "").strip() + "\n\nFinal answer:\n" + str(final_answer or "").strip()
        return text[:max_chars]

    def _write_stage_trace(self, run_id: str, stage: str, status: str, payload: dict[str, Any]) -> None:
        try:
            trace_dir = RUNTIME_TRACES / "ai_core_pipeline"
            trace_dir.mkdir(parents=True, exist_ok=True)
            path = trace_dir / (run_id + ".jsonl")
            event = {
                "at": datetime.now(timezone.utc).isoformat(),
                "run_id": run_id,
                "stage": stage,
                "status": status,
                "payload": payload,
            }
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
            snapshot_dir = trace_dir / run_id
            snapshot_dir.mkdir(parents=True, exist_ok=True)
            safe_stage = "".join(c if c.isalnum() or c in {"_", "-"} else "_" for c in stage)
            (snapshot_dir / f"{safe_stage}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        except Exception:
            pass

    def _event(self, state: dict[str, Any], stage: str, status: str) -> None:
        event = {
            "stage": stage,
            "status": status,
            "at": datetime.now(timezone.utc).isoformat(),
        }
        state.setdefault("progress_events", []).append(event)
        try:
            stage_flow = {
                "input_parsing": "ai_core.input_parsing",
                "intent_recognition": "ai_core.intent_interaction",
                "context_awareness": "auxiliary_memory.parameters",
                "workflow_planning": "ai_core.workflow_graph",
                "execution": "runtime.execution",
                "result_verification": "verification.result",
                "final_synthesis": "presentation_brain",
            }.get(stage, "runtime.execution")
            stage_title = {
                "input_parsing": "Input parsing",
                "intent_recognition": "Intent recognition",
                "context_awareness": "Context binding",
                "workflow_planning": "Workflow planning",
                "execution": "Runtime execution",
                "result_verification": "Result verification",
                "final_synthesis": "Final synthesis",
            }.get(stage, stage)
            completed_order = ["input_parsing", "intent_recognition", "context_awareness", "workflow_planning", "execution", "result_verification", "final_synthesis"]
            base = max(5.0, (completed_order.index(stage) / max(1, len(completed_order))) * 100.0) if stage in completed_order else 50.0
            progress = min(99.0, base + (10.0 if status == "running" else 100.0 / max(1, len(completed_order))))
            if status == "completed":
                progress = 100.0
            runtime_state_manager.emit(
                run_id=str(state.get("run_id") or "conversation_runtime"),
                step_id=stage,
                level="developer",
                kind="lifecycle" if status == "running" else "output",
                status="running" if status == "running" else ("completed" if status in {"completed", "needs_review"} else str(status or "running")),
                title=stage_title,
                message=f"{stage_title}: {status}",
                method="ai_core.conversation_pipeline",
                progress=progress,
                trace={"conversation_trace_id": state.get("conversation_trace_id")},
            )
        except Exception:
            pass

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
        # Generic direct-response fallback.  This path must stay outside task,
        # graph, tool, artifact, and workflow execution.  It intentionally avoids
        # phrase lists and scenario-specific routing rules.
        if not text.strip():
            return "Please enter the content you want me to handle."
        return (
            "I am your AI runtime assistant. I can help with conversation, explanation, "
            "writing, planning, code-related work, and runtime tasks when you explicitly ask for them."
        )
