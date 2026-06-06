from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RuntimeCostSnapshot:
    enabled: bool
    max_prompt_tokens: int
    max_provider_attempts: int
    max_external_discovery_attempts: int
    max_generated_component_attempts: int
    # Backward-compatible names. In v2.9.15 these are adaptive evidence budgets,
    # not hard quality caps. The pipeline may stop early only after quality is
    # sufficient, and it expands incrementally until the budget is exhausted.
    max_evidence_pages: int
    max_evidence_page_chars: int
    adaptive_evidence_enabled: bool
    adaptive_min_sources: int
    adaptive_max_sources: int
    adaptive_candidate_window: int
    adaptive_initial_fetches: int
    adaptive_incremental_fetches: int
    adaptive_fetch_chars_per_source: int
    adaptive_llm_material_chars: int
    adaptive_fact_limit: int
    adaptive_block_limit: int
    adaptive_stop_quality_score: float
    operation_timeout_seconds: int
    sandbox_timeout_seconds: int
    stage_timeouts: dict[str, int]
    prefer_repair_before_model_escalation: bool
    allow_paid_model_escalation: bool

    def evidence_policy(self) -> dict[str, Any]:
        return {
            "adaptive_evidence_enabled": self.adaptive_evidence_enabled,
            "adaptive_min_sources": self.adaptive_min_sources,
            "adaptive_max_sources": self.adaptive_max_sources,
            "candidate_window": self.adaptive_candidate_window,
            "initial_fetches": self.adaptive_initial_fetches,
            "incremental_fetches": self.adaptive_incremental_fetches,
            "max_fetches": self.max_evidence_pages,
            "fetch_chars_per_source": self.adaptive_fetch_chars_per_source,
            "llm_material_chars": self.adaptive_llm_material_chars,
            "fact_limit": self.adaptive_fact_limit,
            "block_limit": self.adaptive_block_limit,
            "stop_quality_score": self.adaptive_stop_quality_score,
            "stage_timeouts": dict(self.stage_timeouts),
        }

    def stage_timeout(self, name: str, default: int | None = None) -> int:
        if default is None:
            default = self.operation_timeout_seconds
        try:
            return max(1, int(self.stage_timeouts.get(name, default)))
        except Exception:
            return max(1, int(default))


