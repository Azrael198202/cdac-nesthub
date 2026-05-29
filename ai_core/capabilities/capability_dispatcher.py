from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Awaitable, Callable

from ai_core.config.paths import CONFIGS_DIR, RUNTIME_GENERATED

CapabilityHandler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


class CapabilityDispatcher:
    """Dispatch direct user requests to runtime capabilities.

    The dispatcher is intentionally policy-driven.  Core code only implements a
    generic rule scorer and a handler registry.  Capability trigger terms,
    modality mappings, and future capability placeholders live in configuration
    so source code does not become a collection of task-specific branches.
    """

    def __init__(self, handlers: dict[str, CapabilityHandler] | None = None, policy_paths: list[str | Path] | None = None) -> None:
        self.handlers = dict(handlers or {})
        self.policy_paths = [Path(p) for p in (policy_paths or [])] or [
            CONFIGS_DIR / "direct_capability_routes.seed.json",
            RUNTIME_GENERATED / "system_topology" / "direct_capability_routes.json",
            RUNTIME_GENERATED / "contracts" / "direct_capability_routes.json",
        ]

    async def dispatch(self, *, text: str, context: dict[str, Any] | None = None) -> dict[str, Any] | None:
        decision = self.match(text=text, context=context or {})
        if not decision:
            return None
        capability_type = str(decision.get("capability_type") or "").strip()
        if not capability_type:
            return None
        handler = self.handlers.get(capability_type)
        if handler is None:
            return {
                "action": "direct_capability_dispatch",
                "origin": "ai_core",
                "status": "requires_setup",
                "final_answer": "The requested output modality is recognized, but no runtime provider is registered for it yet.",
                "capability_profile": decision,
                "fallback_isolated": True,
            }
        payload = await handler({"text": text, "context": context or {}, "decision": decision})
        if not isinstance(payload, dict):
            payload = {"status": "failed", "final_answer": str(payload or "")}
        payload.setdefault("action", "direct_capability_dispatch")
        payload.setdefault("origin", "ai_core")
        payload.setdefault("capability_profile", decision)
        payload["fallback_isolated"] = True
        return payload

    def match(self, *, text: str, context: dict[str, Any] | None = None) -> dict[str, Any] | None:
        source = self._contract_text([text, context or {}])
        if not source.strip():
            return None
        best: dict[str, Any] | None = None
        best_score = 0.0
        for rule in self._rules():
            if not isinstance(rule, dict) or not bool(rule.get("enabled", True)):
                continue
            if self._excluded(source, rule):
                continue
            score = self._score(source, rule)
            threshold = float(rule.get("threshold") or 1.0)
            if score >= threshold and score > best_score:
                best_score = score
                best = rule
        if not best:
            return None
        return {
            "capability_type": str(best.get("capability_type") or best.get("capability") or "").strip(),
            "input_modality": best.get("input_modality") or "text",
            "output_modality": best.get("output_modality") or "artifact",
            "confidence": float(best.get("confidence") or best_score),
            "rule_id": best.get("rule_id"),
            "execution_mode": best.get("execution_mode") or "direct_runtime_capability",
            "fallback_policy": best.get("fallback_policy") if isinstance(best.get("fallback_policy"), dict) else {"allow_chat_fallback": False},
            "metadata": best.get("metadata") if isinstance(best.get("metadata"), dict) else {},
        }

    def _rules(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for path in self.policy_paths:
            if not path.exists():
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8") or "{}")
            except Exception:
                continue
            if isinstance(data, dict) and isinstance(data.get("rules"), list):
                out.extend(item for item in data["rules"] if isinstance(item, dict))
        return out

    def _score(self, text: str, rule: dict[str, Any]) -> float:
        token_sets = rule.get("match_any_token_sets")
        if not isinstance(token_sets, list):
            return 0.0
        best = 0.0
        for raw_set in token_sets:
            tokens = [str(x).casefold().strip() for x in raw_set if str(x).strip()] if isinstance(raw_set, list) else []
            if not tokens:
                continue
            matched = sum(1 for token in tokens if self._token_matches(text, token))
            if matched == len(tokens):
                best = max(best, matched / max(len(tokens), 1))
        return best

    def _excluded(self, text: str, rule: dict[str, Any]) -> bool:
        token_sets = rule.get("exclude_if_any_token_sets")
        if not isinstance(token_sets, list):
            return False
        for raw_set in token_sets:
            tokens = [str(x).casefold().strip() for x in raw_set if str(x).strip()] if isinstance(raw_set, list) else []
            if tokens and all(self._token_matches(text, token) for token in tokens):
                return True
        return False

    def _token_matches(self, text: str, token: str) -> bool:
        if not token:
            return False
        if re.fullmatch(r"[a-z0-9_ -]+", token):
            pattern = r"(?<![a-z0-9_])" + re.escape(token).replace(r"\ ", r"\s+") + r"(?![a-z0-9_])"
            return re.search(pattern, text, flags=re.IGNORECASE) is not None
        return token.casefold() in text

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
