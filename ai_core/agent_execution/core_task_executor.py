from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote_plus, unquote, urlparse
from uuid import uuid4

import httpx
from bs4 import BeautifulSoup

from ai_core.agent_execution.runtime_workflow_executor import RuntimeWorkflowExecutor
from ai_core.agent_execution.orchestration_bridge import AICoreOrchestrationBridge, build_core_execution_request


class AICoreAgentTaskExecutor:
    """Main-brain executor for generated agent tasks.

    The auxiliary layer owns community/task state. This executor owns generic
    execution decisions, external material collection, generated output
    normalization, and final synthesis. It reads runtime/configured matching
    profiles instead of embedding domain-specific words in source code.
    """

    ORIGIN = "ai_core"

    def __init__(self, runtime_root: str | Path = "runtime", tool_config_path: str | Path = "configs/agent_runtime_tools.json") -> None:
        self.runtime_root = Path(runtime_root)
        self.tool_config_path = Path(tool_config_path)
        self.tool_output_dir = self.runtime_root / "generated" / "tool_outputs"
        self.tool_output_dir.mkdir(parents=True, exist_ok=True)
        self.workflow_executor = RuntimeWorkflowExecutor()
        self.orchestration_bridge = AICoreOrchestrationBridge()


    async def execute_task_async(self, *, task: Any, agent: Any, inputs: dict[str, Any] | None = None) -> dict[str, Any]:
        """Run generated-agent work through the main-brain execution kernel.

        The auxiliary layer invokes this method, but execution stays inside
        ai_core.  This path uses the same neutral workflow DAG and configured
        tool-dispatch contracts as the synchronous path, then persists an
        ai_core-origin tool output.  It intentionally does not let the
        auxiliary layer perform retrieval, shell work, code execution, or
        synthesis.
        """
        return self.execute_task(task=task, agent=agent, inputs=inputs or {})

    def execute_task(self, *, task: Any, agent: Any, inputs: dict[str, Any] | None = None) -> dict[str, Any]:
        inputs = inputs or {}
        mode = str(getattr(task, "parameters", {}).get("execution_mode") or "collect")
        if getattr(task, "input_refs", []) or mode == "compose":
            output = self.synthesize_task(task=task, agent=agent, inputs=inputs)
        else:
            output = self.collect_task_material(task=task, agent=agent)
        output["artifact_path"] = str(self._write_output(output))
        return output

    def collect_task_material(self, *, task: Any, agent: Any) -> dict[str, Any]:
        operation = self._select_operation(task=task, agent=agent)
        query = self._build_agent_query(task=task, agent=agent)
        plan = self.workflow_executor.build_collect_plan(
            operation=operation,
            query=query,
            task_id=str(getattr(task, "task_id", "")),
            agent_id=str(getattr(agent, "agent_id", "")),
        )
        profile = self._select_profile(task=task, agent=agent)
        collectors = {"public_discovery": self._public_discovery}
        if profile.get("requests"):
            collectors[operation] = lambda runtime_query: self._configured_collection(profile=profile, query=runtime_query)
        run = self.workflow_executor.run_collect_plan(
            plan=plan,
            operation=operation,
            query=query,
            collectors=collectors,
            context_supplier=lambda: self._runtime_context_snapshot(task=task, agent=agent),
        )
        material = run.get("final_material", {}) if isinstance(run.get("final_material"), dict) else {}
        if operation == "runtime_context_snapshot":
            evidence = run.get("workflow_outputs", {}).get("collected_material", material)
            status = "completed"
            result_text = evidence.get("result_text") if isinstance(evidence, dict) else ""
            tool_type = "runtime_context_snapshot"
        else:
            evidence = run.get("workflow_outputs", {}).get("collected_material", material)
            status = evidence.get("status", "completed") if isinstance(evidence, dict) else "completed"
            result_text = self._summarize_evidence(evidence)
            tool_type = "configured_runtime_tool" if profile.get("requests") else "generic_public_discovery"
        return {
            "tool_call_id": f"tool_call_{uuid4().hex[:8]}",
            "origin": self.ORIGIN,
            "status": status,
            "tool_type": tool_type,
            "task_id": getattr(task, "task_id", ""),
            "agent_id": getattr(agent, "agent_id", ""),
            "query": query,
            "result_text": result_text,
            "evidence": evidence,
            "workflow_plan": run.get("workflow_plan"),
            "workflow_events": run.get("execution_events", []),
            "evidence_validation": run.get("workflow_outputs", {}).get("validated_material", {}),
            "created_at": self._now(),
        }

    def synthesize_task(self, *, task: Any, agent: Any, inputs: dict[str, Any]) -> dict[str, Any]:
        fragments = self._collect_fragments(inputs)
        plan = self.workflow_executor.build_synthesis_plan(
            input_refs=list(getattr(task, "input_refs", []) or []),
            task_id=str(getattr(task, "task_id", "")),
            agent_id=str(getattr(agent, "agent_id", "")),
        )
        run = self.workflow_executor.run_synthesis_plan(
            plan=plan,
            fragments=fragments,
            synthesizer=lambda items: self._stable_join(items) if items else self._clean(str(getattr(task, "objective", ""))),
        )
        final_text = run.get("result_text") or self._clean(str(getattr(task, "objective", "")))
        return {
            "tool_call_id": f"tool_call_{uuid4().hex[:8]}",
            "origin": self.ORIGIN,
            "status": "completed",
            "tool_type": "stable_synthesis",
            "task_id": getattr(task, "task_id", ""),
            "agent_id": getattr(agent, "agent_id", ""),
            "result_text": final_text,
            "input_count": len(inputs),
            "workflow_plan": run.get("workflow_plan"),
            "workflow_events": run.get("execution_events", []),
            "synthesis": {"source": "ai_core_workflow_synthesis", "fragment_count": len(fragments)},
            "created_at": self._now(),
        }

    def _select_operation(self, *, task: Any, agent: Any) -> str:
        profile = self._select_profile(task=task, agent=agent)
        return str(profile.get("operation") or "public_discovery")

    def _runtime_context_snapshot(self, *, task: Any, agent: Any) -> dict[str, Any]:
        now = datetime.now().astimezone()
        label = str(getattr(agent, "role_label", "runtime participant"))
        return {
            "status": "success",
            "iso_time": now.isoformat(),
            "timezone": now.tzname(),
            "result_text": f"{label}: {now.isoformat()}",
            "objective": getattr(task, "objective", ""),
        }

    def _build_agent_query(self, *, task: Any, agent: Any) -> str:
        metadata = getattr(agent, "metadata", {}) or {}
        instruction = str(metadata.get("execution_instruction") or metadata.get("user_instruction") or "")
        base = instruction or " ".join([
            str(getattr(agent, "role_label", "")),
            " ".join(str(v) for v in getattr(agent, "capability_labels", [])),
            str(getattr(task, "objective", "")),
        ])
        return self._compact_query(self._clean_instruction_text(base))

    def _clean_instruction_text(self, text: str) -> str:
        cleaned = str(text or "")
        config = self._load_config()
        for phrase in (config.get("text_cleanup") or {}).get("drop_phrases", []):
            cleaned = re.sub(re.escape(str(phrase)), " ", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\b[A-Za-z0-9_]+\.(?:json|py|html|md)\b", " ", cleaned)
        return self._clean(cleaned)

    def _select_profile(self, *, task: Any, agent: Any) -> dict[str, Any]:
        config = self._load_config()
        searchable = " ".join([
            str(getattr(agent, "role_label", "")),
            " ".join(str(v) for v in getattr(agent, "capability_labels", [])),
            str((getattr(agent, "metadata", {}) or {}).get("user_instruction", "")),
            str((getattr(agent, "metadata", {}) or {}).get("execution_instruction", "")),
            str(getattr(task, "objective", "")),
        ]).casefold()
        for profile in config.get("profiles", []):
            terms = [str(term).casefold() for term in profile.get("match_terms", [])]
            if terms and any(term in searchable for term in terms):
                return profile
        return {}

    def _configured_collection(self, *, profile: dict[str, Any], query: str) -> dict[str, Any]:
        requests = profile.get("requests") if isinstance(profile.get("requests"), list) else []
        if not requests:
            return self._public_discovery(query)
        variables = self._extract_profile_variables(profile=profile, query=query)
        attempts: list[dict[str, Any]] = []
        for request in requests:
            if not isinstance(request, dict):
                continue
            url = self._render_template(str(request.get("url_template") or ""), variables)
            if not url:
                continue
            try:
                with httpx.Client(timeout=float(request.get("timeout_seconds") or 12.0), follow_redirects=True, headers={"User-Agent": "AI-Core-Runtime/1.0"}) as client:
                    response = client.get(url)
                    response.raise_for_status()
                content_type = response.headers.get("content-type", "")
                if "json" in content_type.casefold() or str(request.get("response_type") or "").casefold() == "json":
                    payload: Any = response.json()
                else:
                    payload = {"text": self._clean(response.text)[:3000]}
                result_text = self._summarize_configured_payload(profile=profile, payload=payload, variables=variables)
                material = {
                    "status": "success",
                    "query": query,
                    "url": url,
                    "variables": variables,
                    "result_text": result_text,
                    "response_status": response.status_code,
                    "response_type": request.get("response_type") or content_type,
                    "fetched_at": self._now(),
                }
                return material
            except Exception as exc:
                attempts.append({"url": url, "status": "error", "error": str(exc)})
        fallback = self._public_discovery(query)
        fallback["configured_attempts"] = attempts
        return fallback

    def _extract_profile_variables(self, *, profile: dict[str, Any], query: str) -> dict[str, str]:
        variables: dict[str, str] = {"query": query}
        for spec in profile.get("parameters", []) if isinstance(profile.get("parameters"), list) else []:
            if not isinstance(spec, dict):
                continue
            name = str(spec.get("name") or "").strip()
            if not name:
                continue
            value = ""
            for pattern in spec.get("patterns", []) if isinstance(spec.get("patterns"), list) else []:
                try:
                    match = re.search(str(pattern), query, flags=re.IGNORECASE)
                except re.error:
                    continue
                if match:
                    value = self._clean(match.group(1) if match.groups() else match.group(0))
                    break
            if not value:
                value = str(spec.get("default") or "")
            variables[name] = value
        return variables

    def _render_template(self, template: str, variables: dict[str, str]) -> str:
        rendered = template
        for key, value in variables.items():
            rendered = rendered.replace("{" + key + "}", quote_plus(str(value)))
        return rendered

    def _summarize_configured_payload(self, *, profile: dict[str, Any], payload: Any, variables: dict[str, str]) -> str:
        fields = profile.get("summary_fields") if isinstance(profile.get("summary_fields"), list) else []
        lines: list[str] = []
        heading = profile.get("summary_heading")
        if heading:
            lines.append(self._render_plain_template(str(heading), variables))
        for field in fields:
            if not isinstance(field, dict):
                continue
            label = str(field.get("label") or field.get("path") or "value")
            path = str(field.get("path") or "")
            suffix = str(field.get("suffix") or "")
            value = self._json_path(payload, path)
            if value not in (None, "", []):
                lines.append(f"{label}: {self._clean(str(value))}{suffix}")
        if lines:
            return "\n".join(lines)
        if isinstance(payload, dict):
            return self._clean(json.dumps(payload, ensure_ascii=False))[:1200]
        return self._clean(str(payload))[:1200]

    def _render_plain_template(self, template: str, variables: dict[str, str]) -> str:
        rendered = template
        for key, value in variables.items():
            rendered = rendered.replace("{" + key + "}", str(value))
        return rendered

    def _json_path(self, payload: Any, path: str) -> Any:
        current = payload
        if not path:
            return current
        for part in path.split("."):
            if isinstance(current, list):
                try:
                    current = current[int(part)]
                except Exception:
                    return None
            elif isinstance(current, dict):
                current = current.get(part)
            else:
                return None
        return current

    def _public_discovery(self, query: str) -> dict[str, Any]:
        if not query:
            return {"status": "skipped", "reason": "empty_query", "results": []}
        search_url = "https://duckduckgo.com/html/?q=" + quote_plus(query)
        try:
            with httpx.Client(timeout=12.0, follow_redirects=True, headers={"User-Agent": "AI-Core-Runtime/1.0"}) as client:
                response = client.get(search_url)
                response.raise_for_status()
                soup = BeautifulSoup(response.text, "html.parser")
                results = []
                for item in soup.select(".result")[:3]:
                    anchor = item.select_one(".result__a")
                    snippet_node = item.select_one(".result__snippet")
                    href = self._normalize_url(str(anchor.get("href") if anchor else ""))
                    title = self._clean(anchor.get_text(" ") if anchor else "")
                    snippet = self._clean(snippet_node.get_text(" ") if snippet_node else "")
                    results.append({"url": href, "title": title, "snippet": snippet})
                selected = self._fetch_first(results)
                return {
                    "status": "success",
                    "query": query,
                    "search_url": search_url,
                    "results": results,
                    "selected_document": selected,
                    "fetched_at": self._now(),
                }
        except Exception as exc:
            return {"status": "error", "query": query, "search_url": search_url, "error": str(exc), "results": []}

    def _fetch_first(self, results: list[dict[str, Any]]) -> dict[str, Any]:
        for result in results:
            url = result.get("url") or ""
            if not url.startswith(("http://", "https://")):
                continue
            try:
                with httpx.Client(timeout=12.0, follow_redirects=True, headers={"User-Agent": "AI-Core-Runtime/1.0"}) as client:
                    response = client.get(url)
                    response.raise_for_status()
                soup = BeautifulSoup(response.text, "html.parser")
                for tag in soup(["script", "style", "noscript"]):
                    tag.decompose()
                text = self._clean(soup.get_text(" "))[:1800]
                return {"status": "success", "url": url, "title": result.get("title", ""), "text_excerpt": text, "response_status": response.status_code}
            except Exception as exc:
                return {"status": "error", "url": url, "error": str(exc)}
        return {"status": "skipped", "reason": "no_fetchable_result"}

    def _collect_fragments(self, inputs: dict[str, Any]) -> list[str]:
        fragments: list[str] = []
        for value in inputs.values():
            fragments.extend(self._extract_fragments(value))
        return [item for item in fragments if item]

    def _extract_fragments(self, value: Any) -> list[str]:
        if isinstance(value, dict):
            fragments: list[str] = []
            if value.get("result_text"):
                fragments.append(str(value.get("result_text"))[:800])
            evidence = value.get("evidence") if isinstance(value.get("evidence"), dict) else {}
            selected = evidence.get("selected_document") if isinstance(evidence, dict) else {}
            if isinstance(selected, dict):
                text = selected.get("text_excerpt") or selected.get("title") or ""
                if text:
                    fragments.append(str(text)[:900])
            results = evidence.get("results") if isinstance(evidence, dict) else []
            if isinstance(results, list):
                for result in results[:2]:
                    if isinstance(result, dict):
                        item = " - ".join(str(result.get(k) or "") for k in ("title", "snippet") if result.get(k))
                        if item:
                            fragments.append(item[:600])
            return fragments
        if isinstance(value, str):
            return [value[:800]]
        return [json.dumps(value, ensure_ascii=False)[:800]]

    def _stable_join(self, fragments: list[str]) -> str:
        seen: set[str] = set()
        lines: list[str] = []
        for fragment in fragments:
            cleaned = self._clean(fragment)
            if not cleaned:
                continue
            key = cleaned[:120].casefold()
            if key in seen:
                continue
            seen.add(key)
            lines.append(f"- {cleaned}")
            if len(lines) >= 8:
                break
        return "\n".join(lines)


    def _summarize_evidence(self, evidence: Any) -> str:
        if not isinstance(evidence, dict):
            return self._clean(str(evidence))[:900]
        lines: list[str] = []
        if evidence.get("result_text"):
            lines.append(self._clean(str(evidence.get("result_text")))[:1200])
        if evidence.get("selected_document") and isinstance(evidence.get("selected_document"), dict):
            selected = evidence["selected_document"]
            text = selected.get("text_excerpt") or selected.get("title") or ""
            if text:
                lines.append(self._clean(str(text))[:700])
        for result in evidence.get("results", [])[:2] if isinstance(evidence.get("results"), list) else []:
            if isinstance(result, dict):
                item = " - ".join(str(result.get(k) or "") for k in ("title", "snippet") if result.get(k))
                if item:
                    lines.append(self._clean(item)[:400])
        return "\n".join(f"- {line}" for line in lines if line)

    def _load_config(self) -> dict[str, Any]:
        try:
            return json.loads(self.tool_config_path.read_text(encoding="utf-8"))
        except Exception:
            return {"profiles": [], "text_cleanup": {}}

    def _compact_query(self, text: str) -> str:
        tokens = re.findall(r"[A-Za-z0-9_:\-]{2,}|[\u3040-\u30ff\u3400-\u9fff]{2,}", text or "")
        compact: list[str] = []
        for token in tokens:
            if token not in compact:
                compact.append(token)
            if len(" ".join(compact)) > 180:
                break
        return " ".join(compact)

    def _normalize_url(self, href: str) -> str:
        if not href:
            return ""
        if href.startswith("//"):
            return "https:" + href
        if href.startswith("/l/?") or "duckduckgo.com/l/" in href:
            parsed = urlparse(href)
            qs = parse_qs(parsed.query)
            if qs.get("uddg"):
                return unquote(qs["uddg"][0])
        return href

    def _write_output(self, payload: dict[str, Any]) -> Path:
        path = self.tool_output_dir / f"{payload.get('tool_call_id', uuid4().hex)}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def _clean(self, text: str) -> str:
        return re.sub(r"\s+", " ", str(text or "")).strip()

    def _now(self) -> str:
        return datetime.now().astimezone().isoformat()
