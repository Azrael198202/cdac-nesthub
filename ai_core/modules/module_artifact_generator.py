from __future__ import annotations

from typing import Any
import json

from ai_core.config.loader import ConfigLoader
from ai_core.config.paths import RUNTIME_CONFIGS
from ai_core.llm.provider_router import ProviderRouter
from ai_core.context.evidence_noise_reducer import EvidenceNoiseReducer
from ai_core.codegen.runtime_variable_inferencer import RuntimeVariableInferencer


class RuntimeModuleArtifactGenerator:
    """Generic executable module artifact generator.

    ai_core does not know what the module does. It sends a structured runtime
    module request to the configured code_generation route and expects an
    executable module artifact in return.
    """

    def __init__(self) -> None:
        self.provider_router = ProviderRouter()
        self.loader = ConfigLoader()
        self.evidence_reducer = EvidenceNoiseReducer()

    async def generate_artifact(self, *, run_id: str, node_id: str, generation_request: dict[str, Any]) -> dict[str, Any]:
        compact_request = self.evidence_reducer.compact_generation_request(generation_request)
        runtime_variable_contract = RuntimeVariableInferencer().infer(generation_request)
        compact_request["runtime_variables"] = runtime_variable_contract.get("runtime_variables", [])
        compact_request["parameterization_policy"] = runtime_variable_contract.get("parameterization_policy", {})
        compact_request["reusability_contract"] = {
            "must_be_payload_driven": True,
            "must_not_hardcode_runtime_values": True,
            "generated_module_must_support_different_payloads_for_same_capability": True,
        }
        prompt = {
            "system": (
                "Return ONLY JSON matching the schema. Generate a safe reusable Python module artifact. "
                "The module.py file must define validate_config(config), health_check(), and run(payload: dict) -> dict. "
                "Every helper function called by run must be defined or imported. No mock data, no secrets, no top-level side effects. "
                "Generate reusable code: do not hardcode ANY runtime value that appears in runtime_variables, user input, intent, workflow, semantics, schemas, or evidence. "
                "This rule is not limited to location/date/url; it includes every dynamic keyword, entity, identifier, option, format, path, amount, range, category, language, or query term inferred at runtime. "
                "Read all runtime values from payload/parameters/known and build requests dynamically from verified templates only. "
                "If verified_json_api is false, do not parse HTML as JSON and prefer webpage extraction or return evidence material. "
                "Use the compact evidence packet only; do not invent endpoints. Use standard library network access with timeout. "
                "Return JSON-serializable dicts only."
            ),
            "user": compact_request,
        }
        adapter = dict(generation_request.get("adapter") or {})
        adapter.setdefault("runtime_role", "code_generation_agent")
        adapter.setdefault("required_model_capabilities", [
            "code_generation",
            "python_generation",
            "adapter_generation",
            "schema_repair",
            "structured_output",
            "json_generation",
        ])
        route = self._code_generation_route()
        if route:
            adapter["provider_route"] = route
        artifact = await self.provider_router.generate_json(
            run_id=run_id,
            node_id=node_id,
            adapter=adapter,
            prompt=prompt,
            rendered_user_prompt=self._json_dumps(compact_request),
            schema=self.artifact_schema(),
        )
        if isinstance(artifact, dict):
            artifact.setdefault("runtime_variables", compact_request.get("runtime_variables", []))
            artifact.setdefault("parameterization_policy", compact_request.get("parameterization_policy", {}))
            manifest = artifact.get("manifest") if isinstance(artifact.get("manifest"), dict) else {}
            manifest.setdefault("runtime_variables", compact_request.get("runtime_variables", []))
            manifest.setdefault("parameterization_policy", compact_request.get("parameterization_policy", {}))
            artifact["manifest"] = manifest
        return artifact

    def _json_dumps(self, value: dict[str, Any]) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

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
                        "runtime_variables": {"type": "array", "items": {"type": "object"}},
                        "parameterization_policy": {"type": "object"},
                    },
                    "additionalProperties": True,
                },
                "files": {"type": "object", "additionalProperties": {"type": "string"}},
                "real_execution": {"type": "boolean"},
                "no_mock_data": {"type": "boolean"},
                "uses_network": {"type": "boolean"},
                "verification": {"type": "object"},
                "runtime_variables": {"type": "array", "items": {"type": "object"}},
                "parameterization_policy": {"type": "object"},
            },
            "additionalProperties": True,
        }
