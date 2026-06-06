from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PlannedQuery:
    query: str
    purpose: str
    priority: int


class SearchQueryPlanner:
    """Create compact, purpose-scoped search queries from runtime context.

    This module is intentionally domain-neutral. It does not encode concrete
    capability behavior. It only compresses noisy user requests into multiple
    evidence-oriented query intents so downstream retrieval does not search the
    entire original prompt.
    """

    MAX_QUERY_CHARS = 160

    def plan(self, *, user_input: str, capability: str = "", objective: str = "", known: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        known = known if isinstance(known, dict) else {}
        identity = self._identity_text(capability=capability, objective=objective, user_input=user_input, known=known)
        if not identity:
            identity = self._compact_terms(user_input or objective or capability)
        bases = [identity]
        compact_objective = self._compact_terms(objective)
        if compact_objective and compact_objective not in bases:
            bases.append(compact_objective)
        purposes = [
            ("official_documentation", "official documentation reference", 1),
            ("implementation_example", "implementation example usage", 2),
            ("safety_validation", "security configuration validation", 3),
        ]
        out: list[PlannedQuery] = []
        seen: set[str] = set()
        for base in bases[:2]:
            for purpose, suffix, priority in purposes:
                query = self._clip(f"{base} {suffix}")
                if query and query not in seen:
                    seen.add(query)
                    out.append(PlannedQuery(query=query, purpose=purpose, priority=priority))
        if not out:
            out.append(PlannedQuery(query=self._clip(user_input or "runtime capability documentation"), purpose="general", priority=9))
        return [q.__dict__ for q in out[:6]]

    def _identity_text(self, *, capability: str, objective: str, user_input: str, known: dict[str, Any]) -> str:
        candidates: list[str] = []
        for value in [capability, objective, known.get("capability"), known.get("capability_id"), known.get("tool_id")]:
            if isinstance(value, str) and value.strip():
                candidates.append(value.strip())
        text = str(user_input or "")
        match = re.search(r"Acquire\s+runtime\s+capability\s*:\s*\n?\s*([^\n.]+)", text, re.I)
        if match:
            candidates.insert(0, match.group(1).strip())
        for candidate in candidates:
            compact = self._compact_terms(candidate)
            if compact:
                return compact
        return ""

    def _compact_terms(self, text: str) -> str:
        text = str(text or "")
        text = re.sub(r"https?://\S+", " ", text)
        text = re.sub(r"[`*_#>\[\]{}()]+", " ", text)
        text = re.sub(r"\b(?:constraints?|requirements?|complete|completed|runtime|autonomous|mode|generate|register|verification|validation|sandbox|schema|policy)\b", " ", text, flags=re.I)
        tokens = re.findall(r"[A-Za-z0-9][A-Za-z0-9_+./:-]{1,40}|[\u3040-\u30ff\u3400-\u9fff]{2,}", text)
        kept: list[str] = []
        for token in tokens:
            low = token.casefold()
            if low in {"the", "and", "or", "with", "from", "this", "that", "use", "using", "basic", "if", "can", "will", "must"}:
                continue
            if token not in kept:
                kept.append(token)
            if len(kept) >= 8:
                break
        return " ".join(kept).strip()

    def _clip(self, query: str) -> str:
        query = " ".join(str(query or "").split())
        return query[: self.MAX_QUERY_CHARS].strip()
