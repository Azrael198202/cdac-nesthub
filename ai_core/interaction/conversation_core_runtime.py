from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import json
import re

from ai_core.config.paths import RUNTIME_TRACES, RUNTIME_GENERATED
from ai_core.context.session_memory_store import SessionMemoryStore
from ai_core.context.vector_memory_store import VectorMemoryStore
from ai_core.knowledge.knowledge_service import KnowledgeService
from ai_core.llm.provider_router import ProviderRouter
from ai_core.research.web_research_tool import GenericWebResearchTool
from ai_core.capabilities.runtime_capability_gap_implementer import RuntimeCapabilityGapImplementer
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
        self.sessions = SessionMemoryStore()
        self.vector_memory = VectorMemoryStore()
        self.web_research = GenericWebResearchTool()
        self.capability_implementer = RuntimeCapabilityGapImplementer()

    async def run(self, message: str, *, latest_task: str | None = None, session_id: str | None = None) -> dict[str, Any]:
        run_id = "conversation_core_" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
        active_session_id = self.sessions.start_or_get_session(session_id, metadata={"latest_task": latest_task or ""})
        context_window = self.sessions.load_context_window(active_session_id)
        state: dict[str, Any] = {
            "run_id": run_id,
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

        self._event(state, "intent_recognition", "running")
        intent = await self._intent_recognition(state["input"], parsed, run_id)
        state["results"]["intent_recognition"] = intent
        self._event(state, "intent_recognition", "completed")

        self._event(state, "context_awareness", "running")
        context = self._context_awareness(state["input"], intent, state.get("context_window", {}))
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

        self._event(state, "result_verification", "running")
        verification = self._result_verification(execution, plan)
        state["results"]["result_verification"] = verification
        self._event(state, "result_verification", "completed" if verification.get("passed") else "needs_review")

        self._event(state, "final_synthesis", "running")
        output = await self._output(state["input"], parsed, intent, context, plan, execution, run_id, verification)
        state["results"]["final_synthesis"] = output
        self._event(state, "final_synthesis", "completed")

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
                "requires_external_information": {"type": "boolean"},
                "required_capabilities": {"type": "array", "items": {"type": "string"}},
                "source_policy": {"type": "object"},
                "external_information_signals": {"type": "array", "items": {"type": "string"}},
                "capability_gap_detected": {"type": "boolean"},
                "capability_gap_reason": {"type": "string"},
                "reason": {"type": "string"},
            },
            "additionalProperties": True,
        }
        prompt = {
            "id": "conversation_intent_recognition",
            "system": (
                "Recognize the user's interaction intent using generic labels only. "
                "Choose whether the message can be answered directly or requires an external runtime action. "
                "Set requires_external_information=true when the answer depends on outside, changing, source-backed, or explicitly requested online material. "
                "Set capability_gap_detected=true when the user is asking the runtime to handle or implement an operation that the current system may not support and external implementation knowledge should be collected first. "
                "Use generic signal names only, such as freshness_required, external_source_required, evidence_required, local_context_insufficient, verification_required, and capability_gap_resolution. "
                "Do not use domain-specific routing rules. Return only valid JSON matching the schema."
            ),
        }
        external_signals = self._external_information_signals(text)
        capability_gap = self._generic_capability_gap_signal(text)
        requires_external = bool(external_signals or capability_gap)
        fallback = {
            "intent_type": "capability_gap_resolution" if capability_gap else "direct_response",
            "confidence": 0.5,
            "response_mode": "external_solution_guidance" if capability_gap else "direct_answer",
            "needs_external_execution": requires_external,
            "requires_external_information": requires_external,
            "required_capabilities": ["web_retrieval"] if requires_external else [],
            "source_policy": {
                "requires_source_material": requires_external,
                "min_sources": 2 if requires_external else 0,
                "external_access": "required" if requires_external else "not_required",
                "trusted_sources_preferred": bool(capability_gap),
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
        requires_external = bool(external_signals or capability_gap or result.get("requires_external_information"))
        if requires_external:
            result["requires_external_information"] = True
            result["needs_external_execution"] = True
            caps = result.get("required_capabilities") if isinstance(result.get("required_capabilities"), list) else []
            if "web_retrieval" not in caps:
                caps.append("web_retrieval")
            result["required_capabilities"] = caps
            policy = result.get("source_policy") if isinstance(result.get("source_policy"), dict) else {}
            policy.setdefault("requires_source_material", True)
            policy.setdefault("min_sources", 2)
            policy.setdefault("external_access", "required")
            if capability_gap:
                policy.setdefault("trusted_sources_preferred", True)
            result["source_policy"] = policy
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

    def _context_awareness(self, text: str, intent: dict[str, Any], context_window: dict[str, Any] | None = None) -> dict[str, Any]:
        kb = self.knowledge.answer_from_knowledge(text)
        vector_hits = self.vector_memory.search(text, limit=5, usage_scope="retrieval_context")
        return {
            "knowledge_available": bool(kb),
            "knowledge_answer": kb if kb else None,
            "knowledge_status": self.knowledge.status(),
            "session_context": context_window or {},
            "retrieved_context": [
                {"text": str(item.get("text") or "")[:1200], "score": item.get("score"), "metadata": item.get("metadata", {})}
                for item in vector_hits
            ],
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
                "If intent.requires_external_information is true, lock execution_method=web_search and capability=web_retrieval in the planned step. "
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
        if intent.get("requires_external_information") or intent.get("needs_external_execution"):
            steps = plan.get("planned_steps") if isinstance(plan.get("planned_steps"), list) else []
            if not steps:
                steps = fallback["planned_steps"]
            for step in steps[:1]:
                if isinstance(step, dict):
                    step["execution_method"] = "web_search"
                    step["capability"] = "web_retrieval"
                    if intent.get("capability_gap_detected"):
                        step["step_type"] = "resolve_capability_gap"
                        step.setdefault("objective", "Collect external implementation guidance for a runtime capability gap.")
                    policy = step.get("source_policy") if isinstance(step.get("source_policy"), dict) else {}
                    policy.setdefault("requires_source_material", True)
                    policy.setdefault("min_sources", 2)
                    step["source_policy"] = policy
            plan["planned_steps"] = steps
            plan["locked_execution"] = {
                "execution_method": "web_search",
                "capability": "web_retrieval",
                "reason": "capability_gap_resolution" if intent.get("capability_gap_detected") else "external_information_required",
            }
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
        if str(selected.get("execution_method") or "") == "web_search" or str(selected.get("capability") or "") == "web_retrieval":
            policy = selected.get("source_policy") if isinstance(selected.get("source_policy"), dict) else {}
            max_results = int(policy.get("max_results") or 5)
            capability_gap = bool(intent.get("capability_gap_detected") or str(selected.get("step_type") or "") == "resolve_capability_gap")
            query = self._capability_gap_query(text) if capability_gap else text
            search = await self.web_research.search(query=query, max_results=max_results)
            evidence_items = search.get("results") if isinstance(search.get("results"), list) else []
            fetched = []
            for item in evidence_items[:max(2, min(max_results, 5))]:
                url = str(item.get("url") or "").strip() if isinstance(item, dict) else ""
                if not url:
                    continue
                doc = await self.web_research.fetch(url=url, max_chars=8000)
                if isinstance(doc, dict) and doc.get("status") == "success":
                    fetched.append(doc)
            material = self._web_answer_material(search, fetched)
            evidence = {
                "query": query,
                "original_user_input": text,
                "search_status": search.get("status"),
                "source_count": len(evidence_items),
                "fetched_count": len(fetched),
                "urls": [str(x.get("url") or "") for x in evidence_items if isinstance(x, dict) and x.get("url")],
                "results": evidence_items,
                "fetched_documents": fetched,
                "attempts": search.get("attempts") if isinstance(search.get("attempts"), list) else [],
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
                if runtime_impl.get("status") == "implemented_tested_registered" and self._policy_backed_runtime_source_needed(evidence):
                    evidence["urls"] = ["runtime-policy://basic-generated-capability-contract"]
                    evidence["source_count"] = 1
                    evidence["source_note"] = "Policy-backed basic acquisition used because external retrieval did not provide source URLs."
                    evidence["policy_backed_basic_acquisition"] = True
                implementation = self._capability_gap_resolution_artifact(
                    user_input=text,
                    query=query,
                    evidence=evidence,
                    material=material,
                    run_id=run_id,
                )
                implementation["runtime_implementation"] = runtime_impl
                material = self._capability_gap_answer_material(
                    user_input=text,
                    evidence=evidence,
                    implementation=implementation,
                    material=material,
                )
            elif not material and not evidence_items:
                material = self._external_retrieval_failure_material(evidence)
            execution_completed = bool(evidence_items or fetched or material or (implementation and isinstance(implementation.get("runtime_implementation"), dict) and implementation["runtime_implementation"].get("status") == "implemented_tested_registered"))
            return {
                "status": "completed" if execution_completed else "blocked_no_external_material",
                "execution_mode": "capability_gap_resolution" if capability_gap else "web_search",
                "capability": "web_retrieval",
                "answer_material": material,
                "external_evidence_used": bool(evidence_items),
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
    ) -> dict[str, Any]:
        """Create a generic, non-executing capability implementation record.

        The core does not hard-code a concrete feature.  It records the
        discovered evidence and a safe implementation lifecycle so a runtime
        generated adapter/tool can be created outside ai_core after evidence is
        verified.  If source material is missing, the record is explicitly
        blocked and no implementation is claimed.
        """
        urls = evidence.get("urls") if isinstance(evidence.get("urls"), list) else []
        base = {
            "run_id": run_id,
            "status": "implementation_candidate_created" if urls else "blocked_without_verified_evidence",
            "user_input": str(user_input or ""),
            "resolution_query": query,
            "source_urls": urls,
            "evidence_required": True,
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
        """Build a concise user-facing capability-acquisition summary.

        Full source excerpts, local paths, lifecycle internals, registry files, and
        traces stay in runtime logs / Agent Studio diagnostics. The final answer
        only states what the user needs: whether the tool was generated, whether
        sandbox validation passed, whether it was registered, and the next action.
        """
        urls = evidence.get("urls") if isinstance(evidence.get("urls"), list) else []
        # Capability-acquisition status is an operational runtime report. Keep it
        # in English so command-driven workflows remain stable even if the
        # surrounding conversation contains CJK feedback or diagnostics.
        lang = "en"
        if not urls:
            return (
                "No verified source material was retrieved, so no tool was generated or registered.\n"
                "Next step: refine the search query, or allow a local policy-backed template and run again."
            )
        runtime_impl = implementation.get("runtime_implementation") if isinstance(implementation.get("runtime_implementation"), dict) else {}
        runtime_status = str(runtime_impl.get("status") or "not_requested")
        validation = runtime_impl.get("validation") if isinstance(runtime_impl.get("validation"), dict) else {}
        verification = runtime_impl.get("verification_run") if isinstance(runtime_impl.get("verification_run"), dict) else {}
        registration = runtime_impl.get("registration") if isinstance(runtime_impl.get("registration"), dict) else {}
        lines: list[str] = []
        if runtime_status in {"implemented_tested_registered", "implemented_tested_registered_verified"}:
            lines.extend(self._localized_capability_summary(lang, "success", source_count=len(urls), registered=True))
        elif runtime_status == "generated_but_validation_failed":
            reason = self._runtime_validation_failure_summary(validation, language=lang)
            lines.extend(self._localized_capability_summary(lang, "validation_failed", reason=reason, source_count=len(urls), registered=False))
        elif runtime_status == "generated_but_verification_failed":
            reason = self._runtime_validation_failure_summary(verification, language=lang)
            lines.extend(self._localized_capability_summary(lang, "verification_failed", reason=reason, source_count=len(urls), registered=False))
        elif runtime_status == "dependency_resolution_failed":
            lines.extend(self._localized_capability_summary(lang, "dependency_failed", source_count=len(urls), registered=False))
        elif runtime_status == "blocked":
            reason = str(runtime_impl.get("reason") or "no safe runtime template matched")
            lines.extend(self._localized_capability_summary(lang, "blocked", reason=reason, source_count=len(urls), registered=False))
        else:
            lines.extend(self._localized_capability_summary(lang, "incomplete", source_count=len(urls), registered=bool(registration)))
        return "\n".join(line for line in lines if line).strip()

    def _user_visible_language(self, text: str) -> str:
        value = str(text or "")
        # Keep this generic: choose Chinese only when the actual user request is
        # predominantly CJK. Capability names or programming-language words must
        # not force Chinese output.
        cjk = sum(1 for ch in value if "\u4e00" <= ch <= "\u9fff")
        ascii_letters = sum(1 for ch in value if ("a" <= ch.lower() <= "z"))
        return "zh" if cjk > 0 and cjk >= max(3, ascii_letters // 3) else "en"

    def _localized_capability_summary(
        self,
        language: str,
        status: str,
        *,
        reason: str = "",
        source_count: int = 0,
        registered: bool = False,
    ) -> list[str]:
        # Capability acquisition is a runtime operation report. Keep it in
        # English to avoid language drift when the original command is English
        # but surrounding user feedback contains another language.
        templates = {
            "success": [
                "Tool generation completed: source retrieval, code generation, sandbox validation, registration, and verification run all passed.",
                "Next step: fill connection settings and secrets in Agent Studio. External side-effect execution still requires user approval.",
            ],
            "validation_failed": [
                "Tool code was generated, but sandbox validation failed, so it was not registered.",
                f"Reason: {reason}",
                "Next step: fix the validation environment or regenerate the code, then rerun validation.",
            ],
            "verification_failed": [
                "Tool code passed basic sandbox checks, but the verification run failed, so it was not registered.",
                f"Reason: {reason}",
                "Next step: fix the tool or runtime configuration according to the verification error, then rerun validation.",
            ],
            "dependency_failed": ["Dependency checks failed before tool generation, so nothing was registered."],
            "blocked": ["Source material was retrieved, but the runtime did not generate a registrable tool.", f"Reason: {reason}"],
            "incomplete": ["Source retrieval completed, but the request did not finish the full registrable-tool lifecycle."],
        }
        lines = list(templates.get(status, templates["incomplete"]))
        if source_count:
            lines.append(f"Verified source count: {source_count}.")
        lines.append("Registration status: registered." if registered else "Registration status: not registered.")
        return lines

    def _runtime_validation_failure_summary(self, validation: dict[str, Any], *, language: str = "en") -> str:
        checks = validation.get("checks") if isinstance(validation.get("checks"), list) else []
        for check in checks:
            if not isinstance(check, dict):
                continue
            if int(check.get("returncode") or 0) == 0:
                continue
            name = str(check.get("name") or "validation").strip() or "validation"
            stderr = str(check.get("stderr") or check.get("error") or "").strip()
            lowered = stderr.casefold()
            if "debugpy" in lowered or "pydevd" in lowered or ".vscode" in lowered:
                interrupted = "keyboardinterrupt" in lowered or int(check.get("returncode") or 0) in {3221225786, -1073741510}
                if interrupted:
                    return (
                        f"{name} subprocess was interrupted during Python startup while IDE/debugger subprocess debugging was active; "
                        "the generated tool code itself was not reached."
                    )
                return (
                    f"{name} started through IDE/debugger subprocess bootstrap instead of a clean isolated Python process; "
                    "the generated tool code itself was not reached."
                )
            if "syntaxerror" in lowered:
                return f"{name} found a syntax error in the generated code."
            if "modulenotfounderror" in lowered:
                return f"{name} found an unavailable module import."
            if stderr:
                compact = " ".join(stderr.split())[:220]
                return f"{name} failed: {compact}"
            return f"{name} returned a non-zero exit code."
        reason = str(validation.get("reason") or "sandbox_validation_failed").strip()
        return reason or "sandbox validation failed."

    def _implementation_requested(self, text: str) -> bool:
        value = " " + str(text or "").strip().casefold() + " "
        markers = (
            " acquire runtime capability ", " capability acquisition ", " acquire capability ",
            " generate implementation ", " generate tests ", " verify capability acquisition ",
            " implement ", " build ", " generate ", " create capability ", " add support ",
            " register ", " current runtime does not have ", " does not have this capability ",
            " missing capability ", " capability gap ", " find a solution ",
            "实装", "实现", "生成", "注册", "構築", "実装", "登録",
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
        policy = selected.get("source_policy") if isinstance(selected.get("source_policy"), dict) else {}
        try:
            min_sources = int(policy.get("min_sources") or (1 if expects_web else 0))
        except Exception:
            min_sources = 1 if expects_web else 0
        min_sources = max(0, min_sources)
        fetched_count = int(evidence.get("fetched_count") or 0) if isinstance(evidence.get("fetched_count"), int) else 0
        policy_backed_runtime_success = bool(
            expects_web
            and evidence.get("policy_backed_basic_acquisition")
            and runtime_impl
            and runtime_impl.get("status") == "implemented_tested_registered"
        )
        source_requirement_met = (
            (not expects_web)
            or policy_backed_runtime_success
            or (len(urls) >= min_sources and (fetched_count > 0 or evidence.get("source_note")))
        )
        passed = bool(execution.get("answer_material")) and source_requirement_met
        failure_reasons: list[str] = []
        if expects_web and not policy_backed_runtime_success and len(urls) < min_sources:
            failure_reasons.append("minimum_source_count_not_met")
        if expects_web and not policy_backed_runtime_success and len(urls) >= min_sources and fetched_count <= 0 and not evidence.get("source_note"):
            failure_reasons.append("source_fetch_not_verified")
        if runtime_impl and runtime_impl.get("status") in {"generated_but_validation_failed", "generated_but_verification_failed", "dependency_resolution_failed"}:
            passed = False
            failure_reasons.append(str(runtime_impl.get("status")))
        return {
            "status": "completed" if passed else "failed",
            "passed": passed,
            "expected_execution_method": selected.get("execution_method") or "model_response",
            "actual_execution_mode": execution.get("execution_mode"),
            "expected_capability": selected.get("capability") or "stable_synthesis",
            "actual_capability": execution.get("capability") or execution.get("execution_mode"),
            "evidence_required": expects_web,
            "evidence_present": bool(urls),
            "minimum_source_count": min_sources,
            "minimum_source_count_met": bool(policy_backed_runtime_success or len(urls) >= min_sources),
            "source_fetch_verified": bool(policy_backed_runtime_success or fetched_count > 0 or evidence.get("source_note") or not expects_web),
            "policy_backed_runtime_source_used": policy_backed_runtime_success,
            "failure_reasons": failure_reasons,
            "source_count": len(urls),
            "source_urls": urls,
            "capability_gap_resolution": bool(execution.get("capability_gap_resolution")),
            "runtime_implementation_status": runtime_impl.get("status") if runtime_impl else "not_applicable",
            "runtime_capability_registered": bool((runtime_impl or {}).get("registration")),
            "safe_implementation_policy": "external_code_not_executed_without_validation" if execution.get("capability_gap_resolution") else "not_applicable",
        }

    def _web_answer_material(self, search: dict[str, Any], fetched: list[dict[str, Any]]) -> str:
        lines = []
        results = search.get("results") if isinstance(search.get("results"), list) else []
        if results:
            lines.append("Source URLs:")
            for item in results[:8]:
                if isinstance(item, dict) and item.get("url"):
                    title = str(item.get("title") or item.get("url") or "").strip()
                    lines.append(f"- {title}: {item.get('url')}")
        if fetched:
            lines.append("\nFetched source excerpts:")
            for doc in fetched[:5]:
                title = str(doc.get("title") or doc.get("url") or "source").strip()
                url = str(doc.get("url") or "").strip()
                excerpt = " ".join(str(doc.get("text_excerpt") or doc.get("snippet") or "").split())[:1800]
                lines.append(f"\n[{title}] {url}\n{excerpt}")
        elif results:
            lines.append("\nSearch snippets:")
            for item in results[:5]:
                if isinstance(item, dict):
                    lines.append("- " + " | ".join(str(item.get(k) or "").strip() for k in ("title", "snippet", "url") if item.get(k)))
        return "\n".join(lines).strip()

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
            "freshness_required": (" latest ", " current ", " recent ", " today ", " now ", " stable ", " version ", "最新", "現在", "最近", "今日", "今", "版本", "当前"),
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
        action_markers = (
            " acquire runtime capability ", " runtime capability ", " capability acquisition ",
            " acquire capability ", " generate implementation ", " generate tests ",
            " register capability ", " verify capability acquisition ",
            " implement ", " add support ", " support ", " integrate ", " install ",
            " configure ", " generate code ", " fix ", " cannot handle ", " unable to ",
            " not supported ", " does not have this capability ", " current runtime does not have ",
            " missing capability ", " capability gap ", " how to build ", " how to create ", " how to implement ",
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

    def _policy_backed_runtime_source_needed(self, evidence: dict[str, Any]) -> bool:
        urls = evidence.get("urls") if isinstance(evidence.get("urls"), list) else []
        return not any(str(url or "").startswith("http://") or str(url or "").startswith("https://") for url in urls)

    def _capability_gap_query(self, text: str) -> str:
        base = str(text or "").strip()
        compact = self._compact_external_research_query(base)
        suffix = "implementation official documentation example safe integration validation"
        lower = compact.casefold()
        if all(token not in lower for token in ("documentation", "docs", "official", "guide", "example")):
            compact = (compact + " " + suffix).strip()
        return compact[:500].strip() or (base[:500].strip() + " " + suffix).strip()

    def _compact_external_research_query(self, text: str) -> str:
        lines = [line.strip(" -\t") for line in str(text or "").splitlines() if line.strip()]
        kept: list[str] = []
        low_value_markers = (
            "acquire runtime capability", "runtime autonomous acquisition", "capability acquisition is complete",
            "implementation generated", "sandbox test passed", "registry updated", "verification run completed",
            "store connection values", "store secret values", "agent studio ui", "local runtime secret store",
            "do not block", "register the capability", "after sandbox validation",
        )
        high_value_markers = (
            "runtime language", "complexity level", "standard library", "prefer ", "official",
            "documentation", "example", "safe integration", "validation", "input schema",
            "connection schema", "secret schema", "approval policy", "dry-run", "mock",
        )
        for line in lines:
            folded = line.casefold()
            if any(marker in folded for marker in low_value_markers):
                continue
            if any(marker in folded for marker in high_value_markers) or len(kept) < 2:
                kept.append(line.rstrip("."))
        query = " ".join(kept)
        query = re.sub(r"\b(Step|Constraints?)\s*:?", " ", query, flags=re.IGNORECASE)
        query = re.sub(r"\s+", " ", query).strip()
        words: list[str] = []
        seen: set[str] = set()
        for word in query.split():
            key = word.casefold().strip(".,:;()[]{}")
            if not key or key in seen:
                continue
            seen.add(key)
            words.append(word)
        return " ".join(words)

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
        # Generic direct-response fallback.  This path must stay outside task,
        # graph, tool, artifact, and workflow execution.  It intentionally avoids
        # phrase lists and scenario-specific routing rules.
        if not text.strip():
            return "Please enter the content you want me to handle."
        return (
            "I am your AI runtime assistant. I can help with conversation, explanation, "
            "writing, planning, code-related work, and runtime tasks when you explicitly ask for them."
        )
