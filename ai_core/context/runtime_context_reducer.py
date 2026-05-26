from __future__ import annotations

from typing import Any


class RuntimeContextReducer:
    """Domain-neutral reducer for prompt-bound runtime context.

    This reducer does not know task/business/provider semantics. It keeps only
    execution state needed by the next LLM node and converts large nested traces
    into compact summaries. Runtime-generated reducers can override this by
    producing a reducer artifact under runtime/generated, but ai_core always has
    this safe fallback.
    """

    DEFAULT_MAX_TEXT = 1600
    DEFAULT_MAX_ITEMS = 8

    def reduce_results(self, results: dict[str, Any], *, max_text: int | None = None) -> dict[str, Any]:
        max_text = max_text or self.DEFAULT_MAX_TEXT
        compact: dict[str, Any] = {}
        for node_id, value in (results or {}).items():
            compact[node_id] = self._reduce_value(value, depth=0, max_text=max_text)
        return compact

    def reduce_capability_result(self, value: Any, *, max_text: int | None = None) -> Any:
        return self._reduce_value(value, depth=0, max_text=max_text or self.DEFAULT_MAX_TEXT)

    def _reduce_value(self, value: Any, *, depth: int, max_text: int) -> Any:
        if value is None or isinstance(value, (bool, int, float)):
            return value
        if isinstance(value, str):
            return self._truncate(value, max_text)
        if isinstance(value, list):
            return [self._reduce_value(x, depth=depth + 1, max_text=max_text) for x in value[: self.DEFAULT_MAX_ITEMS]]
        if isinstance(value, dict):
            if depth >= 3:
                return self._summarize_dict(value)
            keep_keys = [
                "status", "node_id", "intent_type", "task_type", "action", "objective",
                "parameters", "known", "missing_required", "execution_ready",
                "final_answer", "message", "summary", "error", "data", "result",
                "tool_results", "answer_material_quality", "trust_summary",
            ]
            compact = {}
            for k in keep_keys:
                if k in value:
                    compact[k] = self._reduce_value(value[k], depth=depth + 1, max_text=max_text)
            if not compact:
                for k, v in list(value.items())[: self.DEFAULT_MAX_ITEMS]:
                    compact[k] = self._reduce_value(v, depth=depth + 1, max_text=max_text)
            return compact
        return self._truncate(str(value), max_text)

    def _summarize_dict(self, value: dict[str, Any]) -> dict[str, Any]:
        return {
            "_reduced": True,
            "keys": list(value.keys())[: self.DEFAULT_MAX_ITEMS],
            "status": value.get("status"),
            "message": self._truncate(str(value.get("message", "")), 500) if value.get("message") else None,
        }

    def _truncate(self, text: str, max_text: int) -> str:
        if len(text) <= max_text:
            return text
        return text[:max_text] + "...[truncated]"
