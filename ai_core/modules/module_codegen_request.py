from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from ai_core.config.paths import RUNTIME_GENERATED


class ModuleCodeGenerationRequestBuilder:
    """
    Creates a strong-model code generation request for a runtime module.

    It does not call the model and does not execute generated code.
    It only writes structured requests under runtime/generated.
    """

    def __init__(self) -> None:
        self.dir = RUNTIME_GENERATED / "module_generation_requests"
        self.dir.mkdir(parents=True, exist_ok=True)

    def create_request(
        self,
        *,
        module_id: str,
        capability: str,
        blueprint: dict[str, Any],
        user_input: str = "",
    ) -> dict[str, Any]:
        request_id = f"module_codegen_{self._safe_name(module_id)}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
        request = {
            "request_id": request_id,
            "module_id": module_id,
            "capability": capability,
            "created_at": datetime.utcnow().isoformat(),
            "status": "pending_strong_model_generation",
            "source_user_input": user_input,
            "blueprint": blueprint,
            "model_task": {
                "role": "Runtime Module Code Generator",
                "instructions": [
                    "Generate a generic runtime module implementation based only on the blueprint metadata.",
                    "Do not hardcode business logic in ai_core.",
                    "Do not hardcode user secrets.",
                    "Expose a small generic interface: validate_config, run, health_check.",
                    "Include input_schema, output_schema, and test cases.",
                    "Do not perform irreversible actions without human confirmation metadata.",
                    "Return generated files separately from explanatory text.",
                ],
            },
            "safety_requirements": [
                "No secret logging.",
                "Generated module must be sandbox-reviewable before registration.",
                "Module must declare external access requirements.",
                "Module must declare human confirmation requirements.",
            ],
        }

        path = self.dir / f"{request_id}.json"
        path.write_text(json.dumps(request, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"request_id": request_id, "request_path": str(path), "request": request}

    def _safe_name(self, value: str) -> str:
        return "".join(c if c.isalnum() else "_" for c in str(value)).strip("_").lower() or "module"
