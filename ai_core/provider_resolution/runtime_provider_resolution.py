from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ai_core.config.paths import RUNTIME_SESSIONS


class RuntimeProviderResolution:
    """Creates runtime provider binding artifacts from an already locked plan.

    The resolver is intentionally domain-neutral. It copies only provider
    candidates, capability identifiers, execution methods, and source policies
    that were supplied by upstream runtime state or by the locked workflow plan.
    It does not invent concrete providers, endpoints, domains, or facts.
    """

    def __init__(self, runtime_sessions: Path | None = None) -> None:
        self.runtime_sessions = runtime_sessions or RUNTIME_SESSIONS

    def resolve(
        self,
        *,
        run_id: str,
        execution_plan: dict[str, Any],
        runtime_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        runtime_context = runtime_context or {}
        steps = self._steps(execution_plan)
        provider_catalog = self._provider_catalog(runtime_context)
        selected: list[dict[str, Any]] = []
        unresolved: list[dict[str, Any]] = []

        for step in steps:
            step_id = str(step.get("step_id") or step.get("id") or f"step_{len(selected) + len(unresolved) + 1}")
            required = self._required_capabilities(step)
            for capability in required:
                candidates = self._candidates_for(capability=capability, step=step, provider_catalog=provider_catalog)
                if candidates:
                    primary = candidates[0]
                    selected.append({
                        "step_id": step_id,
                        "capability": capability,
                        "selected_provider": primary,
                        "fallbacks": candidates[1:],
                        "execution_method": step.get("execution_method") or primary.get("execution_method") or primary.get("type"),
                        "source_policy": self._source_policy(step=step, runtime_context=runtime_context),
                    })
                else:
                    unresolved.append({
                        "step_id": step_id,
                        "capability": capability,
                        "reason": "no_runtime_provider_contract_available",
                    })

        artifact = {
            "version": "4.0",
            "kind": "runtime_provider_resolution",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "run_id": run_id,
            "providers": selected,
            "unresolved": unresolved,
            "policy": {
                "domain_neutral_core": True,
                "runtime_generated": True,
                "execution_must_use_bound_providers_only": True,
            },
        }
        output_dir = self.runtime_sessions / run_id / "provider_resolution"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / "structured_api_providers.json"
        output_path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8")
        return {
            "status": "success" if not unresolved else "partial",
            "provider_resolution_record": artifact,
            "artifact_path": str(output_path),
        }

    def _steps(self, execution_plan: dict[str, Any]) -> list[dict[str, Any]]:
        raw = execution_plan.get("steps") or execution_plan.get("nodes") or []
        return [item for item in raw if isinstance(item, dict)]

    def _required_capabilities(self, step: dict[str, Any]) -> list[str]:
        raw = step.get("required_capabilities") or step.get("capabilities") or step.get("required_tools") or []
        if isinstance(raw, str):
            return [raw]
        if isinstance(raw, list):
            values = []
            for item in raw:
                if isinstance(item, str):
                    values.append(item)
                elif isinstance(item, dict) and isinstance(item.get("capability"), str):
                    values.append(item["capability"])
            return values
        return []

    def _provider_catalog(self, runtime_context: dict[str, Any]) -> list[dict[str, Any]]:
        raw = runtime_context.get("provider_catalog") or runtime_context.get("provider_candidates") or []
        if isinstance(raw, dict):
            raw = raw.get("providers") or []
        return [item for item in raw if isinstance(item, dict)]

    def _candidates_for(self, *, capability: str, step: dict[str, Any], provider_catalog: list[dict[str, Any]]) -> list[dict[str, Any]]:
        inline = step.get("provider_candidates") or step.get("structured_providers") or []
        candidates = [item for item in inline if isinstance(item, dict)]
        for provider in provider_catalog:
            caps = provider.get("capabilities") or provider.get("capability") or []
            if isinstance(caps, str):
                caps = [caps]
            if capability in caps:
                candidates.append(provider)
        return self._dedupe(candidates)

    def _source_policy(self, *, step: dict[str, Any], runtime_context: dict[str, Any]) -> dict[str, Any]:
        policy = {}
        if isinstance(runtime_context.get("source_policy"), dict):
            policy.update(runtime_context["source_policy"])
        if isinstance(step.get("source_policy"), dict):
            policy.update(step["source_policy"])
        return policy

    def _dedupe(self, providers: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seen: set[str] = set()
        result: list[dict[str, Any]] = []
        for provider in providers:
            key = str(provider.get("id") or provider.get("name") or provider)
            if key in seen:
                continue
            seen.add(key)
            result.append(provider)
        return result
