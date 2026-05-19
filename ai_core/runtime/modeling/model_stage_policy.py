from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from ai_core.config.loader import ConfigLoader
from ai_core.config.paths import CONFIGS_DIR, RUNTIME_GENERATED


class ModelStagePolicy:
    """Stage-bound model policy resolver.

    This class is intentionally domain-neutral.  It does not infer business
    meaning from user text.  It only maps runtime stage ids to configured model
    candidates, model tiers, cost policy, provider templates, and validation
    escalation rules.
    """

    STAGE_ALIASES = {
        "input_parsing": "input_parsing",
        "intent_recognition": "simple_intent",
        "simple_intent": "simple_intent",
        "intent_simple": "simple_intent",
        "complex_intent": "complex_intent",
        "intent_complex": "complex_intent",
        "workflow_planning": "workflow_planning",
        "workflow_basic": "workflow_planning",
        "workflow_complex": "workflow_planning",
        "capability_classification": "capability_classification",
        "model_routing": "model_routing",
        "tool_selection": "tool_selection",
        "semantic_grounding": "fact_verification",
        "tool_generation": "tool_generation",
        "code_generation": "code_generation",
        "evidence_extraction": "evidence_extraction",
        "fact_verification": "fact_verification",
        "output": "final_synthesis",
        "final_synthesis": "final_synthesis",
        "stable_synthesis": "final_synthesis",
        "stable_synthesis_strong": "final_synthesis",
        "feedback_learning": "feedback_understanding",
        "feedback_understanding": "feedback_understanding",
    }

    def __init__(self) -> None:
        self.loader = ConfigLoader()

    def ensure_defaults(self) -> None:
        target = RUNTIME_GENERATED / "system_topology" / "model_stage_policy.json"
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(self.default_policy(), ensure_ascii=False, indent=2), encoding="utf-8")

    def load(self) -> dict[str, Any]:
        base = self._load_json(CONFIGS_DIR / "model_stage_policy.seed.json")
        runtime = self._load_json(RUNTIME_GENERATED / "system_topology" / "model_stage_policy.json")
        if not base and not runtime:
            return self.default_policy()
        return self._merge(base or {}, runtime or {})

    def stage_for(self, *, node_id: str | None, adapter: dict[str, Any] | None, route_name: str | None = None) -> str:
        adapter = adapter or {}
        explicit = adapter.get("stage_id") or adapter.get("cognitive_stage") or adapter.get("model_stage")
        for raw in [explicit, route_name, node_id]:
            key = str(raw or "").strip()
            if key:
                return self.STAGE_ALIASES.get(key, key)
        return "general_runtime"

    def policy_for_stage(self, stage_id: str) -> dict[str, Any]:
        policy = self.load()
        stages = policy.get("stages") if isinstance(policy.get("stages"), dict) else {}
        value = stages.get(stage_id) or stages.get("general_runtime") or {}
        return value if isinstance(value, dict) else {}

    def should_escalate_on_validation_failure(self, stage_id: str) -> bool:
        stage = self.policy_for_stage(stage_id)
        validation = stage.get("validation") if isinstance(stage.get("validation"), dict) else {}
        return bool(validation.get("escalate_on_failure", True))

    def escalation_adapter(self, *, adapter: dict[str, Any], stage_id: str, reason: str) -> dict[str, Any]:
        updated = dict(adapter or {})
        updated["model_stage"] = stage_id
        updated["force_model_escalation"] = True
        updated["escalation_reason"] = reason
        return updated

    def apply_to_route(
        self,
        *,
        config: dict[str, Any],
        route: list[str],
        node_id: str,
        adapter: dict[str, Any],
        route_name: str | None,
        escalated: bool = False,
    ) -> tuple[dict[str, Any], list[str], dict[str, Any]]:
        """Return config/route amended with model-specific virtual providers.

        Provider templates remain in providers.yaml.  Model names, tiers, and
        stage bindings remain in model_stage_policy.json.  Missing local models
        are pulled later by the provider handler only when selected.
        """

        stage_id = self.stage_for(node_id=node_id, adapter=adapter, route_name=route_name)
        policy = self.load()
        stage = self.policy_for_stage(stage_id)
        if not stage:
            return config, route, {"stage_id": stage_id, "applied": False}

        candidates = self._candidate_models(stage=stage, escalated=escalated or bool(adapter.get("force_model_escalation")))
        candidates = self._filter_candidates_by_cost(policy=policy, candidates=candidates)
        if not candidates:
            return config, route, {"stage_id": stage_id, "applied": False, "reason": "no_candidate_model"}

        providers = dict(config.get("providers") or {})
        route_candidates: list[str] = []
        catalog = policy.get("model_catalog") if isinstance(policy.get("model_catalog"), dict) else {}

        for model_name in candidates:
            model_meta = catalog.get(model_name)
            if not isinstance(model_meta, dict):
                continue
            provider_template = str(model_meta.get("provider_template") or "").strip()
            if not provider_template or provider_template not in providers:
                continue
            virtual_name = self._virtual_provider_name(stage_id=stage_id, provider_template=provider_template, model_name=model_name)
            virtual_provider = copy.deepcopy(providers[provider_template])
            virtual_provider["model"] = model_name
            virtual_provider["source"] = "model_stage_policy"
            virtual_provider["stage_id"] = stage_id
            virtual_provider["model_tier"] = model_meta.get("tier")
            virtual_provider["cost_class"] = model_meta.get("cost_class")
            virtual_provider["model_family"] = model_meta.get("family")
            virtual_provider["install_strategy"] = model_meta.get("install_strategy")
            virtual_provider["model_tags"] = sorted(set(virtual_provider.get("model_tags") or []) | set(model_meta.get("capabilities") or []))
            virtual_provider["capabilities"] = sorted(set(virtual_provider.get("capabilities") or []) | set(model_meta.get("capabilities") or []))
            if provider_template.startswith("ollama") or virtual_provider.get("protocol") == "ollama_chat":
                fallbacks = [model_name] + [m for m in candidates if m != model_name and self._catalog_provider(catalog, m) == provider_template]
                virtual_provider["fallback_models"] = fallbacks
                virtual_provider["auto_pull_missing_model"] = True
            providers[virtual_name] = virtual_provider
            route_candidates.append(virtual_name)

        if not route_candidates:
            return config, route, {"stage_id": stage_id, "applied": False, "reason": "no_provider_template"}

        amended = dict(config)
        amended["providers"] = providers
        fallback_route = [x for x in route if x not in route_candidates]
        final_route = route_candidates + fallback_route
        metadata = {
            "stage_id": stage_id,
            "applied": True,
            "candidate_models": candidates,
            "virtual_route": route_candidates,
            "cost_policy": policy.get("global_policy", {}).get("cost_policy", {}),
        }
        return amended, final_route, metadata

    def _candidate_models(self, *, stage: dict[str, Any], escalated: bool) -> list[str]:
        if escalated:
            values = list(stage.get("upper_substitutes") or []) + list(stage.get("fallback") or []) + [stage.get("default")]
        else:
            values = [stage.get("default")] + list(stage.get("fallback") or [])
        values.extend(stage.get("lower_substitutes") or [])
        result: list[str] = []
        for value in values:
            model = str(value or "").strip()
            if model and model not in result:
                result.append(model)
        return result

    def _filter_candidates_by_cost(self, *, policy: dict[str, Any], candidates: list[str]) -> list[str]:
        global_policy = policy.get("global_policy") if isinstance(policy.get("global_policy"), dict) else {}
        cost_policy = global_policy.get("cost_policy") if isinstance(global_policy.get("cost_policy"), dict) else {}
        allow_paid = bool(cost_policy.get("allow_paid_models", True))
        catalog = policy.get("model_catalog") if isinstance(policy.get("model_catalog"), dict) else {}
        if allow_paid:
            return candidates
        filtered = []
        for model in candidates:
            meta = catalog.get(model)
            if isinstance(meta, dict) and str(meta.get("cost_class") or "").lower() in {"free", "local"}:
                filtered.append(model)
        return filtered or candidates

    def _catalog_provider(self, catalog: dict[str, Any], model_name: str) -> str:
        meta = catalog.get(model_name)
        if isinstance(meta, dict):
            return str(meta.get("provider_template") or "")
        return ""

    def _virtual_provider_name(self, *, stage_id: str, provider_template: str, model_name: str) -> str:
        safe_model = "".join(ch if ch.isalnum() else "_" for ch in model_name.lower()).strip("_")
        safe_stage = "".join(ch if ch.isalnum() else "_" for ch in stage_id.lower()).strip("_")
        return f"stage_{safe_stage}_{provider_template}_{safe_model}"

    def default_policy(self) -> dict[str, Any]:
        return {
            "version": "2.9.1",
            "description": "Generic stage-bound model policy. No business-domain keywords or task-specific rules.",
            "global_policy": {
                "cost_policy": {
                    "allow_paid_models": True,
                    "prefer_local_when_quality_sufficient": True,
                    "missing_paid_key_action": "skip_and_try_lower_substitute"
                },
                "missing_model_policy": {
                    "local_model_action": "download_on_demand",
                    "external_model_action": "use_when_key_available",
                    "unknown_stage_action": "ask_strong_model_for_model_recommendation_then_persist_candidate"
                },
                "routing_control": {
                    "model_routing_is_deterministic": True,
                    "llm_may_only_propose_candidates": True,
                    "capability_routing_uses_taxonomy_first": True,
                    "execution_mode_uses_policy_first": True
                }
            },
            "model_catalog": {
                "qwen3:1.7b": {"provider_template": "ollama", "family": "qwen", "tier": "local_small", "cost_class": "free", "install_strategy": "on_demand", "capabilities": ["json_generation", "short_context"]},
                "qwen2.5:3b": {"provider_template": "ollama", "family": "qwen", "tier": "local_small", "cost_class": "free", "install_strategy": "on_demand", "capabilities": ["json_generation", "structured_extraction"]},
                "qwen3:4b": {"provider_template": "ollama", "family": "qwen", "tier": "local_basic", "cost_class": "free", "install_strategy": "on_demand", "capabilities": ["json_generation", "structured_extraction", "reasoning"]},
                "qwen3:8b": {"provider_template": "ollama", "family": "qwen", "tier": "local_standard", "cost_class": "free", "install_strategy": "on_demand", "capabilities": ["json_generation", "structured_extraction", "reasoning"]},
                "qwen3:14b": {"provider_template": "ollama", "family": "qwen", "tier": "local_high", "cost_class": "free", "install_strategy": "on_demand", "capabilities": ["json_generation", "structured_extraction", "reasoning", "planning"]},
                "qwen3:32b": {"provider_template": "ollama", "family": "qwen", "tier": "local_strong", "cost_class": "free", "install_strategy": "on_demand", "capabilities": ["json_generation", "reasoning", "workflow_planning", "stable_synthesis"]},
                "qwen2.5-coder:7b": {"provider_template": "ollama_coder_qwen25", "family": "qwen_coder", "tier": "local_coder", "cost_class": "free", "install_strategy": "on_demand", "capabilities": ["code_generation", "tool_generation", "schema_repair", "json_generation"]},
                "qwen2.5-coder:14b": {"provider_template": "ollama_coder_qwen25", "family": "qwen_coder", "tier": "local_coder_high", "cost_class": "free", "install_strategy": "on_demand", "capabilities": ["code_generation", "tool_generation", "schema_repair", "json_generation"]},
                "deepseek-coder-v2:16b": {"provider_template": "ollama_coder_deepseek", "family": "deepseek_coder", "tier": "local_coder_high", "cost_class": "free", "install_strategy": "on_demand", "capabilities": ["code_generation", "tool_generation", "schema_repair", "json_generation"]},
                "gpt-4o-mini": {"provider_template": "openai", "family": "openai", "tier": "external_standard", "cost_class": "paid", "install_strategy": "key_required", "capabilities": ["json_generation", "reasoning", "structured_extraction", "workflow_planning"]},
                "gpt-4.1": {"provider_template": "openai", "family": "openai", "tier": "external_strong", "cost_class": "paid", "install_strategy": "key_required", "capabilities": ["json_generation", "reasoning", "workflow_planning", "stable_synthesis", "evidence_verification"]},
                "gpt-5.x": {"provider_template": "openai", "family": "openai", "tier": "external_top", "cost_class": "paid", "install_strategy": "key_required", "capabilities": ["json_generation", "reasoning", "workflow_planning", "stable_synthesis", "evidence_verification", "code_generation"]},
                "claude-sonnet": {"provider_template": "claude", "family": "claude", "tier": "external_strong", "cost_class": "paid", "install_strategy": "key_required", "capabilities": ["reasoning", "stable_synthesis", "code_generation", "document_generation"]}
            },
            "stages": {
                "input_parsing": {"default": "qwen3:8b", "fallback": ["qwen3:14b", "gpt-4o-mini"], "upper_substitutes": ["qwen3:14b", "gpt-4o-mini"], "lower_substitutes": ["qwen3:4b", "qwen2.5:3b"], "validation": {"schema_required": True, "escalate_on_failure": True}},
                "simple_intent": {"default": "qwen3:8b", "fallback": ["qwen3:14b"], "upper_substitutes": ["qwen3:14b", "gpt-4o-mini"], "lower_substitutes": ["qwen3:4b"], "validation": {"schema_required": True, "escalate_on_failure": True}},
                "complex_intent": {"default": "qwen3:32b", "fallback": ["gpt-4o-mini"], "upper_substitutes": ["gpt-4.1", "gpt-5.x"], "lower_substitutes": ["qwen3:14b"], "validation": {"schema_required": True, "escalate_on_failure": True}},
                "workflow_planning": {"default": "qwen3:32b", "fallback": ["gpt-4.1", "gpt-5.x"], "upper_substitutes": ["gpt-4.1", "gpt-5.x"], "lower_substitutes": ["qwen3:14b"], "validation": {"schema_required": True, "escalate_on_failure": True}},
                "capability_classification": {"default": "deterministic_taxonomy", "fallback": ["qwen3:14b", "gpt-4o-mini"], "upper_substitutes": ["gpt-4.1"], "lower_substitutes": ["qwen3:8b"], "validation": {"schema_required": True, "escalate_on_failure": True}},
                "model_routing": {"default": "deterministic_runtime_policy", "fallback": [], "upper_substitutes": [], "lower_substitutes": [], "validation": {"schema_required": True, "escalate_on_failure": False}},
                "tool_selection": {"default": "deterministic_registry", "fallback": ["qwen3:14b", "gpt-4o-mini"], "upper_substitutes": ["gpt-4.1"], "lower_substitutes": ["qwen3:8b"], "validation": {"schema_required": True, "escalate_on_failure": True}},
                "tool_generation": {"default": "qwen2.5-coder:7b", "fallback": ["deepseek-coder-v2:16b", "qwen2.5-coder:14b"], "upper_substitutes": ["gpt-5.x", "claude-sonnet"], "lower_substitutes": ["qwen3:8b"], "validation": {"schema_required": True, "escalate_on_failure": True}},
                "code_generation": {"default": "qwen2.5-coder:7b", "fallback": ["deepseek-coder-v2:16b", "qwen2.5-coder:14b"], "upper_substitutes": ["gpt-5.x", "claude-sonnet"], "lower_substitutes": ["qwen3:8b"], "validation": {"schema_required": True, "escalate_on_failure": True}},
                "evidence_extraction": {"default": "qwen3:14b", "fallback": ["gpt-4o-mini"], "upper_substitutes": ["gpt-4.1"], "lower_substitutes": ["qwen3:8b"], "validation": {"schema_required": True, "escalate_on_failure": True}},
                "fact_verification": {"default": "gpt-4.1", "fallback": ["qwen3:32b", "gpt-5.x"], "upper_substitutes": ["gpt-5.x"], "lower_substitutes": ["qwen3:14b"], "validation": {"schema_required": True, "escalate_on_failure": True}},
                "final_synthesis": {"default": "gpt-4.1", "fallback": ["gpt-5.x", "claude-sonnet", "qwen3:32b"], "upper_substitutes": ["gpt-5.x", "claude-sonnet"], "lower_substitutes": ["qwen3:32b", "qwen3:14b"], "validation": {"schema_required": True, "escalate_on_failure": True}, "raw_evidence_policy": {"weak_model_direct_raw_evidence": False, "use_reduced_fact_material": True}},
                "feedback_understanding": {"default": "qwen3:8b", "fallback": ["qwen3:14b", "gpt-4o-mini"], "upper_substitutes": ["gpt-4.1"], "lower_substitutes": ["qwen3:4b"], "validation": {"schema_required": True, "escalate_on_failure": True}},
                "general_runtime": {"default": "qwen3:8b", "fallback": ["qwen3:14b", "gpt-4o-mini"], "upper_substitutes": ["gpt-4.1"], "lower_substitutes": ["qwen3:4b"], "validation": {"schema_required": True, "escalate_on_failure": True}}
            }
        }

    def _load_json(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}

    def _merge(self, left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
        result = dict(left or {})
        for key, value in (right or {}).items():
            if isinstance(value, dict) and isinstance(result.get(key), dict):
                result[key] = self._merge(result[key], value)
            else:
                result[key] = value
        return result
