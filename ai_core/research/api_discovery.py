from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from ai_core.config.loader import ConfigLoader
from ai_core.config.paths import RUNTIME_CONFIGS, RUNTIME_GENERATED, RUNTIME_TRACES
from ai_core.events.event_bus import event_bus
from ai_core.llm.provider_router import ProviderRouter
from ai_core.research.web_research_tool import GenericWebResearchTool
from ai_core.research.endpoint_verifier import EndpointVerifier
from ai_core.execution.answer_sufficiency_evaluator import AnswerSufficiencyEvaluator
from ai_core.utils.safe_json import safe_json_dumps


class ApiDiscoveryEngine:
    """Domain-neutral runtime API discovery and documentation understanding.

    The engine does not contain business/API-provider knowledge. It only builds
    a generic discovery package from the runtime request, searches the public
    web for documentation evidence, fetches candidate documents, and asks the
    configured runtime intelligence route to select and understand an API.
    """

    def __init__(self) -> None:
        self.loader = ConfigLoader()
        self.provider_router = ProviderRouter()
        self.web = GenericWebResearchTool()
        self.endpoint_verifier = EndpointVerifier()
        self.answer_sufficiency = AnswerSufficiencyEvaluator()
        self.request_dir = RUNTIME_GENERATED / "api_discovery_requests"
        self.trace_dir = RUNTIME_TRACES / "api_discovery"
        self.request_dir.mkdir(parents=True, exist_ok=True)
        self.trace_dir.mkdir(parents=True, exist_ok=True)

    async def discover(
        self,
        *,
        run_id: str,
        node_id: str,
        capability: str,
        step: dict[str, Any],
        user_input: str,
    ) -> dict[str, Any]:
        request = self._build_request(capability=capability, step=step, user_input=user_input)
        request_path = self.request_dir / f"{request['request_id']}.json"
        request_path.write_text(json.dumps(request, ensure_ascii=False, indent=2), encoding="utf-8")

        await event_bus.emit(run_id, {
            "type": "API_DISCOVERY_STARTED",
            "title": "API discovery started",
            "message": f"Discovering runtime API documentation for capability={capability}",
            "node_id": node_id,
            "result": {"request_id": request["request_id"], "request_path": str(request_path)},
        })

        web_evidence = await self._collect_web_evidence(run_id=run_id, node_id=node_id, request=request)
        request["web_evidence"] = web_evidence

        if request.get("request_mode") == "answer_lookup":
            sufficiency = self._evaluate_answer_sufficiency(web_evidence, request)
            await self._emit_answer_sufficiency(run_id, node_id, sufficiency, stage="web_search")
            if sufficiency.get("passed"):
                discovery = self._finalize_answer_sufficient(
                    request=request,
                    web_evidence=web_evidence,
                    documentation_evidence=[],
                    sufficiency=sufficiency,
                    strategy="web_search_answer_sufficiency",
                )
                await self._emit_done(run_id, node_id, discovery)
                return discovery

            # v70.14: promising search snippets are not enough for final answer,
            # but they are enough to justify fetching those pages before any
            # API documentation or tool/code generation path.
            answer_evidence = await self._fetch_answer_evidence(
                run_id=run_id,
                node_id=node_id,
                search_evidence=sufficiency.get("selected_evidence") or web_evidence,
            )
            if answer_evidence:
                request["answer_evidence"] = answer_evidence
                combined_answer_evidence = answer_evidence + web_evidence
                sufficiency = self._evaluate_answer_sufficiency(combined_answer_evidence, request)
                await self._emit_answer_sufficiency(run_id, node_id, sufficiency, stage="fetched_answer_pages")
                if sufficiency.get("passed"):
                    discovery = self._finalize_answer_sufficient(
                        request=request,
                        web_evidence=web_evidence,
                        documentation_evidence=answer_evidence,
                        sufficiency=sufficiency,
                        strategy="fetched_page_answer_sufficiency",
                    )
                    await self._emit_done(run_id, node_id, discovery)
                    return discovery
                await event_bus.emit(run_id, {
                    "type": "ANSWER_EVIDENCE_INSUFFICIENT_AFTER_FETCH",
                    "title": "Fetched answer evidence is still insufficient",
                    "message": f"score={sufficiency.get('score')} next_action={sufficiency.get('next_action')}",
                    "node_id": node_id,
                    "result": sufficiency,
                })

        documentation_evidence = await self._fetch_documentation_evidence(
            run_id=run_id,
            node_id=node_id,
            search_evidence=web_evidence,
        )
        request["documentation_evidence"] = documentation_evidence

        # API discovery is a high-leverage planning stage. Prefer the configured
        # external/high-quality route first so the runtime can discover stable
        # structured providers before falling back to weaker local inference.
        external = await self._try_model_discovery(run_id=run_id, node_id=node_id, request=request, route_name="api_discovery_external")
        if self._usable_discovery(external):
            discovery = self._finalize(request=request, result=external, strategy="external_model", web_evidence=web_evidence, documentation_evidence=documentation_evidence)
            discovery = self.endpoint_verifier.verify_discovery(discovery)
            await self._emit_done(run_id, node_id, discovery)
            return discovery

        local = await self._try_model_discovery(run_id=run_id, node_id=node_id, request=request, route_name="api_discovery_local")
        discovery = self._finalize(request=request, result=local or external or {}, strategy="local_model_after_external_unavailable", web_evidence=web_evidence, documentation_evidence=documentation_evidence)
        discovery = self.endpoint_verifier.verify_discovery(discovery)
        await self._emit_done(run_id, node_id, discovery)
        return discovery

    def _build_request(self, *, capability: str, step: dict[str, Any], user_input: str) -> dict[str, Any]:
        request_id = "api_discovery_" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
        return {
            "request_id": request_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "capability": capability,
            "task_goal": "Find and understand an external API or connector that can satisfy this runtime capability with real data.",
            "user_input": user_input,
            "source_step": step,
            "runtime_request_semantics": self._extract_runtime_semantics(step=step, user_input=user_input),
            "request_mode": self._infer_request_mode(step=step, user_input=user_input),
            "requirements": {
                "must_use_real_network": True,
                "no_mock_data": True,
                "must_return_json": True,
                "must_search_documentation": True,
                "must_understand_authentication": True,
                "must_understand_parameters": True,
                "must_understand_response_shape": True,
                "must_support_live_verification": True,
                "prefer_no_api_key_when_possible": True,
                "prefer_structured_api_before_web_page": True,
                "must_disclose_required_secret_name_and_provider": True,
            },
            "strategy": {
                "first": "external_model_structured_api_advice",
                "second": "generic_web_documentation_search",
                "third": "runtime_model_api_selection_and_document_understanding",
                "fallback": "web_page_evidence_only_after_api_paths_fail",
            },
        }

    def _extract_runtime_semantics(self, *, step: dict[str, Any], user_input: str) -> dict[str, Any]:
        parameters = step.get("parameters") if isinstance(step.get("parameters"), dict) else {}
        return {
            "original_user_input": user_input,
            "objective": step.get("objective"),
            "action": step.get("action"),
            "task_type": step.get("task_type"),
            "known_parameters": parameters.get("known", parameters),
            "optional_parameters": parameters.get("optional", {}),
            "missing_required": parameters.get("missing_required", {}),
            "runtime_modifiers": step.get("modifiers") or parameters.get("modifiers") or parameters.get("qualifiers") or [],
            "runtime_constraints": step.get("constraints") or parameters.get("constraints") or {},
            "output_preferences": step.get("output_preferences") or parameters.get("output_preferences") or {},
        }

    def _search_queries(self, request: dict[str, Any]) -> list[str]:
        capability = str(request.get("capability") or "").strip()
        objective = str((request.get("source_step") or {}).get("objective") or "").strip()
        action = str((request.get("source_step") or {}).get("action") or "").strip()
        user_input = str(request.get("user_input") or "").strip()
        semantics = request.get("runtime_request_semantics") if isinstance(request.get("runtime_request_semantics"), dict) else {}
        known = semantics.get("known_parameters") if isinstance(semantics.get("known_parameters"), dict) else {}
        known_text = " ".join(str(v) for v in known.values() if v)
        if request.get("request_mode") == "answer_lookup":
            base = " ".join(part for part in [known_text, objective, action, user_input] if part)
            return [
                base,
                f"{known_text} {capability} detailed result".strip(),
            ]
        base = " ".join(part for part in [capability, objective, action, user_input] if part)
        if not base:
            base = capability or "external data"
        return [
            f"{base} official API documentation JSON parameters response example",
            f"{base} REST API docs authentication endpoint schema",
            f"{base} free public API documentation json no api key",
        ]

    async def _collect_web_evidence(self, *, run_id: str, node_id: str, request: dict[str, Any]) -> list[dict[str, Any]]:
        all_results: list[dict[str, Any]] = []
        for query in self._search_queries(request):
            try:
                search_result = await self.web.search(query=query, max_results=5)
                await event_bus.emit(run_id, {
                    "type": "WEB_RESEARCH_DONE",
                    "title": "Generic web research completed",
                    "message": f"query={query}",
                    "node_id": node_id,
                    "result": search_result,
                })
                if isinstance(search_result, dict):
                    for item in search_result.get("results", []) or []:
                        if isinstance(item, dict):
                            all_results.append(item)
            except Exception as exc:
                await event_bus.emit(run_id, {
                    "type": "WEB_RESEARCH_FAILED",
                    "title": "Generic web research failed",
                    "message": str(exc),
                    "node_id": node_id,
                    "result": {"query": query},
                })
        return self._dedupe_by_url(all_results)[:10]

    def _infer_request_mode(self, *, step: dict[str, Any], user_input: str) -> str:
        text = " ".join(str(x or "") for x in [user_input, step.get("objective"), step.get("action"), step.get("next_action")]).lower()
        explicit_integration_terms = (
            "create tool", "generate tool", "build tool", "create api", "generate api",
            "api documentation", "api docs", "endpoint", "adapter", "module", "codegen",
            "generate code", "write code", "sdk", "connector",
        )
        if any(term in text for term in explicit_integration_terms):
            return "api_discovery"
        return "answer_lookup"

    def _evaluate_answer_sufficiency(self, evidence: list[dict[str, Any]], request: dict[str, Any]) -> dict[str, Any]:
        semantics = request.get("runtime_request_semantics") if isinstance(request.get("runtime_request_semantics"), dict) else {}
        return self.answer_sufficiency.evaluate(
            user_input=str(request.get("user_input") or ""),
            objective=str(semantics.get("objective") or ""),
            capability=str(request.get("capability") or ""),
            known_parameters=semantics.get("known_parameters") if isinstance(semantics.get("known_parameters"), dict) else {},
            evidence=evidence,
        )

    async def _emit_answer_sufficiency(self, run_id: str, node_id: str, sufficiency: dict[str, Any], *, stage: str) -> None:
        await event_bus.emit(run_id, {
            "type": "ANSWER_SUFFICIENCY_EVALUATED",
            "title": "Answer sufficiency evaluated",
            "message": f"stage={stage} passed={sufficiency.get('passed')} score={sufficiency.get('score')}",
            "node_id": node_id,
            "result": sufficiency,
        })

    async def _fetch_answer_evidence(
        self,
        *,
        run_id: str,
        node_id: str,
        search_evidence: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        fetched: list[dict[str, Any]] = []
        for item in search_evidence[:7]:
            url = str(item.get("url") or "").strip()
            if not url and isinstance(item.get("evidence"), dict):
                evidence_obj = item.get("evidence") or {}
                url = str(evidence_obj.get("url") or "").strip()
            if not url and isinstance(item.get("source_search_result"), dict):
                search_obj = item.get("source_search_result") or {}
                url = str(search_obj.get("url") or "").strip()
            if not url:
                continue
            try:
                doc = await self.web.fetch(url=url, max_chars=24000)
                if isinstance(doc, dict) and doc.get("status") == "success":
                    fetched.append({
                        "source": "fetched_answer_evidence",
                        "source_search_result": item,
                        "document": doc,
                    })
                    await event_bus.emit(run_id, {
                        "type": "ANSWER_EVIDENCE_FETCHED",
                        "title": "Answer evidence fetched",
                        "message": doc.get("title") or url,
                        "node_id": node_id,
                        "result": {"url": url, "trace": doc.get("web_research_trace")},
                    })
            except Exception as exc:
                await event_bus.emit(run_id, {
                    "type": "ANSWER_EVIDENCE_FETCH_FAILED",
                    "title": "Answer evidence fetch failed",
                    "message": str(exc),
                    "node_id": node_id,
                    "result": {"url": url},
                })
        return fetched

    async def _fetch_documentation_evidence(
        self,
        *,
        run_id: str,
        node_id: str,
        search_evidence: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        fetched: list[dict[str, Any]] = []
        for item in search_evidence[:6]:
            url = str(item.get("url") or "").strip()
            if not url:
                continue
            try:
                doc = await self.web.fetch(url=url, max_chars=12000)
                if isinstance(doc, dict) and doc.get("status") == "success":
                    fetched.append({
                        "source_search_result": item,
                        "document": doc,
                    })
                    await event_bus.emit(run_id, {
                        "type": "API_DOCUMENTATION_FETCHED",
                        "title": "API documentation fetched",
                        "message": doc.get("title") or url,
                        "node_id": node_id,
                        "result": {"url": url, "trace": doc.get("web_research_trace")},
                    })
            except Exception as exc:
                await event_bus.emit(run_id, {
                    "type": "API_DOCUMENTATION_FETCH_FAILED",
                    "title": "API documentation fetch failed",
                    "message": str(exc),
                    "node_id": node_id,
                    "result": {"url": url},
                })
        return fetched

    async def _try_model_discovery(self, *, run_id: str, node_id: str, request: dict[str, Any], route_name: str) -> dict[str, Any] | None:
        route = self._route(route_name)
        if not route:
            return None
        prompt = {
            "system": (
                "You are a domain-neutral API documentation analyst. Return ONLY JSON. "
                "Use the supplied runtime request, web search evidence, and fetched documentation excerpts. "
                "Select one candidate only when documentation evidence supports its authentication, parameters, response shape, and live-verification approach. "
                "Do not invent URLs, endpoints, parameters, or verification results. "
                "If evidence is insufficient, set confidence below 0.5 and explain what is missing."
            ),
            "user": request,
        }
        try:
            await event_bus.emit(run_id, {
                "type": "API_DISCOVERY_MODEL_STARTED",
                "title": "API discovery model started",
                "message": f"route={route_name}: " + ", ".join(route),
                "node_id": node_id,
            })
            return await self.provider_router.generate_json(
                run_id=run_id,
                node_id=node_id,
                adapter={"provider_route": route},
                prompt=prompt,
                rendered_user_prompt=json.dumps(request, ensure_ascii=False, indent=2),
                schema=self.discovery_schema(),
            )
        except Exception as exc:
            await event_bus.emit(run_id, {
                "type": "API_DISCOVERY_MODEL_FAILED",
                "title": "API discovery model failed",
                "message": f"route={route_name}: {exc}",
                "node_id": node_id,
            })
            return None

    def _route(self, name: str) -> list[str]:
        config = self.loader.load_yaml(RUNTIME_CONFIGS / "models" / "providers.yaml")
        routes = config.get("routes") if isinstance(config.get("routes"), dict) else {}
        route = routes.get(name)
        if isinstance(route, list):
            return [str(x) for x in route if str(x).strip()]
        if name.endswith("local"):
            return ["ollama"]
        fallback = routes.get("fallback", ["openai"])
        return [str(x) for x in fallback] if isinstance(fallback, list) else [str(fallback)]

    def _usable_discovery(self, result: dict[str, Any] | None) -> bool:
        if not isinstance(result, dict):
            return False
        confidence = result.get("confidence")
        selected = result.get("selected_candidate")
        docs = result.get("documentation_understanding")
        if not isinstance(confidence, (int, float)) or confidence < 0.65:
            return False
        if not isinstance(selected, dict) or not selected.get("official_documentation_url"):
            return False
        if not isinstance(docs, dict):
            return False
        required_doc_keys = ["authentication", "request", "response", "verification_plan"]
        return all(key in docs for key in required_doc_keys)

    def _finalize_answer_sufficient(
        self,
        *,
        request: dict[str, Any],
        web_evidence: list[dict[str, Any]],
        documentation_evidence: list[dict[str, Any]],
        sufficiency: dict[str, Any],
        strategy: str,
    ) -> dict[str, Any]:
        trace_id = request.get("request_id")
        discovery = {
            "status": "success",
            "strategy_used": strategy,
            "request": request,
            "request_mode": "answer_lookup",
            "web_evidence": web_evidence,
            "documentation_evidence": documentation_evidence,
            "answer_sufficiency": sufficiency,
            "selected_evidence": sufficiency.get("selected_evidence") or [],
            "result": {
                "confidence": sufficiency.get("score", 0),
                "selected_candidate": {},
                "candidates": [],
                "documentation_understanding": {},
                "verification_plan": {"method": "not_required", "description": "Existing web evidence is sufficient for direct answer."},
            },
            "endpoint_verification": {
                "verified_json_api": False,
                "recommended_tool_type": "direct_answer",
                "selected_verified_endpoint": None,
                "selected_document_page": {},
                "checks": [],
            },
            "trace_id": trace_id,
        }
        trace_path = self.trace_dir / f"{trace_id}.json"
        trace_path.write_text(safe_json_dumps(discovery, indent=2), encoding="utf-8")
        discovery["trace_path"] = str(trace_path)
        return discovery

    def _finalize(
        self,
        *,
        request: dict[str, Any],
        result: dict[str, Any],
        strategy: str,
        web_evidence: list[dict[str, Any]],
        documentation_evidence: list[dict[str, Any]],
    ) -> dict[str, Any]:
        trace_id = "api_discovery_" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
        trace_path = self.trace_dir / f"{trace_id}.json"
        discovery = {
            "status": "success" if self._usable_discovery(result) else "insufficient_evidence",
            "strategy_used": strategy,
            "request": request,
            "result": result,
            "web_evidence": web_evidence,
            "documentation_evidence": documentation_evidence,
            "trace_id": trace_id,
            "trace_path": str(trace_path),
        }
        trace_path.write_text(safe_json_dumps(discovery, indent=2), encoding="utf-8")
        return discovery

    async def _emit_done(self, run_id: str, node_id: str, discovery: dict[str, Any]) -> None:
        result = discovery.get("result") if isinstance(discovery.get("result"), dict) else {}
        await event_bus.emit(run_id, {
            "type": "API_DISCOVERY_DONE",
            "title": "API discovery completed",
            "message": f"status={discovery.get('status')} strategy={discovery.get('strategy_used')}",
            "node_id": node_id,
            "result": {
                "status": discovery.get("status"),
                "strategy_used": discovery.get("strategy_used"),
                "trace_id": discovery.get("trace_id"),
                "trace_path": discovery.get("trace_path"),
                "candidate_count": len(result.get("candidates") or []),
                "selected_candidate": result.get("selected_candidate"),
                "documentation_evidence_count": len(discovery.get("documentation_evidence") or []),
                "endpoint_verification": discovery.get("endpoint_verification"),
                "runtime_strategy": discovery.get("runtime_strategy"),
            },
        })

    def _dedupe_by_url(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seen: set[str] = set()
        output: list[dict[str, Any]] = []
        for item in items:
            url = str(item.get("url") or "").strip()
            key = url or json.dumps(item, sort_keys=True, ensure_ascii=False)
            if key in seen:
                continue
            seen.add(key)
            output.append(item)
        return output

    def discovery_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "required": ["confidence", "candidates", "selected_candidate", "documentation_understanding", "verification_plan"],
            "properties": {
                "confidence": {"type": "number"},
                "reason": {"type": "string"},
                "candidates": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "official_documentation_url": {"type": "string"},
                            "requires_api_key": {"type": "boolean"},
                            "supports_json": {"type": "boolean"},
                            "supports_live_verification": {"type": "boolean"},
                            "evidence_urls": {"type": "array", "items": {"type": "string"}},
                            "notes": {"type": "string"},
                        },
                        "additionalProperties": True,
                    },
                },
                "selected_candidate": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "official_documentation_url": {"type": "string"},
                        "selection_reason": {"type": "string"},
                        "requires_api_key": {"type": "boolean"},
                    },
                    "additionalProperties": True,
                },
                "documentation_understanding": {
                    "type": "object",
                    "properties": {
                        "authentication": {"type": "object", "additionalProperties": True},
                        "request": {"type": "object", "additionalProperties": True},
                        "response": {"type": "object", "additionalProperties": True},
                        "parameter_mapping": {"type": "object", "additionalProperties": True},
                        "runtime_semantics_mapping": {"type": "object", "additionalProperties": True},
                        "verification_plan": {"type": "object", "additionalProperties": True},
                        "evidence_urls": {"type": "array", "items": {"type": "string"}},
                        "limitations": {"type": "array", "items": {"type": "string"}},
                    },
                    "additionalProperties": True,
                },
                "verification_plan": {"type": "object", "additionalProperties": True},
                "missing_evidence": {"type": "array", "items": {"type": "string"}},
            },
            "additionalProperties": True,
        }
