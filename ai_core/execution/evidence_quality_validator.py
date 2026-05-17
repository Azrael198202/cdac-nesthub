from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from typing import Any

from ai_core.utils.safe_json import make_json_safe


@dataclass
class EvidenceQualityResult:
    passed: bool
    score: float
    reason: str
    required_terms: dict[str, list[str]]
    matched_terms: dict[str, list[str]]
    missing_keys: list[str]
    example_like: bool


class EvidenceQualityValidator:
    """Validate whether extracted answer material is tied to runtime input.

    The validator is generic. It does not know any business domain. It only
    checks whether the result material covers the critical values that upstream
    nodes already parsed into payload.parameters.known / payload.known.
    """

    NON_EVIDENCE_KEYS = {
        "detail", "details", "detail_level", "semantic_modifiers", "format",
        "language", "locale", "unit", "units", "timezone", "time_zone",
    }

    def validate_result(self, result: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        material = self._material_text(result)
        known = self._known(payload)
        terms = self.required_terms(known)
        matched: dict[str, list[str]] = {}
        missing: list[str] = []
        material_l = material.lower()
        for key, aliases in terms.items():
            hits = [alias for alias in aliases if alias and alias.lower() in material_l]
            if hits:
                matched[key] = hits[:5]
            else:
                missing.append(key)
        example_like = self._looks_like_example_material(material, known)
        if not terms:
            passed = bool(material.strip()) and not example_like
        else:
            passed = not missing and not example_like
        score = 1.0 if passed else max(0.0, (len(terms) - len(missing)) / max(len(terms), 1))
        reason = "evidence_covers_runtime_parameters" if passed else "evidence_missing_runtime_parameters_or_example_like"
        return make_json_safe(asdict(EvidenceQualityResult(
            passed=passed,
            score=round(score, 3),
            reason=reason,
            required_terms=terms,
            matched_terms=matched,
            missing_keys=missing,
            example_like=example_like,
        )))

    def required_terms(self, known: dict[str, Any]) -> dict[str, list[str]]:
        output: dict[str, list[str]] = {}
        for key, value in known.items():
            k = str(key).strip().lower()
            if not k or k in self.NON_EVIDENCE_KEYS:
                continue
            aliases = self._aliases(value)
            aliases = [item for item in aliases if len(item.strip()) >= 2]
            if aliases:
                output[k] = sorted(set(aliases), key=lambda x: (len(x), x.lower()), reverse=True)[:20]
        return output

    def _known(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            return {}
        params = payload.get("parameters") if isinstance(payload.get("parameters"), dict) else {}
        known = params.get("known") if isinstance(params.get("known"), dict) else {}
        direct_known = payload.get("known") if isinstance(payload.get("known"), dict) else {}
        merged: dict[str, Any] = {}
        for source in (known, direct_known, payload):
            if not isinstance(source, dict):
                continue
            for key, value in source.items():
                if key in {"parameters", "known", "optional", "context", "source_step"}:
                    continue
                if isinstance(value, (str, int, float, bool, list, dict)) or value is None:
                    merged[str(key)] = value
        return merged

    def _aliases(self, value: Any) -> list[str]:
        out: list[str] = []
        def add(v: Any) -> None:
            if v is None:
                return
            if isinstance(v, dict):
                for vv in v.values():
                    add(vv)
                return
            if isinstance(v, (list, tuple, set)):
                for vv in v:
                    add(vv)
                return
            s = str(v).strip()
            if not s:
                return
            out.append(s)
            m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", s)
            if m:
                y, mo, d = m.groups()
                mi = int(mo)
                di = int(d)
                out.extend([
                    f"{y}/{mo}/{d}", f"{y}.{mo}.{d}", f"{y}/{mi}/{di}",
                    f"{mi}/{di}", f"{mi}-{di}", f"{di}. {mi}.",
                    f"{mo}/{d}", f"{mo}-{d}", f"{di}",
                ])
        add(value)
        return out

    def _material_text(self, result: dict[str, Any]) -> str:
        if not isinstance(result, dict):
            return str(result or "")
        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        parts: list[str] = []
        for key in ("extracted_text", "source", "source_name", "source_url"):
            value = data.get(key) if key in data else result.get(key)
            if isinstance(value, str) and value.strip():
                parts.append(value)
        snippets = data.get("evidence_snippets")
        if isinstance(snippets, list):
            parts.extend(str(x) for x in snippets if isinstance(x, (str, int, float)))
        answer_material = data.get("answer_material") if isinstance(data.get("answer_material"), dict) else {}
        for value in answer_material.values():
            if isinstance(value, str):
                parts.append(value)
        return "\n".join(parts)

    def _looks_like_example_material(self, material: str, known: dict[str, Any]) -> bool:
        text = (material or "").lower()
        if not text.strip():
            return True
        example_markers = ["example", "sample", "demo", "api_key", "your_api_key", "appid", "date_epoch", "time_epoch"]
        marker_count = sum(1 for marker in example_markers if marker in text)
        if marker_count >= 2:
            return True
        years = set(re.findall(r"\b(20\d{2}|19\d{2})\b", text))
        known_years = set()
        for alias_list in self.required_terms(known).values():
            for alias in alias_list:
                known_years.update(re.findall(r"\b(20\d{2}|19\d{2})\b", alias))
        if years and known_years and years.isdisjoint(known_years) and marker_count >= 1:
            return True
        return False
