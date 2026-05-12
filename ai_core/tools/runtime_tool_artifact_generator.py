from __future__ import annotations

from typing import Any

from ai_core.llm.provider_router import ProviderRouter


class RuntimeToolArtifactGenerator:
    """
    Generic runtime tool artifact generator.

    ai_core does not know provider choices, API names, endpoints, or business logic.
    It sends a capability-generation request to the configured runtime LLM route
    and expects a generic tool artifact contract in return.
    """

    def __init__(self) -> None:
        self.provider_router = ProviderRouter()

    async def generate_artifact(
        self,
        *,
        run_id: str,
        node_id: str,
        generation_request: dict[str, Any],
    ) -> dict[str, Any]:
        schema = self.artifact_schema()
        prompt = {
            "system": (
                "You are a runtime tool artifact generator. Return ONLY JSON matching the schema. "
                "Generate a safe Python tool artifact from the supplied capability request. "
                "Do not include secrets. Do not use mock data. Include real timeout/retry/error handling. "
                "The generated tool must expose a run(input_data: dict) -> dict function."
            ),
            "user": generation_request,
        }
        adapter = generation_request.get("adapter") if isinstance(generation_request.get("adapter"), dict) else {}
        rendered_user_prompt = str(generation_request)
        return await self.provider_router.generate_json(
            run_id=run_id,
            node_id=node_id,
            adapter=adapter,
            prompt=prompt,
            rendered_user_prompt=rendered_user_prompt,
            schema=schema,
        )

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
