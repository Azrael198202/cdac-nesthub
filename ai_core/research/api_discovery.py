from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from ai_core.config.loader import ConfigLoader
from ai_core.config.paths import RUNTIME_CONFIGS, RUNTIME_GENERATED, RUNTIME_TRACES
from ai_core.events.event_bus import event_bus
from ai_core.llm.provider_router import ProviderRouter
from ai_core.research.web_research_tool import GenericWebResearchTool


class ApiDiscoveryEngine:
    """Runtime API discovery orchestration.

    The engine is domain-neutral. It does not know any API vendor or specific
    data domain. It creates a generic discovery request, tries local reasoning
    first, optionally uses generic web research, then escalates to a stronger
    external model route when configured/needed.
    """

    def __init__(self) -> None:
        self.loader = ConfigLoader()
        self.provider_router = ProviderRouter()
        self.web = GenericWebResearchTool()
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
            "message": f"Discovering external API candidates for capability={capability}",
            "node_id": node_id,
            "result": {"request_id": request["request_id"], "request_path": str(request_path)},
        })

        web_evidence = await self._collect_web_evidence(run_id=run_id, node_id=node_id, request=request)
        request["web_evidence"] = web_evidence

        local = await self._try_model_discovery(run_id=run_id, node_id=node_id, request=request, route_name="api_discovery_local")
        if self._usable_discovery(local):
            discovery = self._finalize(request=request, result=local, strategy="local_model", web_evidence=web_evidence)
            await self._emit_done(run_id, node_id, discovery)
            return discovery

        external = await self._try_model_discovery(run_id=run_id, node_id=node_id, request=request, route_name="api_discovery_external")
        discovery = self._finalize(request=request, result=external or {}, strategy="external_model", web_evidence=web_evidence)
        await self._emit_done(run_id, node_id, discovery)
        return discovery

    def _build_request(self, *, capability: str, step: dict[str, Any], user_input: str) -> dict[str, Any]:
        request_id = "api_discovery_" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
        return {
            "request_id": request_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "capability": capability,
            "task_goal": "Discover candidate external APIs/connectors that can satisfy the capability with real data.",
            "user_input": user_input,
            "source_step": step,
            "requirements": {
                "must_use_real_network": True,
                "no_mock_data": True,
                "must_return_json": True,
                "must_have_official_documentation": True,
                "must_support_live_verification": True,
                "prefer_no_api_key_when_possible": True,
            },
            "strategy": {
                "first": "local_model",
                "fallback": "external_model_with_generic_web_research",
            },
        }

    async def _collect_web_evidence(self, *, run_id: str, node_id: str, request: dict[str, Any]) -> list[dict[str, Any]]:
        query = f"official API documentation JSON {request.get('capability')}"
        try:
            search_result = await self.web.search(query=query, max_results=5)
            await event_bus.emit(run_id, {
                "type": "WEB_RESEARCH_DONE",
                "title": "Generic web research completed",
                "message": f"query={query}",
                "node_id": node_id,
                "result": search_result,
            })
            return search_result.get("results", []) if isinstance(search_result, dict) else []
        except Exception as exc:
            await event_bus.emit(run_id, {
                "type": "WEB_RESEARCH_FAILED",
                "title": "Generic web research failed",
                "message": str(exc),
                "node_id": node_id,
            })
            return []

    async def _try_model_discovery(self, *, run_id: str, node_id: str, request: dict[str, Any], route_name: str) -> dict[str, Any] | None:
        route = self._route(route_name)
        if not route:
            return None
        prompt = {
            "system": (
                "You are a domain-neutral API discovery planner. Return ONLY JSON. "
                "Use the supplied capability, workflow step, and web evidence to propose external API candidates. "
                "Prefer official documentation and APIs that can be live-verified. Do not invent verification results. "
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
        return routes.get("fallback", ["openai"])

    def _usable_discovery(self, result: dict[str, Any] | None) -> bool:
        if not isinstance(result, dict):
            return False
        confidence = result.get("confidence")
        candidates = result.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            return False
        return isinstance(confidence, (int, float)) and confidence >= 0.65

    def _finalize(self, *, request: dict[str, Any], result: dict[str, Any], strategy: str, web_evidence: list[dict[str, Any]]) -> dict[str, Any]:
        trace_id = "api_discovery_" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
        trace_path = self.trace_dir / f"{trace_id}.json"
        discovery = {
            "status": "success" if self._usable_discovery(result) else "insufficient_evidence",
            "strategy_used": strategy,
            "request": request,
            "result": result,
            "web_evidence": web_evidence,
            "trace_id": trace_id,
            "trace_path": str(trace_path),
        }
        trace_path.write_text(json.dumps(discovery, ensure_ascii=False, indent=2), encoding="utf-8")
        return discovery

    async def _emit_done(self, run_id: str, node_id: str, discovery: dict[str, Any]) -> None:
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
                "candidate_count": len((discovery.get("result") or {}).get("candidates") or []),
            },
        })

    def discovery_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "required": ["confidence", "candidates", "verification_plan"],
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
                            "notes": {"type": "string"},
                        },
                        "additionalProperties": True,
                    },
                },
                "selected_candidate": {"type": "object", "additionalProperties": True},
                "connector_design": {"type": "object", "additionalProperties": True},
                "verification_plan": {"type": "object", "additionalProperties": True},
                "sources": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
            },
            "additionalProperties": True,
        }