class RuntimeCostPolicy:
    """Runtime cost and convergence policy.

    Cost saving must not simply truncate evidence. This policy separates API
    prompt budgets from evidence collection budgets. Evidence is collected,
    ranked, normalized, deduplicated and compressed locally; only compact
    structured facts should reach expensive model calls.
    """

    def snapshot(self, source: dict[str, Any] | None = None) -> RuntimeCostSnapshot:
        source = source if isinstance(source, dict) else {}
        policy = self._find_policy(source)
        adaptive = policy.get("adaptive_evidence") if isinstance(policy.get("adaptive_evidence"), dict) else {}
        adaptive_enabled = self._bool("AI_CORE_ADAPTIVE_EVIDENCE_ENABLED", adaptive.get("enabled"), True)
        adaptive_max_sources = self._int("AI_CORE_ADAPTIVE_EVIDENCE_MAX_SOURCES", adaptive.get("max_sources"), 5, 1)
        legacy_pages = self._int("AI_CORE_MAX_EVIDENCE_PAGES", policy.get("max_evidence_pages"), adaptive_max_sources, 1)
        max_fetches = self._int("AI_CORE_ADAPTIVE_EVIDENCE_MAX_FETCHES", adaptive.get("max_fetches"), max(legacy_pages, adaptive_max_sources), 1)
        chars_per_source = self._int(
            "AI_CORE_ADAPTIVE_EVIDENCE_SOURCE_CHARS",
            adaptive.get("fetch_chars_per_source", policy.get("max_evidence_page_chars")),
            18000,
            4000,
        )
        return RuntimeCostSnapshot(
            enabled=self._bool("AI_CORE_TOKEN_SAVER_ENABLED", policy.get("enabled"), True),
            max_prompt_tokens=self._int("AI_CORE_MAX_PROMPT_TOKENS", policy.get("max_prompt_tokens"), 2500, 800),
            max_provider_attempts=self._int("AI_CORE_MAX_PROVIDER_ATTEMPTS", policy.get("max_provider_attempts"), 1, 1),
            max_external_discovery_attempts=self._int("AI_CORE_MAX_EXTERNAL_DISCOVERY_ATTEMPTS", policy.get("max_external_discovery_attempts"), 1, 0),
            max_generated_component_attempts=self._int("AI_CORE_MAX_GENERATED_COMPONENT_ATTEMPTS", policy.get("max_generated_component_attempts"), 1, 0),
            max_evidence_pages=max_fetches,
            max_evidence_page_chars=chars_per_source,
            adaptive_evidence_enabled=adaptive_enabled,
            adaptive_min_sources=self._int("AI_CORE_ADAPTIVE_EVIDENCE_MIN_SOURCES", adaptive.get("min_sources"), 2, 1),
            adaptive_max_sources=adaptive_max_sources,
            adaptive_candidate_window=self._int("AI_CORE_ADAPTIVE_EVIDENCE_CANDIDATE_WINDOW", adaptive.get("candidate_window"), 6, 1),
            adaptive_initial_fetches=self._int("AI_CORE_ADAPTIVE_EVIDENCE_INITIAL_FETCHES", adaptive.get("initial_fetches"), 2, 1),
            adaptive_incremental_fetches=self._int("AI_CORE_ADAPTIVE_EVIDENCE_INCREMENTAL_FETCHES", adaptive.get("incremental_fetches"), 1, 1),
            adaptive_fetch_chars_per_source=chars_per_source,
            adaptive_llm_material_chars=self._int("AI_CORE_ADAPTIVE_EVIDENCE_LLM_CHARS", adaptive.get("llm_material_chars"), 1800, 600),
            adaptive_fact_limit=self._int("AI_CORE_ADAPTIVE_EVIDENCE_FACT_LIMIT", adaptive.get("fact_limit"), 16, 4),
            adaptive_block_limit=self._int("AI_CORE_ADAPTIVE_EVIDENCE_BLOCK_LIMIT", adaptive.get("block_limit"), 8, 3),
            adaptive_stop_quality_score=self._float("AI_CORE_ADAPTIVE_EVIDENCE_STOP_SCORE", adaptive.get("stop_quality_score"), 0.78, 0.0, 0.99),
            operation_timeout_seconds=self._int("AI_CORE_OPERATION_TIMEOUT_SECONDS", policy.get("operation_timeout_seconds"), 180, 5),
            sandbox_timeout_seconds=self._int("AI_CORE_SANDBOX_TIMEOUT_SECONDS", policy.get("sandbox_timeout_seconds"), 45, 5),
            stage_timeouts=self._stage_timeouts(policy),
            prefer_repair_before_model_escalation=self._bool("AI_CORE_REPAIR_BEFORE_ESCALATION", policy.get("prefer_repair_before_model_escalation"), True),
            allow_paid_model_escalation=self._bool("AI_CORE_ALLOW_PAID_MODEL_ESCALATION", policy.get("allow_paid_model_escalation"), True),
        )

    def apply_adapter_budget(self, adapter: dict[str, Any] | None, source: dict[str, Any] | None = None) -> dict[str, Any]:
        adapter = dict(adapter or {})
        snap = self.snapshot(source)
        if not snap.enabled:
            return adapter
        existing = adapter.get("max_prompt_tokens")
        if existing is None:
            adapter["max_prompt_tokens"] = snap.max_prompt_tokens
        else:
            try:
                adapter["max_prompt_tokens"] = min(int(existing), snap.max_prompt_tokens)
            except Exception:
                adapter["max_prompt_tokens"] = snap.max_prompt_tokens
        adapter.setdefault("max_provider_attempts", snap.max_provider_attempts)
        return adapter

    def trim_route(self, route: list[str], *, source: dict[str, Any] | None = None, escalated: bool = False) -> list[str]:
        snap = self.snapshot(source)
        if not snap.enabled or escalated:
            return route
        return list(route[: max(1, snap.max_provider_attempts)])

    def _find_policy(self, source: dict[str, Any]) -> dict[str, Any]:
        if isinstance(source.get("runtime_cost_policy"), dict):
            return source["runtime_cost_policy"]
        global_policy = source.get("global_policy") if isinstance(source.get("global_policy"), dict) else {}
        runtime_execution_policy = global_policy.get("runtime_execution_policy") if isinstance(global_policy.get("runtime_execution_policy"), dict) else {}
        if isinstance(runtime_execution_policy.get("runtime_cost_policy"), dict):
            return runtime_execution_policy["runtime_cost_policy"]
        if isinstance(global_policy.get("runtime_cost_policy"), dict):
            return global_policy["runtime_cost_policy"]
        return {}

    def _bool(self, env_name: str, configured: Any, default: bool) -> bool:
        raw = os.getenv(env_name)
        value = configured if raw is None else raw
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"1", "true", "yes", "on", "enabled"}

    def _int(self, env_name: str, configured: Any, default: int, minimum: int) -> int:
        raw = os.getenv(env_name)
        value = configured if raw is None else raw
        try:
            parsed = int(value)
        except Exception:
            parsed = default
        return max(minimum, parsed)

    def _float(self, env_name: str, configured: Any, default: float, minimum: float, maximum: float) -> float:
        raw = os.getenv(env_name)
        value = configured if raw is None else raw
        try:
            parsed = float(value)
        except Exception:
            parsed = default
        return max(minimum, min(maximum, parsed))


# v2.9.23 helper extension kept at module end to avoid changing callers.
def _runtime_cost_policy_stage_timeouts(self, policy: dict[str, Any]) -> dict[str, int]:
    configured = policy.get("stage_timeouts") if isinstance(policy.get("stage_timeouts"), dict) else {}
    aliases = policy.get("method_timeout_seconds") if isinstance(policy.get("method_timeout_seconds"), dict) else {}
    values = {
        "web_discovery": self._int("AI_CORE_STAGE_TIMEOUT_WEB_DISCOVERY", configured.get("web_discovery"), 18, 1),
        "extraction": self._int("AI_CORE_STAGE_TIMEOUT_EXTRACTION", configured.get("extraction"), 25, 1),
        "evidence_validation": self._int("AI_CORE_STAGE_TIMEOUT_EVIDENCE_VALIDATION", configured.get("evidence_validation"), 20, 1),
        "api_discovery": self._int("AI_CORE_STAGE_TIMEOUT_API_DISCOVERY", configured.get("api_discovery"), 15, 1),
        "api_call": self._int("AI_CORE_STAGE_TIMEOUT_API_CALL", aliases.get("api_call", configured.get("api_call")), 30, 1),
        "web_search": self._int("AI_CORE_STAGE_TIMEOUT_WEB_SEARCH", aliases.get("web_search", configured.get("web_search")), 30, 1),
        "synthesis": self._int("AI_CORE_STAGE_TIMEOUT_SYNTHESIS", configured.get("synthesis"), 20, 1),
    }
    return values

RuntimeCostPolicy._stage_timeouts = _runtime_cost_policy_stage_timeouts
