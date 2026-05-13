from __future__ import annotations

from typing import Any

from ai_core.config.loader import ConfigLoader
from ai_core.config.paths import RUNTIME_CONFIGS
from ai_core.llm.provider_router import ProviderRouter


class RuntimeToolArtifactGenerator:
    """
    Generic runtime tool artifact generator.

    ai_core does not know provider choices, API names, endpoints, or business logic.
    It sends a capability/tool-generation request to the configured runtime LLM
    route and expects a generic tool artifact contract in return.

    v45: code generation uses a dedicated runtime-configured code_generation
    route when available. The core does not choose a model by business domain;
    it only asks runtime config for the route optimized for code artifacts.
    """

    def __init__(self) -> None:
        self.provider_router = ProviderRouter()
        self.loader = ConfigLoader()

    async def generate_artifact(
        self,
        *,
        run_id: str,
        node_id: str,
        generation_request: dict[str, Any],
    ) -> dict[str, Any]:
        return await self._generate(
            run_id=run_id,
            node_id=node_id,
            generation_request=generation_request,
            repair_context=None,
        )

    async def repair_artifact(
        self,
        *,
        run_id: str,
        node_id: str,
        generation_request: dict[str, Any],
        failed_artifact: dict[str, Any] | None,
        error: dict[str, Any] | str,
    ) -> dict[str, Any]:
        return await self._generate(
            run_id=run_id,
            node_id=node_id,
            generation_request=generation_request,
            repair_context={
                "error": error,
                "failed_artifact": failed_artifact or {},
                "instruction": (
                    "Repair the artifact. Return a complete replacement artifact. "
                    "Do not call undefined helper functions. Define every helper in tool.py or import it. "
                    "The manifest implementation function must exist and be callable."
                ),
            },
        )

    async def _generate(
        self,
        *,
        run_id: str,
        node_id: str,
        generation_request: dict[str, Any],
        repair_context: dict[str, Any] | None,
    ) -> dict[str, Any]:
        schema = self.artifact_schema()
        effective_request = dict(generation_request)
        if repair_context:
            effective_request["repair_context"] = repair_context

        prompt = {
            "system": (
                "You are a production runtime tool artifact generator. Return ONLY JSON matching the schema. "
                "Generate a safe, reusable Python tool artifact from the supplied capability request. "
                "Do not include secrets. Do not use mock data or placeholder outputs. "
                "When network/API access is needed, include real timeout/retry/error handling. "
                "The generated tool must expose a run(input_data: dict) -> dict function unless the manifest declares another callable. "
                "Every helper function called by run must be defined in the file or imported. "
                "Avoid top-level network calls. Put side effects inside the callable. "
                "Return code and metadata only inside the artifact JSON."
            ),
            "user": effective_request,
        }
        adapter = generation_request.get("adapter") if isinstance(generation_request.get("adapter"), dict) else {}
        adapter = {**adapter}
        route = self._code_generation_route()
        if route:
            adapter["provider_route"] = route
        rendered_user_prompt = str(effective_request)
        return await self.provider_router.generate_json(
            run_id=run_id,
            node_id=node_id,
            adapter=adapter,
            prompt=prompt,
            rendered_user_prompt=rendered_user_prompt,
            schema=schema,
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
            "required": ["tool_id", "manifest", "files"],
            "properties": {
                "tool_id": {"type": "string"},
                "requires_review": {"type": "boolean"},
                "manifest": {
                    "type": "object",
                    "required": ["capability", "capabilities", "implementation", "input_schema", "output_schema", "safety"],
                    "properties": {
                        "name": {"type": "string"},
                        "capability": {"type": "string"},
                        "capabilities": {"type": "array", "items": {"type": "string"}},
                        "status": {"type": "string"},
                        "implementation": {"type": "object"},
                        "input_schema": {"type": "object"},
                        "output_schema": {"type": "object"},
                        "safety": {"type": "object"},
                    },
                    "additionalProperties": True,
                },
                "files": {
                    "type": "object",
                    "additionalProperties": {"type": "string"},
                },
            },
            "additionalProperties": True,
        }
