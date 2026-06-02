from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from ai_core.config.paths import RUNTIME_GENERATED


class ToolCodeGenerationRequestBuilder:
    def __init__(self) -> None:
        self.dir = RUNTIME_GENERATED / "tool_generation_requests"
        self.dir.mkdir(parents=True, exist_ok=True)

    def create_request(self, *, capability: str, blueprint: dict[str, Any], user_input: str = "") -> dict[str, Any]:
        request_id = f"codegen_{self._safe_name(capability)}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
        request = {
            "request_id": request_id,
            "capability": capability,
            "created_at": datetime.utcnow().isoformat(),
            "status": "pending_strong_model_generation",
            "source_user_input": user_input,
            "blueprint": blueprint,
            "model_task": {
                "role": "Runtime Tool Code Generator",
                "instructions": [
                    "Generate safe, generic Python tool code based on the blueprint.",
                    "Do not hardcode secrets.",
                    "Do not perform irreversible actions without human confirmation.",
                    "Include input_schema and output_schema.",
                    "Include test cases.",
                    "Return code and metadata separately.",
                ],
            },
            "safety_requirements": [
                "No secret logging.",
                "No irreversible or externally mutating action without confirmation.",
                "Network access must be explicit in tool metadata.",
                "Automation must pause before irreversible external actions.",
            ],
        }
        path = self.dir / f"{request_id}.json"
        path.write_text(json.dumps(request, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"request_id": request_id, "request_path": str(path), "request": request}

    def _safe_name(self, value: str) -> str:
        return "".join(c if c.isalnum() else "_" for c in str(value)).strip("_").lower() or "tool"
