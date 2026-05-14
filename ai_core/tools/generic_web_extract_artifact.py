from __future__ import annotations

import json
from datetime import datetime
from typing import Any


class GenericWebExtractArtifactFactory:
    """Build a deterministic generic web extraction runtime tool artifact.

    This factory is intentionally domain-neutral. It does not know what the
    target page means. It only creates a small adapter that can fetch or reuse
    verified page evidence, strip HTML, select snippets using already-parsed
    runtime parameters, and return a JSON-serializable payload.
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
                "implementation": {
                    "type": "python_function",
                    "function": "run",
                    "module_path": "tool.py",
                },
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
        # json.dumps safely quotes arbitrary page text into the generated source.
        return f'''from __future__ import annotations

import html
import json
import re
import urllib.request
import urllib.error

CANDIDATE_URL = {json.dumps(url, ensure_ascii=False)}
CANDIDATE_NAME = {json.dumps(name, ensure_ascii=False)}
EMBEDDED_EVIDENCE_TEXT = {json.dumps((evidence_text or "")[:60000], ensure_ascii=False)}


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
        snippets = _fallback_snippets(plain_text)
    if not snippets:
        return _error("no_relevant_snippets", "Page content was available but no useful text could be extracted.", fetch)
    return {{
        "status": "success",
        "data": {{
            "source_name": CANDIDATE_NAME,
            "source_url": CANDIDATE_URL,
            "retrieval": {{
                "used_live_fetch": bool(fetch.get("ok")),
                "http_status": fetch.get("status_code"),
                "error": fetch.get("error"),
            }},
            "query_parameters": known,
            "extracted_text": "\\n".join(snippets),
            "evidence_snippets": snippets,
            "answer_material": {{
                "summary_input": "\\n".join(snippets),
                "source_url": CANDIDATE_URL,
                "source_name": CANDIDATE_NAME,
            }},
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
        req = urllib.request.Request(
            url,
            headers={{
                "User-Agent": "Mozilla/5.0 (compatible; RuntimeWebExtract/1.0)",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            }},
        )
        with urllib.request.urlopen(req, timeout=15) as response:
            raw = response.read(900000)
            charset = response.headers.get_content_charset() or "utf-8"
            text = raw.decode(charset, errors="replace")
            return {{"ok": True, "status_code": getattr(response, "status", None), "text": text}}
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


def _tokens(known: dict) -> list[str]:
    out = []
    def add(value):
        if value is None:
            return
        if isinstance(value, (list, tuple, set)):
            for item in value:
                add(item)
            return
        if isinstance(value, dict):
            for item in value.values():
                add(item)
            return
        s = str(value).strip()
        if not s:
            return
        out.append(s)
        if re.match(r"^\d{{4}}-\d{{2}}-\d{{2}}$", s):
            y, m, d = s.split("-")
            out.extend([f"{{y}}/{{m}}/{{d}}", f"{{int(m)}}/{{int(d)}}", f"{{int(m)}}-{{int(d)}}", f"{{int(d)}}"])
    for value in known.values():
        add(value)
    return [x.lower() for x in out if len(x.strip()) >= 2]


def _select_snippets(text: str, known: dict) -> list[str]:
    tokens = _tokens(known)
    chunks = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if len(line) < 8:
            continue
        line_l = line.lower()
        score = 0
        for token in tokens:
            if token and token in line_l:
                score += 1
        if score:
            chunks.append((score, line))
    chunks.sort(key=lambda item: (-item[0], len(item[1])))
    selected = []
    seen = set()
    for _score, line in chunks:
        key = line[:180]
        if key in seen:
            continue
        seen.add(key)
        selected.append(line[:1200])
        if len(selected) >= 12:
            break
    return selected


def _fallback_snippets(text: str) -> list[str]:
    compact = " ".join(part.strip() for part in text.splitlines() if part.strip())
    if not compact:
        return []
    return [compact[:4000]]


def _error(code: str, message: str, details: dict | None = None) -> dict:
    return {{
        "status": "error",
        "error": {{"code": code, "message": message, "details": details or {{}}}},
        "data": {{}},
        "source": CANDIDATE_URL or CANDIDATE_NAME or "generic_web_extract",
        "requires_human_confirmation": False,
    }}
'''
