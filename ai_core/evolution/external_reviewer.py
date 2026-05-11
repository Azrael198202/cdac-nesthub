from __future__ import annotations

import json
from typing import Any

from ai_core.llm.openai_client import OpenAIClient


class ExternalReviewer:
    async def review_failure(self, step: str, user_text: str, local_output: Any, validation: dict[str, Any]) -> dict[str, Any]:
        prompt = f"""
You are an external insurance reviewer for an AI Core.
Step: {step}
User request: {user_text}
Local output: {local_output}
Validation: {validation}

Return JSON with exactly this structure:
{{
  "decision": "use_local_with_improvement" | "download_local_model" | "search_huggingface_model" | "use_external_api_model" | "ask_human_direction",
  "reason": "...",
  "improved_result": {{}}
}}
"""
        result = await OpenAIClient().generate(prompt)
        if not result.ok or not result.text:
            return {"decision": "ask_human_direction", "reason": "external_api_unavailable_or_missing_key", "improved_result": {}}
        try:
            text = result.text.strip()
            if text.startswith("```"):
                text = text.strip("`").replace("json", "", 1).strip()
            return json.loads(text)
        except Exception:
            return {"decision": "use_external_api_model", "reason": "external_text_not_json", "improved_result": {"raw": result.text}}
