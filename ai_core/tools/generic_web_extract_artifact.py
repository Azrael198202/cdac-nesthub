from __future__ import annotations

import json
from datetime import datetime
from typing import Any


class GenericWebExtractArtifactFactory:
    """Build a deterministic generic web extraction runtime tool artifact.

    This factory is intentionally domain-neutral. It does not know what the
    target page means. It only creates a small adapter that can fetch or reuse
    verified page evidence, strip HTML, select snippets using already-parsed
    runtime parameters, validate that the material covers those parameters, and
    return a JSON-serializable payload.
    """

    def build_artifact(
        self,
        *,
        capability: str,
        candidate: dict[str, Any],
        source_step: dict[str, Any] | None = None,
        evidence_text: str = "",
        tool_id: str | None = None,
    ) -> dict[str, Any]:
        safe_tool_id = self._safe_name(tool_id or f"generic_web_extract_{capability}_{candidate.get('candidate_index') or candidate.get('rank') or 'candidate'}")
        url = str(candidate.get("url") or candidate.get("official_documentation_url") or "").strip()
        name = str(candidate.get("name") or url or safe_tool_id)
        code = self._tool_source(url=url, name=name, evidence_text=evidence_text)
        return {
            "tool_id": safe_tool_id,
            "requires_review": False,
            "real_execution": True,
            "no_mock_data": True,
            "uses_network": True,
            "manifest": {
                "name": name,
                "capability": capability,
                "capabilities": [capability],
                "status": "enabled",
                "implementation": {"type": "python_function", "function": "run", "module_path": "tool.py"},
                "input_schema": {"type": "object", "additionalProperties": True},
                "output_schema": {"type": "object", "additionalProperties": True},
                "safety": {
                    "can_read_external_data": True,
                    "can_write_external_data": False,
                    "can_perform_irreversible_action": False,
                    "requires_human_confirmation": False,
                    "generated_code_must_be_reviewed": False,
                },
                "execution_claims": {
                    "real_execution": True,
                    "no_mock_data": True,
                    "uses_network": True,
                    "generated_by_runtime": True,
                    "live_verification_required": True,
                    "live_verification_passed": False,
                },
                "verification": {
                    "strategy": "deterministic_generic_web_extract",
                    "created_at": datetime.utcnow().isoformat(),
                    "source_candidate": self._compact_candidate(candidate),
                    "quality_gate": "dynamic_runtime_parameter_coverage",
                },
                "source_provenance": [{
                    "name": name,
                    "url": url,
                    "source": candidate.get("source"),
                    "tool_type": candidate.get("tool_type"),
                    "score": candidate.get("score"),
                }],
                "parameter_mapping": {
                    "strategy": "runtime_payload_keyword_projection",
                    "known_parameters_source": "payload.known or payload.parameters.known",
                },
                "source_step": source_step or {},
            },
            "files": {"tool.py": code},
            "verification": {
                "deterministic_artifact_factory": True,
                "source_candidate": self._compact_candidate(candidate),
                "quality_gate": "dynamic_runtime_parameter_coverage",
            },
        }

    def _compact_candidate(self, candidate: dict[str, Any]) -> dict[str, Any]:
        return {
            "name": candidate.get("name"),
            "url": candidate.get("url") or candidate.get("official_documentation_url"),
            "source": candidate.get("source"),
            "tool_type": candidate.get("tool_type"),
            "score": candidate.get("score"),
            "score_reasons": candidate.get("score_reasons"),
        }

    def _safe_name(self, value: str) -> str:
        safe = "".join(ch if ch.isalnum() else "_" for ch in str(value)).strip("_").lower()
        return safe[:96] or "generic_web_extract_tool"

    def _tool_source(self, *, url: str, name: str, evidence_text: str) -> str:
        return rf'''from __future__ import annotations

import html
import json
import re
import urllib.request
from datetime import datetime

CANDIDATE_URL = {json.dumps(url, ensure_ascii=False)}
CANDIDATE_NAME = {json.dumps(name, ensure_ascii=False)}
EMBEDDED_EVIDENCE_TEXT = {json.dumps((evidence_text or "")[:60000], ensure_ascii=False)}
NON_EVIDENCE_KEYS = {{
    "detail", "details", "detail_level", "semantic_modifiers", "format",
    "language", "locale", "unit", "units", "timezone", "time_zone",
    "date_expression", "relative_date", "text",
}}


def run(payload: dict) -> dict:
    if not isinstance(payload, dict):
        payload = {{}}
    known = _known(payload)
    fetch = _fetch_text(CANDIDATE_URL)
    source_text = fetch.get("text") or EMBEDDED_EVIDENCE_TEXT
    if not source_text:
        return _error("no_extractable_content", "No page content or verified evidence text was available.", fetch)
    plain_text = _to_text(source_text)
    snippets = _select_snippets(plain_text, known)
    if not snippets:
        snippets = _fallback_snippets(plain_text, known)
    quality = _quality(snippets, known)
    if not snippets:
        return _error("no_relevant_snippets", "Page content was available but no useful text could be extracted.", fetch)
    if not quality.get("passed"):
        return _error(
            "answer_material_quality_failed",
            "Extracted material did not cover runtime parameters or looked like sample/demo material.",
            {{"quality": quality, "retrieval": fetch}},
        )
    text = "\\n".join(snippets)
    return {{
        "status": "success",
        "data": {{
            "source_name": CANDIDATE_NAME,
            "source_url": CANDIDATE_URL,
            "retrieval": {{"used_live_fetch": bool(fetch.get("ok")), "http_status": fetch.get("status_code"), "error": fetch.get("error")}},
            "query_parameters": known,
            "extracted_text": text,
            "evidence_snippets": snippets,
            "answer_material_quality": quality,
            "answer_material": {{"summary_input": text, "source_url": CANDIDATE_URL, "source_name": CANDIDATE_NAME}},
        }},
        "source": CANDIDATE_URL or CANDIDATE_NAME or "generic_web_extract",
        "requires_human_confirmation": False,
    }}


def _known(payload: dict) -> dict:
    params = payload.get("parameters") if isinstance(payload.get("parameters"), dict) else {{}}
    known = params.get("known") if isinstance(params.get("known"), dict) else {{}}
    direct_known = payload.get("known") if isinstance(payload.get("known"), dict) else {{}}
    merged = {{}}
    for source in (known, direct_known, payload):
        if isinstance(source, dict):
            for key, value in source.items():
                if key in {{"parameters", "known", "optional", "context", "source_step"}}:
                    continue
                if _jsonish(value):
                    merged[str(key)] = value
    return merged


def _jsonish(value):
    return value is None or isinstance(value, (str, int, float, bool, list, dict))


def _fetch_text(url: str) -> dict:
    if not url:
        return {{"ok": False, "error": "missing_url", "text": ""}}
    try:
        req = urllib.request.Request(url, headers={{"User-Agent": "Mozilla/5.0 (compatible; RuntimeWebExtract/1.0)", "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}})
        with urllib.request.urlopen(req, timeout=15) as response:
            raw = response.read(900000)
            charset = response.headers.get_content_charset() or "utf-8"
            return {{"ok": True, "status_code": getattr(response, "status", None), "text": raw.decode(charset, errors="replace")}}
    except Exception as exc:
        return {{"ok": False, "error": str(exc), "text": ""}}


def _to_text(raw: str) -> str:
    text = str(raw or "")
    text = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", text)
    text = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", text)
    text = re.sub(r"(?is)<noscript[^>]*>.*?</noscript>", " ", text)
    text = re.sub(r"(?is)<br\\s*/?>", "\\n", text)
    text = re.sub(r"(?is)</(p|div|li|tr|td|th|h1|h2|h3|h4|section|article)>", "\\n", text)
    text = re.sub(r"(?is)<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"[ \\t\\r\\f\\v]+", " ", text)
    text = re.sub(r"\\n\\s+", "\\n", text)
    text = re.sub(r"\\n{{3,}}", "\\n\\n", text)
    return text.strip()


def _aliases(value) -> list[str]:
    out = []
    def add(v):
        if v is None:
            return
        if isinstance(v, dict):
            for vv in v.values(): add(vv)
            return
        if isinstance(v, (list, tuple, set)):
            for vv in v: add(vv)
            return
        s = str(v).strip()
        if not s:
            return
        out.append(s)
        m = re.match(r"^(\d{{4}})-(\d{{2}})-(\d{{2}})$", s)
        if m:
            y, mo, d = m.groups(); mi = int(mo); di = int(d)
            months = ["", "January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
            months_short = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
            weekdays = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
            mon = months[mi]; mon_s = months_short[mi]
            try:
                weekday = weekdays[datetime(int(y), mi, di).weekday()]
            except Exception:
                weekday = ""
            out.extend([
                f"{{y}}/{{mo}}/{{d}}", f"{{y}}.{{mo}}.{{d}}", f"{{y}}/{{mi}}/{{di}}",
                f"{{mi}}/{{di}}", f"{{mi}}-{{di}}", f"{{mo}}/{{d}}", f"{{mo}}-{{d}}",
                f"{{di}}. {{mi}}.", f"{{di}}.{{mi}}.", f"{{di}}/{{mi}}",
                f"{{mon}} {{di}}", f"{{mon}} {{di}}, {{y}}", f"{{di}} {{mon}}", f"{{di}} {{mon}} {{y}}",
                f"{{mon_s}} {{di}}", f"{{mon_s}} {{di}}, {{y}}", f"{{di}} {{mon_s}}", f"{{di}} {{mon_s}} {{y}}",
            ])
            if weekday:
                out.extend([weekday, weekday[:3], f"{{weekday}} {{di}}", f"{{weekday[:3]}} {{di}}", f"{{weekday}}, {{mon}} {{di}}", f"{{weekday[:3]}} {{mon_s}} {{di}}"])
    add(value)
    return list(dict.fromkeys(out))


def _required_terms(known: dict) -> dict:
    terms = {{}}
    for key, value in known.items():
        k = str(key).strip().lower()
        if not k or k in NON_EVIDENCE_KEYS:
            continue
        aliases = [a for a in _aliases(value) if len(str(a).strip()) >= 2]
        if aliases:
            terms[k] = aliases[:20]
    return terms


def _select_snippets(text: str, known: dict) -> list[str]:
    terms = _required_terms(known)
    aliases = [a.lower() for values in terms.values() for a in values]
    chunks = []
    lines = [line.strip() for line in text.splitlines() if len(line.strip()) >= 8]
    for i, line in enumerate(lines):
        line_l = line.lower()
        score = sum(1 for alias in aliases if alias and alias in line_l)
        if score:
            context = " ".join(lines[max(0, i-2): min(len(lines), i+3)])
            chunks.append((score, context[:1800]))
    chunks.sort(key=lambda item: (-item[0], len(item[1])))
    selected, seen = [], set()
    for _score, line in chunks:
        key = line[:180]
        if key in seen:
            continue
        seen.add(key)
        selected.append(line)
        if len(selected) >= 12:
            break
    if selected:
        return selected
    return _fallback_snippets(text, known)


def _fallback_snippets(text: str, known: dict) -> list[str]:
    # Fallback is deliberately conservative: return only if the compact page
    # itself contains all required runtime terms. This avoids treating API docs
    # examples as final answer material.
    compact = " ".join(part.strip() for part in text.splitlines() if part.strip())
    if not compact:
        return []
    terms = _required_terms(known)
    compact_l = compact.lower()
    if terms and not all(any(alias.lower() in compact_l for alias in aliases) for aliases in terms.values()):
        return []
    return [compact[:4000]]


def _quality(snippets: list[str], known: dict) -> dict:
    material = "\\n".join(snippets + [CANDIDATE_NAME, CANDIDATE_URL])
    material_l = material.lower()
    terms = _required_terms(known)
    matched, missing = {{}}, []
    for key, aliases in terms.items():
        hits = [a for a in aliases if a.lower() in material_l]
        if hits:
            matched[key] = hits[:5]
        else:
            missing.append(key)
    example_like = _looks_like_example(material, known)
    passed = bool(snippets) and not missing and not example_like
    return {{"passed": passed, "required_terms": terms, "matched_terms": matched, "missing_keys": missing, "example_like": example_like}}


def _looks_like_example(material: str, known: dict) -> bool:
    text = (material or "").lower()
    markers = ["example", "sample", "demo", "api_key", "your_api_key", "appid", "date_epoch", "time_epoch"]
    count = sum(1 for marker in markers if marker in text)
    if count >= 2:
        return True
    years = set(re.findall(r"\b(20\d{{2}}|19\d{{2}})\b", text))
    known_years = set()
    for aliases in _required_terms(known).values():
        for alias in aliases:
            known_years.update(re.findall(r"\b(20\d{{2}}|19\d{{2}})\b", alias))
    return bool(years and known_years and years.isdisjoint(known_years) and count >= 1)


def _error(code: str, message: str, details: dict | None = None) -> dict:
    return {{"status": "error", "error": {{"code": code, "message": message, "details": details or {{}}}}, "data": {{}}, "source": CANDIDATE_URL or CANDIDATE_NAME or "generic_web_extract", "requires_human_confirmation": False}}
'''
