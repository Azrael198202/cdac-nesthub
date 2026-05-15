from __future__ import annotations

import json
from typing import Any

from ai_core.llm.provider_router import ProviderRouter
from ai_core.presentation.result_presenter import ResultPresenter
from ai_core.presentation.result_sanitizer import ResultSanitizer


class FinalAnswerSynthesizer:
    """Creates the final user-facing answer from sanitized result material.

    Every upstream output is treated as intermediate material. Raw transport,
    trace, source markup, and tool payloads are never returned directly.
    """

    def __init__(self) -> None:
        self.sanitizer = ResultSanitizer()
        self.presenter = ResultPresenter()
        self.router = ProviderRouter()

    async def synthesize(
        self,
        *,
        run_id: str,
        node_id: str,
        state: dict[str, Any],
        materials: list[dict[str, Any]],
        trust_summary: dict[str, Any],
    ) -> dict[str, Any]:
        sanitized = self.sanitizer.sanitize_materials(materials)
        deterministic = self._deterministic_summary(sanitized)
        answer = deterministic

        if self._model_synthesis_enabled(state, sanitized):
            generated = await self._try_model_synthesis(
                run_id=run_id,
                node_id=node_id,
                state=state,
                sanitized=sanitized,
                trust_summary=trust_summary,
            )
            if generated:
                answer = generated

        return {
            "answer": answer,
            "result_material": sanitized,
            "synthesis": {
                "source": "model_or_rule_synthesis" if answer != deterministic else "rule_synthesis",
                "raw_source_material_returned": False,
            },
        }

    def _model_synthesis_enabled(self, state: dict[str, Any], sanitized: list[dict[str, Any]]) -> bool:
        output_policy = (((state.get("runtime") or {}) if isinstance(state, dict) else {}).get("output_policy") or {})
        if output_policy.get("disable_model_synthesis") is True:
            return False
        # Avoid an LLM call when there is no useful material.
        return bool(sanitized)

    async def _try_model_synthesis(
        self,
        *,
        run_id: str,
        node_id: str,
        state: dict[str, Any],
        sanitized: list[dict[str, Any]],
        trust_summary: dict[str, Any],
    ) -> str:
        try:
            original_input = self._original_input(state)
            language = self._language(state)
            prompt_text = json.dumps(
                {
                    "user_request": original_input,
                    "language": language,
                    "materials": sanitized,
                    "trust": trust_summary,
                    "instructions": [
                        "Create a concise user-facing answer.",
                        "Use only the sanitized materials.",
                        "Do not include raw markup, raw JSON, traces, debug logs, or internal field dumps.",
                        "Mention uncertainty briefly if the material quality is limited.",
                        "Return JSON with key final_answer only.",
                    ],
                },
                ensure_ascii=False,
            )
            adapter = {
                "adapter_id": "final_answer_synthesizer",
                "provider_route": ["ollama", "openai"],
                "preferred_capabilities": ["structured_output", "summarization"],
                "prompt_policy": {"max_context_tokens": 2500},
            }
            prompt = {
                "id": "final_answer_synthesis",
                "system": "You are a neutral final answer synthesizer. Return valid JSON only.",
            }
            schema = {
                "type": "object",
                "properties": {"final_answer": {"type": "string"}},
                "required": ["final_answer"],
                "additionalProperties": True,
            }
            result = await self.router.generate_json(
                run_id=run_id,
                node_id=node_id,
                adapter=adapter,
                prompt=prompt,
                rendered_user_prompt=prompt_text,
                schema=schema,
            )
            value = result.get("final_answer") if isinstance(result, dict) else None
            if isinstance(value, str) and value.strip():
                return self.sanitizer.sanitize_value(value).strip()
        except Exception:
            return ""
        return ""

    def _deterministic_summary(self, sanitized: list[dict[str, Any]]) -> str:
        lines: list[str] = []
        for material in sanitized:
            if not isinstance(material, dict):
                continue
            status = str(material.get("status") or "")
            content = material.get("content")
            if status and status not in {"success", "executed", "completed"}:
                error_text = self._error_text(content)
                if error_text:
                    lines.append(error_text)
                    continue
            text = self._content_text(content)
            if text:
                lines.append(text)
        if not lines:
            return "The runtime completed, but no user-facing answer material was available."
        compact: list[str] = []
        seen: set[str] = set()
        for line in lines:
            value = " ".join(str(line).split())
            if not value or value in seen:
                continue
            seen.add(value)
            compact.append(value)
        return "\n".join(compact[:8])

    def _content_text(self, content: Any) -> str:
        if isinstance(content, dict):
            for key in ("final_answer", "answer", "summary", "message", "text"):
                value = content.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
            extracted = content.get("extracted_material")
            if isinstance(extracted, dict):
                rows = extracted.get("records")
                text = extracted.get("text")
                row_text = ""
                if isinstance(rows, list) and rows:
                    row_lines = []
                    for row in rows[:5]:
                        if isinstance(row, list):
                            row_lines.append(" | ".join(str(x) for x in row[:8]))
                    row_text = "\n".join(row_lines)
                if row_text:
                    return row_text
                if isinstance(text, str):
                    return text.strip()
            return self.presenter.present_data(content)
        if isinstance(content, list):
            parts = [self._content_text(x) for x in content[:5]]
            return "\n".join(x for x in parts if x)
        if content is None:
            return ""
        return self.sanitizer.sanitize_value(str(content))

    def _error_text(self, content: Any) -> str:
        if isinstance(content, dict):
            error = content.get("error")
            if isinstance(error, dict):
                msg = error.get("message") or error.get("reason")
                if msg:
                    return f"The step failed: {msg}"
            if isinstance(error, str):
                return f"The step failed: {error}"
        return ""

    def _original_input(self, state: dict[str, Any]) -> str:
        for section_name in ("input", "request", "runtime"):
            section = state.get(section_name) if isinstance(state, dict) else None
            if isinstance(section, dict):
                for key in ("original_input", "user_input", "message"):
                    value = section.get(key)
                    if isinstance(value, str) and value.strip():
                        return value.strip()
        results = state.get("results") if isinstance(state, dict) else None
        if isinstance(results, dict):
            input_result = results.get("input_parsing")
            if isinstance(input_result, dict):
                value = input_result.get("original_input")
                if isinstance(value, str):
                    return value
        return ""

    def _language(self, state: dict[str, Any]) -> str:
        results = state.get("results") if isinstance(state, dict) else None
        if isinstance(results, dict):
            input_result = results.get("input_parsing")
            if isinstance(input_result, dict):
                value = input_result.get("language")
                if isinstance(value, str) and value.strip():
                    return value.strip()
        return ""
