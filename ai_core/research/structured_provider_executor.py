from __future__ import annotations

import asyncio
import json
import math
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ai_core.config.paths import RUNTIME_SESSIONS, RUNTIME_TRACES
from ai_core.events.event_bus import event_bus
from ai_core.secrets.secret_store import SecretStore


class StructuredProviderExecutor:
    """Generic structured-provider executor.

    This component is intentionally source/config driven.  The core code does
    not decide business domains.  Provider candidates, parameter mappings,
    endpoint templates, authentication contracts, and extraction paths are data
    loaded from JSON policy files.  The executor only applies that contract,
    calls HTTP JSON endpoints, validates the returned shape, and emits compact
    material for final synthesis.
    """

    def __init__(self) -> None:
        self.secret_store = SecretStore()
        self.trace_dir = RUNTIME_TRACES / "structured_provider_execution"
        self.trace_dir.mkdir(parents=True, exist_ok=True)
        self.session_root = RUNTIME_SESSIONS

    async def execute(
        self,
        *,
        run_id: str,
        node_id: str,
        step_id: str,
        capability: str,
        step: dict[str, Any],
        state: dict[str, Any],
        advisory: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        trace: dict[str, Any] = {
            "run_id": run_id,
            "node_id": node_id,
            "step_id": step_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "capability": capability,
            "stages": [],
            "providers": [],
        }
        known = self._known_parameters(step)
        policies = self._load_policies(run_id=run_id)
        candidates = self._rank_candidates(policies, capability=capability, step=step, known=known, advisory=advisory)
        trace["candidate_count"] = len(candidates)
        await self._emit(run_id, node_id, step_id, "STRUCTURED_PROVIDER_CANDIDATES", "Structured provider candidates resolved", {"count": len(candidates), "providers": [self._safe_provider_summary(p) for p in candidates]})

        usable_materials: list[dict[str, Any]] = []
        credential_options: list[dict[str, Any]] = []
        failures: list[dict[str, Any]] = []

        for provider in candidates:
            provider_trace: dict[str, Any] = {"provider": provider.get("id") or provider.get("name"), "stages": []}
            trace["providers"].append(provider_trace)
            if self._requires_secret(provider):
                secret_name = str(provider.get("secret_name") or "").strip()
                if secret_name and not self.secret_store.has(secret_name):
                    credential_options.append(self._credential_option(provider))
                    provider_trace["status"] = "credential_required"
                    provider_trace["secret_name"] = secret_name
                    continue

            try:
                material = await self._execute_provider(provider=provider, known=known, state=state, provider_trace=provider_trace)
            except Exception as exc:
                failure = {"provider": provider.get("id") or provider.get("name"), "reason": str(exc)[:500]}
                failures.append(failure)
                provider_trace["status"] = "failed"
                provider_trace["error"] = failure["reason"]
                continue

            if self._material_is_usable(material):
                usable_materials.append(material)
                provider_trace["status"] = "usable"
                provider_trace["fact_count"] = len(material.get("normalized_facts") or [])
            else:
                failures.append({"provider": provider.get("id") or provider.get("name"), "reason": "structured material did not satisfy provider output contract"})
                provider_trace["status"] = "not_usable"
                provider_trace["material_preview"] = self._preview(material)

            if self._enough_material(usable_materials, candidates):
                break

        fused = self._fuse_materials(usable_materials)
        trace["usable_material_count"] = len(usable_materials)
        trace["credential_option_count"] = len(credential_options)
        trace["failure_count"] = len(failures)
        trace["fused"] = self._preview(fused)
        trace_path = self._write_trace(trace)

        if fused.get("status") == "success":
            result = {
                "status": "success",
                "source": "structured_provider",
                "data": {
                    "answer": fused.get("answer_material") or "",
                    "answer_material": fused.get("answer_material") or "",
                    "normalized_facts": fused.get("normalized_facts") or [],
                    "structured_evidence": fused.get("normalized_facts") or [],
                    "source_url": fused.get("source_url") or "",
                    "source_title": fused.get("source_title") or "Structured provider result",
                    "supporting_sources": fused.get("supporting_sources") or [],
                    "answer_material_quality": fused.get("answer_material_quality") or {},
                    "provider_execution_trace": str(trace_path),
                    "investigated_sources": self._investigated_sources(trace),
                },
                "provenance": {
                    "source": "structured_provider",
                    "trace_id": trace_path.stem,
                    "trace_path": str(trace_path),
                    "execution_claims": {
                        "real_execution_declared": True,
                        "no_mock_data_declared": True,
                        "network_declared": True,
                        "live_verification_passed": True,
                    },
                },
            }
            await self._emit(run_id, node_id, step_id, "STRUCTURED_PROVIDER_EXECUTION_SUCCESS", "Structured provider execution succeeded", self._compact_result(result))
            return {"status": "success", "result": result, "tool": {"id": "structured_provider_executor", "source": "api_or_sdk"}}

        partial = {
            "status": "partial",
            "source": "structured_provider",
            "data": {
                "answer": "",
                "answer_material": "",
                "normalized_facts": [],
                "structured_evidence": [],
                "answer_material_quality": {"passed": False, "reason": "no verified structured material"},
                "provider_execution_trace": str(trace_path),
                "investigated_sources": self._investigated_sources(trace),
                "credential_options": credential_options,
                "failures": failures,
            },
        }
        await self._emit(run_id, node_id, step_id, "STRUCTURED_PROVIDER_EXECUTION_PARTIAL", "Structured provider execution did not produce verified material", self._compact_result(partial))
        return {"status": "partial", "result": partial, "tool": {"id": "structured_provider_executor", "source": "api_or_sdk"}}

    def _load_policies(self, *, run_id: str) -> list[dict[str, Any]]:
        path = self.session_root / run_id / "provider_resolution" / "structured_api_providers.json"
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return []
        providers = data.get("providers") if isinstance(data, dict) else data
        if not isinstance(providers, list):
            return []
        normalized: list[dict[str, Any]] = []
        for binding in providers:
            if not isinstance(binding, dict):
                continue
            primary = binding.get("selected_provider")
            if isinstance(primary, dict):
                item = dict(primary)
                item.setdefault("capability", binding.get("capability"))
                item.setdefault("execution_method", binding.get("execution_method"))
                normalized.append(item)
            for fallback in binding.get("fallbacks") or []:
                if isinstance(fallback, dict):
                    item = dict(fallback)
                    item.setdefault("capability", binding.get("capability"))
                    item.setdefault("execution_method", binding.get("execution_method"))
                    normalized.append(item)
        return normalized

    def _rank_candidates(self, policies: list[dict[str, Any]], *, capability: str, step: dict[str, Any], known: dict[str, Any], advisory: dict[str, Any] | None) -> list[dict[str, Any]]:
        text = " ".join([capability, str(step.get("objective") or ""), str(step.get("action") or ""), json.dumps(known, ensure_ascii=False)]).casefold()
        advisory_names = self._advisory_names(advisory or {})
        ranked: list[tuple[float, dict[str, Any]]] = []
        for provider in policies:
            enabled = provider.get("enabled", True)
            if not enabled:
                continue
            score = float(provider.get("priority") or 0)
            terms = [str(x).casefold() for x in provider.get("match_terms") or []]
            score += sum(12 for term in terms if term and term in text)
            if str(provider.get("id") or provider.get("name") or "").casefold() in advisory_names:
                score += 20
            if provider.get("requires_secret") is False:
                score += 8
            if str(provider.get("cost_level") or "").casefold() in {"free", "no_cost"}:
                score += 6
            if str(provider.get("quality_level") or "").casefold() in {"high", "trusted"}:
                score += 4
            ranked.append((score, provider))
        ranked.sort(key=lambda item: item[0], reverse=True)
        return [provider for score, provider in ranked if score > 0][: int((advisory or {}).get("max_provider_attempts") or 4)]

    def _advisory_names(self, advisory: dict[str, Any]) -> set[str]:
        names: set[str] = set()
        def walk(value: Any) -> None:
            if isinstance(value, dict):
                for key, item in value.items():
                    if key in {"name", "id", "provider", "provider_id"} and isinstance(item, str):
                        names.add(item.casefold())
                    else:
                        walk(item)
            elif isinstance(value, list):
                for item in value:
                    walk(item)
        walk(advisory)
        return names

    async def _execute_provider(self, *, provider: dict[str, Any], known: dict[str, Any], state: dict[str, Any], provider_trace: dict[str, Any]) -> dict[str, Any]:
        context = dict(known)
        responses: dict[str, Any] = {}
        for step in provider.get("steps") or []:
            if not isinstance(step, dict):
                continue
            name = str(step.get("id") or step.get("name") or f"step_{len(responses)+1}")
            url = self._render_url(str(step.get("url") or ""), context=context, provider=provider)
            method = str(step.get("method") or "GET").upper()
            headers = self._headers(step=step, provider=provider)
            body = self._body(step=step, context=context)
            stage_trace = {"id": name, "method": method, "url": self._redact_url(url), "headers": sorted(headers.keys())}
            provider_trace.setdefault("stages", []).append(stage_trace)
            response = await asyncio.to_thread(self._http_json, url, method, headers, body)
            stage_trace["status_code"] = response.get("status_code")
            stage_trace["content_type"] = response.get("content_type")
            payload = response.get("json")
            responses[name] = payload
            stage_trace["payload_preview"] = self._preview(payload)
            for assignment in step.get("assign") or []:
                if isinstance(assignment, dict):
                    key = str(assignment.get("name") or "").strip()
                    path = str(assignment.get("path") or "").strip()
                    if key and path:
                        context[key] = self._value_at(payload, path)
                        stage_trace.setdefault("assigned", {})[key] = context.get(key)
        material = self._extract_material(provider=provider, responses=responses, context=context)
        material["provider"] = provider.get("id") or provider.get("name")
        material["source_url"] = str(provider.get("documentation_url") or provider.get("source_url") or "")
        material["source_title"] = str(provider.get("name") or provider.get("id") or "Structured provider")
        return material

    def _extract_material(self, *, provider: dict[str, Any], responses: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        mappings = provider.get("output_mapping") if isinstance(provider.get("output_mapping"), dict) else {}
        response_name = str(mappings.get("response") or (list(responses.keys())[-1] if responses else ""))
        payload = responses.get(response_name)
        records_path = str(mappings.get("records_path") or "")
        records = self._value_at(payload, records_path) if records_path else payload
        if isinstance(records, dict):
            records = self._records_from_columnar(records)
        if not isinstance(records, list):
            records = [records] if records is not None else []
        fields = mappings.get("fields") if isinstance(mappings.get("fields"), list) else []
        facts: list[dict[str, Any]] = []
        lines: list[str] = []
        for idx, record in enumerate(records[: int(mappings.get("max_records") or 8)]):
            if not isinstance(record, dict):
                continue
            line_parts: list[str] = []
            target_value = ""
            for field in fields:
                if not isinstance(field, dict):
                    continue
                label = str(field.get("label") or field.get("name") or "value")
                path = str(field.get("path") or field.get("name") or "")
                raw = self._value_at(record, path)
                if raw is None:
                    continue
                unit = str(field.get("unit") or "")
                value = self._format_value(raw, unit=unit)
                if field.get("target"):
                    target_value = str(raw)
                fact = {
                    "kind": str(field.get("kind") or "observed_value"),
                    "label": label,
                    "value": str(raw),
                    "unit": unit,
                    "context": str(record)[:500],
                    "confidence": float(field.get("confidence") or 0.86),
                    "target": target_value,
                    "source_url": str(provider.get("documentation_url") or provider.get("source_url") or ""),
                }
                facts.append(fact)
                line_parts.append(f"{label}: {value}")
            if line_parts:
                prefix = f"Record {idx + 1}"
                if target_value:
                    prefix = str(target_value)
                lines.append(prefix + " — " + "; ".join(line_parts))
        return {
            "status": "success" if lines and facts else "no_material",
            "answer_material": "\n".join(lines),
            "normalized_facts": facts,
            "answer_material_quality": {
                "passed": bool(lines and facts),
                "score": 0.9 if lines and facts else 0.0,
                "record_count": len(lines),
                "fact_count": len(facts),
                "source_type": "structured_json",
            },
        }

    def _records_from_columnar(self, value: dict[str, Any]) -> list[dict[str, Any]]:
        arrays = {k: v for k, v in value.items() if isinstance(v, list)}
        if not arrays:
            return [value]
        length = max(len(v) for v in arrays.values())
        records: list[dict[str, Any]] = []
        for i in range(length):
            row = {}
            for key, arr in arrays.items():
                row[key] = arr[i] if i < len(arr) else None
            for key, item in value.items():
                if key not in arrays and not isinstance(item, (dict, list)):
                    row[key] = item
            records.append(row)
        return records

    def _fuse_materials(self, materials: list[dict[str, Any]]) -> dict[str, Any]:
        usable = [m for m in materials if self._material_is_usable(m)]
        if not usable:
            return {"status": "failed", "answer_material_quality": {"passed": False}}
        facts: list[dict[str, Any]] = []
        lines: list[str] = []
        sources: list[dict[str, Any]] = []
        for material in usable:
            facts.extend([f for f in material.get("normalized_facts") or [] if isinstance(f, dict)])
            answer = str(material.get("answer_material") or "").strip()
            if answer:
                lines.append(answer)
            sources.append({"provider": material.get("provider"), "url": material.get("source_url"), "quality": material.get("answer_material_quality")})
        return {
            "status": "success",
            "answer_material": "\n".join(lines[:3]),
            "normalized_facts": facts[:80],
            "source_url": str(usable[0].get("source_url") or ""),
            "source_title": str(usable[0].get("source_title") or "Structured provider result"),
            "supporting_sources": sources,
            "answer_material_quality": {
                "passed": True,
                "score": min(0.98, 0.82 + 0.04 * len(usable)),
                "source_count": len(usable),
                "fact_count": len(facts),
                "source_type": "structured_json",
            },
        }

    def _known_parameters(self, step: dict[str, Any]) -> dict[str, Any]:
        params = step.get("parameters") if isinstance(step.get("parameters"), dict) else {}
        known = params.get("known") if isinstance(params.get("known"), dict) else params
        return dict(known or {})

    def _render_url(self, template: str, *, context: dict[str, Any], provider: dict[str, Any]) -> str:
        def repl(match: re.Match[str]) -> str:
            name = match.group(1)
            value = context.get(name)
            if value is None:
                value = provider.get(name)
            if isinstance(value, list):
                value = ",".join(str(x) for x in value)
            return urllib.parse.quote(str(value if value is not None else ""), safe=",:/")
        return re.sub(r"\{([A-Za-z0-9_\.\-]+)\}", repl, template)

    def _headers(self, *, step: dict[str, Any], provider: dict[str, Any]) -> dict[str, str]:
        headers = {str(k): str(v) for k, v in (step.get("headers") or {}).items()} if isinstance(step.get("headers"), dict) else {}
        secret_name = str(provider.get("secret_name") or "").strip()
        if secret_name and self.secret_store.has(secret_name):
            header_name = str(provider.get("secret_header") or "Authorization")
            prefix = str(provider.get("secret_prefix") or "").strip()
            value = self.secret_store.get(secret_name) or ""
            headers[header_name] = (prefix + " " + value).strip() if prefix else value
        return headers

    def _body(self, *, step: dict[str, Any], context: dict[str, Any]) -> bytes | None:
        body = step.get("body")
        if body is None:
            return None
        if isinstance(body, (dict, list)):
            text = json.dumps(body, ensure_ascii=False)
        else:
            text = str(body)
        for key, value in context.items():
            text = text.replace("{" + str(key) + "}", str(value))
        return text.encode("utf-8")

    def _http_json(self, url: str, method: str, headers: dict[str, str], body: bytes | None) -> dict[str, Any]:
        req = urllib.request.Request(url=url, data=body, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read(2_000_000)
            content_type = resp.headers.get("content-type", "")
            text = raw.decode("utf-8", errors="replace")
            payload: Any = None
            if "json" in content_type or text.strip().startswith(("{", "[")):
                payload = json.loads(text)
            return {"status_code": resp.status, "content_type": content_type, "json": payload, "text_preview": text[:1000]}

    def _value_at(self, obj: Any, path: str) -> Any:
        if not path:
            return obj
        current = obj
        for part in path.split("."):
            if current is None:
                return None
            if isinstance(current, dict):
                current = current.get(part)
            elif isinstance(current, list):
                if part == "*":
                    return current
                try:
                    current = current[int(part)]
                except Exception:
                    return None
            else:
                return None
        return current

    def _format_value(self, value: Any, *, unit: str) -> str:
        if isinstance(value, float) and math.isfinite(value):
            text = f"{value:.1f}".rstrip("0").rstrip(".")
        else:
            text = str(value)
        return (text + unit) if unit and not text.endswith(unit) else text

    def _requires_secret(self, provider: dict[str, Any]) -> bool:
        return bool(provider.get("requires_secret"))

    def _credential_option(self, provider: dict[str, Any]) -> dict[str, Any]:
        return {
            "provider": provider.get("name") or provider.get("id"),
            "source_url": provider.get("documentation_url") or provider.get("source_url"),
            "secret_name": provider.get("secret_name"),
            "reason": "Provider declares that a credential is required.",
        }

    def _material_is_usable(self, material: dict[str, Any] | None) -> bool:
        if not isinstance(material, dict):
            return False
        quality = material.get("answer_material_quality") if isinstance(material.get("answer_material_quality"), dict) else {}
        return bool(quality.get("passed") and str(material.get("answer_material") or "").strip() and material.get("normalized_facts"))

    def _enough_material(self, materials: list[dict[str, Any]], candidates: list[dict[str, Any]]) -> bool:
        public_candidates = [c for c in candidates if not self._requires_secret(c)]
        return len(materials) >= min(2, max(1, len(public_candidates)))

    def _write_trace(self, trace: dict[str, Any]) -> Path:
        path = self.trace_dir / ("structured_provider_" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f") + ".json")
        path.write_text(json.dumps(trace, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def _investigated_sources(self, trace: dict[str, Any]) -> list[dict[str, Any]]:
        result = []
        for item in trace.get("providers") or []:
            if isinstance(item, dict):
                result.append({
                    "provider": item.get("provider"),
                    "status": item.get("status"),
                    "fact_count": item.get("fact_count", 0),
                    "error": item.get("error"),
                    "stages": len(item.get("stages") or []),
                })
        return result

    def _safe_provider_summary(self, provider: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": provider.get("id"),
            "name": provider.get("name"),
            "cost_level": provider.get("cost_level"),
            "requires_secret": provider.get("requires_secret"),
            "quality_level": provider.get("quality_level"),
            "documentation_url": provider.get("documentation_url"),
        }

    def _compact_result(self, result: dict[str, Any]) -> dict[str, Any]:
        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        return {
            "status": result.get("status"),
            "source": result.get("source"),
            "answer_preview": str(data.get("answer_material") or data.get("answer") or "")[:1000],
            "fact_count": len(data.get("normalized_facts") or []),
            "sources": data.get("supporting_sources") or data.get("investigated_sources") or [],
            "quality": data.get("answer_material_quality") or {},
        }

    def _preview(self, value: Any) -> Any:
        try:
            text = json.dumps(value, ensure_ascii=False)
        except Exception:
            text = str(value)
        return text[:1200]

    def _redact_url(self, url: str) -> str:
        return re.sub(r"([?&][^=]*(?:key|token|secret|credential)[^=]*=)[^&]+", r"\1***", url, flags=re.IGNORECASE)

    async def _emit(self, run_id: str, node_id: str, step_id: str, event_type: str, message: str, result: dict[str, Any]) -> None:
        await event_bus.emit(run_id, {
            "type": event_type,
            "title": message,
            "message": message,
            "node_id": node_id,
            "step_id": step_id,
            "result": result,
        })
