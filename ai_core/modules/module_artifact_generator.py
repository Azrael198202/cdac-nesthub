from __future__ import annotations

from typing import Any

from ai_core.config.loader import ConfigLoader
from ai_core.config.paths import RUNTIME_CONFIGS
from ai_core.llm.provider_router import ProviderRouter


class RuntimeModuleArtifactGenerator:
    """Generic executable module artifact generator.

    ai_core does not know what the module does. It sends a structured runtime
    module request to the configured code_generation route and expects an
    executable module artifact in return.
    """

    def __init__(self) -> None:
        self.provider_router = ProviderRouter()
        self.loader = ConfigLoader()

    async def generate_artifact(self, *, run_id: str, node_id: str, generation_request: dict[str, Any]) -> dict[str, Any]:
        prompt = {
            "system": (
                "You are a production runtime module artifact generator. Return ONLY JSON matching the schema. "
                "Generate a safe, reusable Python module artifact from the supplied structured runtime request. "
                "Do not include secrets. Do not use mock data or placeholder outputs. "
                "If the request includes api_discovery, use only the discovered/evidenced connector design and official sources. "
                "If real external data is required, module.py must perform a real network call with timeout/retry and return request/response evidence. "
                "The module.py file must define validate_config(config), health_check(), and run(input_data). "
                "Every helper function called must be defined or imported. Avoid top-level side effects. "
                "The manifest must declare execution_claims including real_execution, no_mock_data, uses_network, and live_verification_required when applicable."
            ),
            "user": generation_request,
        }
        adapter = dict(generation_request.get("adapter") or {})
        route = self._code_generation_route()
        if route:
            adapter["provider_route"] = route
        return await self.provider_router.generate_json(
            run_id=run_id,
            node_id=node_id,
            adapter=adapter,
            prompt=prompt,
            rendered_user_prompt=str(generation_request),
            schema=self.artifact_schema(),
        )

    def _code_generation_route(self) -> list[str]:
        config = self.loader.load_yaml(RUNTIME_CONFIGS / "models" / "providers.yaml")
        routes = config.get("routes") if isinstance(config.get("routes"), dict) else {}
        route = routes.get("code_generation") or config.get("code_generation_route")
        if isinstance(route, list):
            return [str(x) for x in route if str(x).strip()]
        return []

    def artifact_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "required": ["module_id", "manifest", "files"],
            "properties": {
                "module_id": {"type": "string"},
                "requires_review": {"type": "boolean"},
                "manifest": {
                    "type": "object",
                    "required": ["capability", "capabilities", "input_schema", "output_schema", "runtime_interface", "safety_policy", "execution_claims"],
                    "properties": {
                        "module_id": {"type": "string"},
                        "capability": {"type": "string"},
                        "capabilities": {"type": "array", "items": {"type": "string"}},
                        "status": {"type": "string"},
                        "input_schema": {"type": "object"},
                        "output_schema": {"type": "object"},
                        "runtime_interface": {"type": "object"},
                        "safety_policy": {"type": "object"},
                        "execution_claims": {"type": "object"},
                        "api_discovery": {"type": "object"},
                        "verification": {"type": "object"},
                    },
                    "additionalProperties": True,
                },
                "files": {"type": "object", "additionalProperties": {"type": "string"}},
                "real_execution": {"type": "boolean"},
                "no_mock_data": {"type": "boolean"},
                "uses_network": {"type": "boolean"},
                "verification": {"type": "object"},
            },
            "additionalProperties": True,
        }
