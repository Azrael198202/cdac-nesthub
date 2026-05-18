from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4
from urllib.parse import quote_plus, urlparse, parse_qs, unquote

import httpx
from bs4 import BeautifulSoup

from auxiliary_brain.community.models import RuntimeAgentDefinition, RuntimeTaskDefinition


class RuntimeToolRuntime:
    """Generic tool executor for generated task nodes.

    The executor has no domain connectors. It can perform generic public
    discovery, compose generated material, and persist neutral deliveries.
    """

    ORIGIN = "auxiliary_brain"

    def __init__(self, runtime_root: str | Path = "runtime") -> None:
        self.runtime_root = Path(runtime_root)
        self.tool_output_dir = self.runtime_root / "generated" / "tool_outputs"
        self.delivery_dir = self.runtime_root / "deliveries"
        self.tool_output_dir.mkdir(parents=True, exist_ok=True)
        self.delivery_dir.mkdir(parents=True, exist_ok=True)

    def execute(
        self,
        *,
        task: RuntimeTaskDefinition,
        agent: RuntimeAgentDefinition,
        inputs: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        inputs = inputs or {}
        mode = str(task.parameters.get("execution_mode") or "collect")
        if task.input_refs or mode == "compose":
            output = self._compose(task=task, agent=agent, inputs=inputs)
        else:
            output = self._collect(task=task, agent=agent)
        artifact_path = self._write_output(output)
        output["artifact_path"] = str(artifact_path)
        return output

    def deliver(self, *, graph_id: str, content: dict[str, Any]) -> dict[str, Any]:
        delivery = {
            "delivery_id": f"delivery_{uuid4().hex[:8]}",
            "origin": self.ORIGIN,
            "graph_id": graph_id,
            "channel": "console",
            "status": "delivered",
            "created_at": self._now(),
            "content": content,
        }
        path = self.delivery_dir / f"{delivery['delivery_id']}.json"
        path.write_text(json.dumps(delivery, ensure_ascii=False, indent=2), encoding="utf-8")
        delivery["artifact_path"] = str(path)
        return delivery

    def _collect(self, *, task: RuntimeTaskDefinition, agent: RuntimeAgentDefinition) -> dict[str, Any]:
        query = self._compact_query(" ".join([task.objective, agent.role_label, " ".join(agent.capability_labels)]))
        evidence = self._public_discovery(query)
        return {
            "tool_call_id": f"tool_call_{uuid4().hex[:8]}",
            "origin": self.ORIGIN,
            "status": evidence.get("status", "completed"),
            "tool_type": "generic_public_discovery",
            "task_id": task.task_id,
            "agent_id": agent.agent_id,
            "query": query,
            "evidence": evidence,
            "created_at": self._now(),
        }

    def _compose(self, *, task: RuntimeTaskDefinition, agent: RuntimeAgentDefinition, inputs: dict[str, Any]) -> dict[str, Any]:
        fragments: list[str] = []
        for value in inputs.values():
            fragments.extend(self._extract_fragments(value))
        if not fragments:
            fragments.append(task.objective)
        summary = "\n".join(f"- {item}" for item in fragments[:8])
        return {
            "tool_call_id": f"tool_call_{uuid4().hex[:8]}",
            "origin": self.ORIGIN,
            "status": "completed",
            "tool_type": "generic_synthesis",
            "task_id": task.task_id,
            "agent_id": agent.agent_id,
            "result_text": summary,
            "input_count": len(inputs),
            "created_at": self._now(),
        }

    def _public_discovery(self, query: str) -> dict[str, Any]:
        if not query:
            return {"status": "skipped", "reason": "empty_query", "results": []}
        search_url = "https://duckduckgo.com/html/?q=" + quote_plus(query)
        try:
            with httpx.Client(timeout=12.0, follow_redirects=True, headers={"User-Agent": "Runtime-Agent-Studio/1.0"}) as client:
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
                fetched = self._fetch_first(results)
                return {
                    "status": "success",
                    "query": query,
                    "search_url": search_url,
                    "results": results,
                    "selected_document": fetched,
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
                with httpx.Client(timeout=12.0, follow_redirects=True, headers={"User-Agent": "Runtime-Agent-Studio/1.0"}) as client:
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

    def _extract_fragments(self, value: Any) -> list[str]:
        if isinstance(value, dict):
            fragments: list[str] = []
            evidence = value.get("evidence") if isinstance(value.get("evidence"), dict) else {}
            selected = evidence.get("selected_document") if isinstance(evidence, dict) else {}
            if isinstance(selected, dict):
                text = selected.get("text_excerpt") or selected.get("title") or ""
                if text:
                    fragments.append(str(text)[:600])
            for key in ("result_text", "query"):
                if value.get(key):
                    fragments.append(str(value.get(key))[:600])
            return fragments
        if isinstance(value, str):
            return [value[:600]]
        return [json.dumps(value, ensure_ascii=False)[:600]]

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
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def _clean(self, text: str) -> str:
        return re.sub(r"\s+", " ", str(text or "")).strip()

    def _now(self) -> str:
        return datetime.now().astimezone().isoformat()
