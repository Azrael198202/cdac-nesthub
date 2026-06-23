from __future__ import annotations

import copy
import json
from pathlib import Path
from ai_core.safe_collections import safe_string_set
from typing import Any

from ai_core.config.loader import ConfigLoader
from ai_core.config.paths import CONFIGS_DIR, RUNTIME_GENERATED
from ai_core.runtime.modeling.runtime_execution_policy import RuntimeExecutionPolicy
from ai_core.runtime.modeling.user_model_selection import UserModelSelectionStore


class ModelStagePolicy:
    """Domain-neutral runtime model governance resolver.

    The resolver is deliberately not a business router.  It only reads a generic
    model governance policy and converts a runtime stage into ordered provider
    candidates.  The policy may contain text, code, audio, image, video, and
    file/artifact capabilities, but those are modality/capability labels rather
    than domain-specific rules.
    """

    STAGE_ALIASES = {
        # language / intent
        "input_parsing": "input_parsing",
        "parse_input": "input_parsing",
        "language_detection": "language_detection",
        "intent_recognition": "simple_intent",
        "simple_intent": "simple_intent",
        "intent_simple": "simple_intent",
        "complex_intent": "complex_intent",
        "intent_complex": "complex_intent",
        "translation": "translation",
        # governance
        "workflow_planning": "workflow_planning",
        "workflow_basic": "workflow_planning",
        "workflow_complex": "workflow_planning",
        "capability_classification": "capability_classification",
        "execution_mode": "execution_mode_decision",
        "execution_mode_decision": "execution_mode_decision",
        "model_routing": "model_routing",
        "tool_selection": "tool_selection",
        "semantic_grounding": "fact_verification",
        # code / tools / schemas
        "tool_generation": "tool_generation",
        "code_generation": "code_generation",
        "code_review": "code_review",
        "schema_design": "schema_design",
        "schema_repair": "schema_repair",
        # retrieval / evidence
        "embedding": "embedding_generation",
        "embedding_generation": "embedding_generation",
        "retrieval_query_rewrite": "retrieval_query_rewrite",
        "reranking": "reranking",
        "evidence_extraction": "evidence_extraction",
        "evidence_compression": "evidence_compression",
        "fact_verification": "fact_verification",
        # final / feedback / memory
        "output": "final_synthesis",
        "final_synthesis": "final_synthesis",
        "stable_synthesis": "final_synthesis",
        "stable_synthesis_strong": "final_synthesis",
        "feedback_learning": "feedback_understanding",
        "feedback_understanding": "feedback_understanding",
        "memory_update": "memory_update",
        # artifact generation
        "document_generation": "document_generation",
        "report_generation": "report_generation",
        "plan_generation": "plan_generation",
        "slide_generation": "slide_generation",
        "presentation_generation": "slide_generation",
        "spreadsheet_generation": "spreadsheet_generation",
        "pdf_generation": "pdf_generation",
        "file_generation": "document_generation",
        "file_transformation": "file_transformation",
        "diagram_generation": "diagram_generation",
        "document_rendering": "document_rendering",
        "spreadsheet_rendering": "spreadsheet_rendering",
        "slide_rendering": "slide_rendering",
        "pdf_rendering": "pdf_rendering",
        "diagram_rendering": "diagram_rendering",
        "file_packaging": "file_packaging",
        # audio
        "stt": "speech_to_text",
        "speech_to_text": "speech_to_text",
        "tts": "text_to_speech",
        "text_to_speech": "text_to_speech",
        "audio_generation": "audio_generation",
        # image / vision
        "vision": "image_understanding",
        "image_understanding": "image_understanding",
        "image_generation": "image_generation",
        "image_editing": "image_editing",
        # video
        "video_understanding": "video_understanding",
        "video_generation": "video_generation",
        "general_runtime": "general_runtime",
    }

    INTERNAL_PROVIDER_TEMPLATES = {"internal"}

    def __init__(self) -> None:
        self.loader = ConfigLoader()
        self.runtime_execution_policy = RuntimeExecutionPolicy()
        self.user_model_selection = UserModelSelectionStore()

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
        merged = self._merge(base or {}, runtime or {})
        return merged if isinstance(merged, dict) else self.default_policy()

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
        if not isinstance(value, dict):
            return {}
        defaults = policy.get("stage_defaults") if isinstance(policy.get("stage_defaults"), dict) else {}
        return self._merge(defaults, value)

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

    def models_for_stage(self, stage_id: str, *, escalated: bool = False, free_only: bool | None = None) -> list[dict[str, Any]]:
        """Return catalog entries in the exact order the runtime would prefer.

        This method is useful for tests, diagnostics, UI display, and future
        runtime learning jobs that need to inspect policy without invoking a
        provider.
        """
        policy = self.load()
        stage = self.policy_for_stage(stage_id)
        candidates = self._candidate_models(stage=stage, escalated=escalated)
        if free_only is not None:
            policy = self._override_paid_policy(policy, allow_paid=not free_only)
        candidates = self._filter_candidates_by_cost(policy=policy, candidates=candidates)
        candidates = self._filter_candidates_by_stage_requirements(policy=policy, stage=stage, candidates=candidates)
        catalog = policy.get("model_catalog") if isinstance(policy.get("model_catalog"), dict) else {}
        result = []
        for model_id in candidates:
            meta = catalog.get(model_id)
            if isinstance(meta, dict):
                item = dict(meta)
                item["model_id"] = model_id
                result.append(item)
        return result

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
        """Return config and route amended with stage-specific virtual providers.

        Provider templates remain in providers.yaml.  Model names, tiers,
        modality/capability tags, and stage bindings remain in the model stage
        policy.  Local models are only downloaded by provider handlers if a
        selected provider supports on-demand installation.
        """

        stage_id = self.stage_for(node_id=node_id, adapter=adapter, route_name=route_name)
        policy = self.load()
        stage = self.policy_for_stage(stage_id)
        if not stage:
            return config, route, {"stage_id": stage_id, "applied": False, "reason": "stage_not_found"}

        force_escalation = escalated or bool(adapter.get("force_model_escalation"))
        candidates = self._candidate_models(stage=stage, escalated=force_escalation)
        candidates = self.user_model_selection.reorder_candidates(candidates, escalated=force_escalation)
        candidates = self._filter_candidates_by_current_mode(policy=policy, candidates=candidates)
        candidates = self._filter_candidates_by_cost(policy=policy, candidates=candidates)
        candidates = self._filter_candidates_by_stage_requirements(policy=policy, stage=stage, candidates=candidates)
        if not candidates:
            return config, route, {"stage_id": stage_id, "applied": False, "reason": "no_candidate_model"}

        providers = dict(config.get("providers") or {})
        route_candidates: list[str] = []
        catalog = policy.get("model_catalog") if isinstance(policy.get("model_catalog"), dict) else {}
        skipped: list[dict[str, str]] = []

        for model_id in candidates:
            model_meta = catalog.get(model_id)
            if not isinstance(model_meta, dict):
                skipped.append({"model": model_id, "reason": "not_in_catalog"})
                continue

            provider_templates = self._provider_templates_for_model(
                policy=policy,
                stage=stage,
                model_meta=model_meta,
                catalog=catalog,
                model_id=model_id,
            )
            if not provider_templates:
                skipped.append({"model": model_id, "reason": "provider_template_filtered_by_runtime_policy"})
                continue

            for provider_template in provider_templates:
                if provider_template in self.INTERNAL_PROVIDER_TEMPLATES:
                    skipped.append({"model": model_id, "provider_template": provider_template, "reason": "internal_policy_component"})
                    continue
                if not provider_template or provider_template not in providers:
                    skipped.append({"model": model_id, "provider_template": provider_template, "reason": "provider_template_missing"})
                    continue

                virtual_name = self._virtual_provider_name(stage_id=stage_id, provider_template=provider_template, model_name=model_id)
                virtual_provider = copy.deepcopy(providers[provider_template])
                virtual_provider["model"] = self._provider_model_for_template(model_meta=model_meta, provider_template=provider_template, model_id=model_id)
                virtual_provider["model_id"] = model_id
                virtual_provider["source"] = "model_stage_policy"
                virtual_provider["stage_id"] = stage_id
                virtual_provider["model_tier"] = model_meta.get("tier")
                virtual_provider["cost_class"] = model_meta.get("cost_class")
                virtual_provider["deployment"] = model_meta.get("deployment")
                virtual_provider["model_family"] = model_meta.get("family")
                virtual_provider["install_strategy"] = model_meta.get("install_strategy")
                virtual_provider["allow_external"] = model_meta.get("allow_external", virtual_provider.get("allow_external"))
                virtual_provider["modalities"] = model_meta.get("modalities", virtual_provider.get("modalities", {}))
                tags = safe_string_set(virtual_provider.get("model_tags") or []) | safe_string_set(model_meta.get("capabilities") or [])
                caps = safe_string_set(virtual_provider.get("capabilities") or []) | safe_string_set(model_meta.get("capabilities") or [])
                virtual_provider["model_tags"] = sorted(tags)
                virtual_provider["capabilities"] = sorted(caps)
                if model_meta.get("context_window_hint") and not virtual_provider.get("context_window"):
                    virtual_provider["context_window"] = model_meta.get("context_window_hint")

                if self._is_ollama_provider(provider_template, virtual_provider):
                    fallbacks = [
                        self._provider_model_for_template(model_meta=catalog[m], provider_template=provider_template, model_id=m)
                        for m in candidates
                        if isinstance(catalog.get(m), dict)
                        and provider_template in self._provider_templates_for_model(policy=policy, stage=stage, model_meta=catalog[m], catalog=catalog, model_id=m)
                        and provider_template not in self.INTERNAL_PROVIDER_TEMPLATES
                    ]
                    virtual_provider["fallback_models"] = list(dict.fromkeys(fallbacks))
                    virtual_provider["auto_pull_missing_model"] = model_meta.get("install_strategy") in {
                        "on_demand", "on_demand_or_package", "manual_or_on_demand"
                    }
                providers[virtual_name] = virtual_provider
                route_candidates.append(virtual_name)

        if not route_candidates:
            execution_mode = str(stage.get("execution_mode") or "")
            if execution_mode in {"deterministic_only", "deterministic_first", "parser_first", "embedding_provider"}:
                return config, route, {
                    "stage_id": stage_id,
                    "applied": False,
                    "reason": "policy_resolved_to_internal_or_non_llm_component",
                    "candidate_models": candidates,
                    "skipped": skipped,
                    "execution_mode": execution_mode,
                }
            return config, route, {"stage_id": stage_id, "applied": False, "reason": "no_provider_template", "skipped": skipped}

        amended = dict(config)
        amended["providers"] = providers
        fallback_route = [x for x in route if x not in route_candidates]
        runtime_policy = self._local_model_policy(policy)
        if not runtime_policy["enabled"] and runtime_policy["api_only_when_disabled"]:
            fallback_route = [
                x for x in fallback_route
                if not self._route_provider_is_local(provider_name=x, providers=providers)
            ]
        final_route = route_candidates + fallback_route
        metadata = {
            "stage_id": stage_id,
            "applied": True,
            "candidate_models": candidates,
            "virtual_route": route_candidates,
            "skipped": skipped,
            "execution_mode": stage.get("execution_mode"),
            "required_capabilities": stage.get("required_capabilities", []),
            "required_modalities": stage.get("required_modalities", {}),
            "cost_policy": policy.get("global_policy", {}).get("cost_policy", {}),
            "privacy_policy": stage.get("privacy_policy", {}),
        }
        return amended, final_route, metadata

    def _candidate_models(self, *, stage: dict[str, Any], escalated: bool) -> list[str]:
        if not isinstance(stage, dict):
            return []
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

    def _filter_candidates_by_current_mode(self, *, policy: dict[str, Any], candidates: list[str]) -> list[str]:
        catalog = policy.get("model_catalog") if isinstance(policy.get("model_catalog"), dict) else {}
        snap = self.user_model_selection.snapshot()
        filtered: list[str] = []
        for model_id in candidates:
            meta = catalog.get(model_id) if isinstance(catalog, dict) else None
            if not isinstance(meta, dict):
                filtered.append(model_id)
                continue
            family = self.user_model_selection.family_for_model_meta(meta)
            if snap.mode == "local_only" and family != "local":
                continue
            if snap.mode == "api_only" and family != "api":
                continue
            filtered.append(model_id)
        return filtered

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
            if isinstance(meta, dict) and str(meta.get("cost_class") or "").lower() in {"free", "local", "internal"}:
                filtered.append(model)
        return filtered or candidates

    def _filter_candidates_by_stage_requirements(self, *, policy: dict[str, Any], stage: dict[str, Any], candidates: list[str]) -> list[str]:
        catalog = policy.get("model_catalog") if isinstance(policy.get("model_catalog"), dict) else {}
        selection = stage.get("selection") if isinstance(stage.get("selection"), dict) else {}
        require_capability = bool(selection.get("require_capability_match", False))
        require_modality = bool(selection.get("require_modality_match", False))
        allow_candidate = bool(selection.get("allow_candidate_status", True))
        required_caps = {str(x) for x in stage.get("required_capabilities", []) or [] if str(x)}
        required_input = {str(x) for x in ((stage.get("required_modalities") or {}).get("input") or []) if str(x)}
        required_output = {str(x) for x in ((stage.get("required_modalities") or {}).get("output") or []) if str(x)}

        filtered: list[str] = []
        for model in candidates:
            meta = catalog.get(model)
            if not isinstance(meta, dict):
                continue
            status = str(meta.get("status") or "approved")
            if not allow_candidate and status not in {"approved", "available"}:
                continue
            caps = {str(x) for x in meta.get("capabilities", []) or [] if str(x)}
            if require_capability and required_caps and not (required_caps & caps):
                continue
            modalities = meta.get("modalities") if isinstance(meta.get("modalities"), dict) else {}
            model_input = {str(x) for x in modalities.get("input", []) or [] if str(x)}
            model_output = {str(x) for x in modalities.get("output", []) or [] if str(x)}
            if require_modality:
                if required_input and model_input and not (required_input & model_input):
                    continue
                if required_output and model_output and not (required_output & model_output):
                    continue
            filtered.append(model)
        return filtered or candidates

    def _override_paid_policy(self, policy: dict[str, Any], *, allow_paid: bool) -> dict[str, Any]:
        updated = copy.deepcopy(policy)
        updated.setdefault("global_policy", {}).setdefault("cost_policy", {})["allow_paid_models"] = allow_paid
        return updated



    def _route_provider_is_local(self, *, provider_name: str, providers: dict[str, Any]) -> bool:
        provider = providers.get(provider_name) if isinstance(providers, dict) else None
        if not isinstance(provider, dict):
            return provider_name in {"vllm", "vllm_coder", "ollama", "ollama_coder_qwen25", "ollama_coder_deepseek", "ollama_embedding", "lmstudio", "lmstudio_coder"}
        role = str(provider.get("role") or "").lower()
        base_url = str(provider.get("base_url") or "").lower()
        tags = {str(x).lower() for x in provider.get("model_tags", []) or []}
        protocol = str(provider.get("protocol") or "").lower()
        if role.startswith("external"):
            return False
        return (
            provider_name in {"vllm", "vllm_coder", "ollama", "ollama_coder_qwen25", "ollama_coder_deepseek", "ollama_embedding", "lmstudio", "lmstudio_coder"}
            or "local" in tags
            or protocol.startswith("ollama")
            or "127.0.0.1" in base_url
            or "localhost" in base_url
        )

    def _local_model_policy(self, policy: dict[str, Any]) -> dict[str, Any]:
        snapshot = self.runtime_execution_policy.snapshot(policy=policy)
        return {
            "enabled": snapshot.local_enabled,
            "default_provider_order": snapshot.local_provider_order,
            "code_provider_order": snapshot.local_code_provider_order,
            "api_provider_order": snapshot.api_provider_order,
            "api_only_when_disabled": snapshot.api_only_when_local_disabled,
        }

    def _is_local_model(self, model_meta: dict[str, Any]) -> bool:
        deployment = str(model_meta.get("deployment") or "").lower()
        cost_class = str(model_meta.get("cost_class") or "").lower()
        provider_template = str(model_meta.get("provider_template") or "").lower()
        return deployment in {"local", "local_runtime", "local_service", "local_model"} or cost_class in {"free", "local"} or provider_template in {"vllm", "vllm_coder", "ollama", "ollama_coder_qwen25", "ollama_coder_deepseek", "ollama_embedding"}

    def _is_api_model(self, model_meta: dict[str, Any]) -> bool:
        deployment = str(model_meta.get("deployment") or "").lower()
        cost_class = str(model_meta.get("cost_class") or "").lower()
        provider_template = str(model_meta.get("provider_template") or "").lower()
        return deployment in {"api", "remote_api", "external_api", "managed_api"} or cost_class in {"paid", "metered"} or provider_template in {"openai", "claude"}

    def _provider_templates_for_model(
        self,
        *,
        policy: dict[str, Any],
        stage: dict[str, Any],
        model_meta: dict[str, Any],
        catalog: dict[str, Any],
        model_id: str,
    ) -> list[str]:
        runtime_policy = self._local_model_policy(policy)
        declared = str(model_meta.get("provider_template") or "").strip()
        explicit = [str(x).strip() for x in model_meta.get("provider_templates", []) or [] if str(x).strip()]
        fallbacks = [str(x).strip() for x in model_meta.get("fallback_provider_templates", []) or [] if str(x).strip()]
        templates = explicit or ([declared] if declared else [])
        templates.extend(x for x in fallbacks if x not in templates)

        if self._is_local_model(model_meta):
            if not runtime_policy["enabled"] and runtime_policy["api_only_when_disabled"]:
                return []
            provider_order_key = "code_provider_order" if ("code_generation" in {str(x) for x in model_meta.get("capabilities", []) or []}) else "default_provider_order"
            preferred = runtime_policy.get(provider_order_key) or runtime_policy["default_provider_order"]
            local_known = {"vllm", "vllm_coder", "ollama", "ollama_coder_qwen25", "ollama_coder_deepseek", "ollama_embedding", "lmstudio", "lmstudio_coder"}
            compatible = [x for x in preferred if self._provider_can_host_model(provider_template=x, model_meta=model_meta)]
            compatible.extend(x for x in templates if x in local_known and x not in compatible)
            return compatible or templates

        if self._is_api_model(model_meta):
            api_order = runtime_policy["api_provider_order"]
            compatible = [x for x in api_order if self._provider_can_host_model(provider_template=x, model_meta=model_meta)]
            compatible.extend(x for x in templates if x not in compatible)
            return compatible or templates

        return templates

    def _provider_can_host_model(self, *, provider_template: str, model_meta: dict[str, Any]) -> bool:
        provider_template = str(provider_template or "")
        family = str(model_meta.get("family") or "").lower()
        caps = {str(x) for x in model_meta.get("capabilities", []) or []}
        if provider_template == "vllm_coder":
            return "code_generation" in caps or "coder" in family
        if provider_template == "vllm":
            return "code_generation" not in caps
        if provider_template.startswith("ollama_coder"):
            return "code_generation" in caps or "coder" in family
        if provider_template == "ollama":
            return "code_generation" not in caps
        if provider_template in {"openai", "claude"}:
            return True
        return True

    def _provider_model_for_template(self, *, model_meta: dict[str, Any], provider_template: str, model_id: str) -> str:
        provider_models = model_meta.get("provider_models") if isinstance(model_meta.get("provider_models"), dict) else {}
        if provider_template in provider_models:
            return str(provider_models[provider_template])
        provider_model = str(model_meta.get("provider_model") or "").strip()
        if provider_model:
            return provider_model
        return str(model_id)

    def _catalog_provider(self, catalog: dict[str, Any], model_name: str) -> str:
        meta = catalog.get(model_name)
        if isinstance(meta, dict):
            return str(meta.get("provider_template") or "")
        return ""

    def _is_ollama_provider(self, provider_template: str, provider: dict[str, Any]) -> bool:
        return provider_template.startswith("ollama") or provider.get("protocol") == "ollama_chat"

    def _virtual_provider_name(self, *, stage_id: str, provider_template: str, model_name: str) -> str:
        safe_model = "".join(ch if ch.isalnum() else "_" for ch in model_name.lower()).strip("_")
        safe_stage = "".join(ch if ch.isalnum() else "_" for ch in stage_id.lower()).strip("_")
        return f"stage_{safe_stage}_{provider_template}_{safe_model}"

    def default_policy(self) -> dict[str, Any]:
        seed = self._load_json(CONFIGS_DIR / "model_stage_policy.seed.json")
        if seed:
            return seed
        return {
            "version": "2.9.2",
            "policy_kind": "runtime_model_governance_policy",
            "global_policy": {},
            "model_catalog": {},
            "stages": {"general_runtime": {"default": "qwen3.5:2b", "fallback": [], "upper_substitutes": [], "lower_substitutes": [], "validation": {"schema_required": True, "escalate_on_failure": True}}},
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
