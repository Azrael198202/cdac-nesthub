from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ai_core.config.paths import CONFIGS_DIR, RUNTIME_GENERATED


class CapabilityInference:
    """Infers a generic capability from runtime policy files.

    The core does not embed task vocabulary.  Semantic trigger terms live in
    JSON policy files that can be generated or edited at runtime.
    """

    def infer(self, *, step: dict[str, Any], plan: dict[str, Any] | None = None, state: dict[str, Any] | None = None) -> dict[str, Any] | None:
        text = self._contract_text([step, plan or {}, state or {}])
        if not text.strip():
            return None
        best: dict[str, Any] | None = None
        best_score = 0.0
        for rule in self._rules():
            if not isinstance(rule, dict):
                continue
            if self._excluded(text, rule):
                continue
            score = self._score(text, rule)
            if score > best_score:
                best_score = score
                best = rule
        if not best or best_score <= 0:
            return None
        capability = str(best.get("capability") or "").strip()
        if not capability:
            return None
        return {
            "capability": capability,
            "confidence": float(best.get("confidence") or best_score),
            "rule_id": best.get("rule_id"),
            "default_parameters": best.get("default_parameters") if isinstance(best.get("default_parameters"), dict) else {},
            "execution_strategy": best.get("execution_strategy") if isinstance(best.get("execution_strategy"), list) else [],
            "metadata": best.get("metadata") if isinstance(best.get("metadata"), dict) else {},
        }

    def apply_to_step(self, *, step: dict[str, Any], plan: dict[str, Any] | None = None, state: dict[str, Any] | None = None) -> dict[str, Any]:
        if step.get("required_capability") or step.get("capability"):
            return step
        inferred = self.infer(step=step, plan=plan, state=state)
        if not inferred:
            return step
        result = dict(step)
        result["required_capability"] = inferred["capability"]
        result["capability_inference"] = {
            "status": "inferred",
            "rule_id": inferred.get("rule_id"),
            "confidence": inferred.get("confidence"),
            "metadata": inferred.get("metadata") or {},
        }
        params = result.get("parameters") if isinstance(result.get("parameters"), dict) else {}
        default_params = inferred.get("default_parameters") if isinstance(inferred.get("default_parameters"), dict) else {}
        result["parameters"] = self._merge_params(default_params, params)
        if inferred.get("execution_strategy") and not result.get("execution_strategy"):
            result["execution_strategy"] = inferred.get("execution_strategy")
        return result

    def _rules(self) -> list[dict[str, Any]]:
        rules: list[dict[str, Any]] = []
        for path in [
            CONFIGS_DIR / "runtime_capability_inference.seed.json",
            RUNTIME_GENERATED / "system_topology" / "runtime_capability_inference.json",
            RUNTIME_GENERATED / "contracts" / "runtime_capability_inference.json",
        ]:
            if not path.exists():
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8") or "{}")
            except Exception:
                continue
            if isinstance(data, dict) and isinstance(data.get("rules"), list):
                rules.extend(x for x in data["rules"] if isinstance(x, dict))
        return rules

    def _score(self, text: str, rule: dict[str, Any]) -> float:
        sets = rule.get("match_any_token_sets")
        if not isinstance(sets, list):
            return 0.0
        best = 0.0
        for raw_set in sets:
            tokens = [str(x).casefold().strip() for x in raw_set if str(x).strip()] if isinstance(raw_set, list) else []
            if not tokens:
                continue
            matched = sum(1 for token in tokens if token in text)
            if matched == len(tokens):
                best = max(best, matched / max(len(tokens), 1))
        return best

    def _excluded(self, text: str, rule: dict[str, Any]) -> bool:
        sets = rule.get("exclude_if_any_token_sets")
        if not isinstance(sets, list):
            return False
        for raw_set in sets:
            tokens = [str(x).casefold().strip() for x in raw_set if str(x).strip()] if isinstance(raw_set, list) else []
            if tokens and all(token in text for token in tokens):
                return True
        return False

    def _merge_params(self, default_params: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
        result = {
            "known": {},
            "optional": {},
            "missing_required": {},
        }
        for source in (default_params, params):
            if not isinstance(source, dict):
                continue
            if any(k in source for k in ["known", "optional", "missing_required"]):
                for key in result:
                    value = source.get(key)
                    if isinstance(value, dict) and isinstance(result[key], dict):
                        result[key].update(value)
                    elif isinstance(value, list):
                        result[key] = value
            else:
                result["known"].update(source)
        return result

    def _contract_text(self, values: list[Any]) -> str:
        parts: list[str] = []

        def walk(value: Any) -> None:
            if isinstance(value, str):
                parts.append(value)
            elif isinstance(value, (int, float, bool)):
                parts.append(str(value))
            elif isinstance(value, dict):
                for key, child in value.items():
                    parts.append(str(key))
                    walk(child)
            elif isinstance(value, list):
                for child in value:
                    walk(child)

        for value in values:
            walk(value)
        return " ".join(parts).casefold()
