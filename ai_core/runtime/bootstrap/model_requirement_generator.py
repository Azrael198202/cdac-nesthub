from __future__ import annotations

import json
from typing import Any

from ai_core.llm.provider_router import ProviderRouter


class ModelRequirementGenerator:
    """Optionally asks a strong external model to build runtime topology.

    If no external provider/key is available, callers can fall back to the seed
    topology. The prompt is generic and based on runtime feature/capability
    names, not on business domains.
    """

    def __init__(self) -> None:
        self.router = ProviderRouter()

    async def generate(
        self,
        *,
        run_id: str,
        feature_inventory: dict[str, Any],
        provider_inventory: dict[str, Any],
        seed_topology: dict[str, Any],
    ) -> dict[str, Any]:
        schema = {
            "type": "object",
            "additionalProperties": True,
            "properties": {
                "version": {"type": "string"},
                "capability_semantic_graph": {"type": "object"},
                "model_role_defaults": {"type": "object"},
                "execution_mode_rules": {"type": "object"},
                "missing_model_recommendations": {"type": "array"},
                "mcp_discovery_policy": {"type": "object"},
            },
        }
        prompt = {
            "system": (
                "You are a runtime bootstrap planner. Build a generic model/capability "
                "topology for an AI runtime. Use only capability names and provider metadata. "
                "Do not create business-domain rules. Return JSON only."
            ),
            "user": json.dumps(
                {
                    "feature_inventory": feature_inventory,
                    "provider_inventory": provider_inventory,
                    "seed_topology": seed_topology,
                    "requirements": [
                        "assign model tiers by cognitive capability",
                        "prefer lower-cost/local models for simple structured tasks",
                        "use stronger models for semantic governance and unknown capability discovery",
                        "preserve MCP discovery/orchestration as a capability source",
                        "include missing model recommendations when configured models are insufficient",
                    ],
                },
                ensure_ascii=False,
            ),
        }
        adapter = {
            "task_type": "runtime_bootstrap_topology",
            "required_capabilities": ["semantic_grounding", "structured_output"],
            "provider_route": ["openai", "claude", "ollama"],
        }
        return await self.router.generate_json(
            run_id=run_id,
            node_id="runtime_bootstrap",
            adapter=adapter,
            prompt=prompt,
            rendered_user_prompt=prompt["user"],
            schema=schema,
        )
