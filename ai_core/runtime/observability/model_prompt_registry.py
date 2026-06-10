from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from ai_core.config.paths import CONFIGS_DIR, RUNTIME_CONFIGS, RUNTIME_TRACES


class ModelPromptRegistry:
    """Generic registry for model and prompt observability/editing.

    The registry only reads generic runtime configuration and LLM trace material.
    It does not classify by domain and does not route execution.
    Runtime overrides are stored outside ai_core under runtime/configs.
    """

    def __init__(self, *, override_path: Path | None = None) -> None:
        self.override_path = override_path or (RUNTIME_CONFIGS / "model_prompt_overrides.json")

    def state(self) -> dict[str, Any]:
        defaults = self._discover_defaults()
        overrides = self._read_overrides()
        live = self._read_live_events(limit=200)
        return {
            "ok": True,
            "generated_at": self._now_ms(),
            "override_path": str(self.override_path),
            "defaults": defaults,
            "overrides": overrides,
            "effective": self._apply_overrides(defaults, overrides),
            "live_events": live,
        }

    def update(self, update: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(update, dict):
            return {"ok": False, "error": "invalid_update"}
        location = str(update.get("location") or update.get("node_id") or "").strip()
        if not location:
            return {"ok": False, "error": "missing_location"}
        current = self._read_overrides()
        entries = current.setdefault("entries", {})
        item = entries.setdefault(location, {})
        for key in ("model", "provider", "system_prompt", "user_prompt", "prompt_id", "adapter_id"):
            if key in update:
                item[key] = update.get(key)
        item["updated_at"] = self._now_ms()
        item["location"] = location
        self.override_path.parent.mkdir(parents=True, exist_ok=True)
        self.override_path.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"ok": True, "overrides": current, "effective": self._apply_overrides(self._discover_defaults(), current)}

    def _discover_defaults(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        topology = self._read_json(CONFIGS_DIR / "model_routing_topology.json")
        routes = topology.get("routes") if isinstance(topology.get("routes"), dict) else {}
        nodes = topology.get("nodes") if isinstance(topology.get("nodes"), dict) else {}
        for node_id, node in sorted(nodes.items()):
            if not isinstance(node, dict):
                continue
            route_name = str(node.get("route_name") or node.get("route") or "")
            route = routes.get(route_name) if isinstance(routes.get(route_name), dict) else {}
            items.append({
                "location": str(node_id),
                "layer": self._infer_layer(str(node_id)),
                "workflow": "runtime_default",
                "graph": "model_routing_topology",
                "route_name": route_name,
                "model": route.get("model") or route.get("model_id") or route.get("preferred_model") or "",
                "provider": route.get("provider") or route.get("provider_template") or "",
                "prompt_id": "",
                "adapter_id": "",
                "system_prompt": "",
                "user_prompt": "",
                "source": str(CONFIGS_DIR / "model_routing_topology.json"),
                "editable": True,
            })
        stage_policy = self._read_json(CONFIGS_DIR / "model_stage_policy.seed.json")
        for node_id, node in self._walk_mapping(stage_policy):
            if not isinstance(node, dict):
                continue
            if any(k in node for k in ("model", "model_id", "provider", "system", "prompt", "system_prompt", "user_prompt")):
                loc = str(node.get("node_id") or node.get("stage") or node.get("id") or node_id)
                items.append({
                    "location": loc,
                    "layer": self._infer_layer(loc),
                    "workflow": str(node.get("workflow") or "runtime_stage_policy"),
                    "graph": str(node.get("graph") or "model_stage_policy"),
                    "route_name": str(node.get("route_name") or node.get("route") or ""),
                    "model": node.get("model") or node.get("model_id") or "",
                    "provider": node.get("provider") or node.get("provider_template") or "",
                    "prompt_id": str(node.get("prompt_id") or node.get("id") or ""),
                    "adapter_id": str(node.get("adapter_id") or ""),
                    "system_prompt": node.get("system_prompt") or node.get("system") or "",
                    "user_prompt": node.get("user_prompt") or node.get("prompt") or "",
                    "source": str(CONFIGS_DIR / "model_stage_policy.seed.json"),
                    "editable": True,
                })
        latest = self._read_live_events(limit=80)
        known = {str(x.get("location")) for x in items}
        for ev in latest:
            loc = str(ev.get("node_id") or ev.get("location") or "unknown_node")
            if loc in known:
                continue
            known.add(loc)
            items.append({
                "location": loc,
                "layer": self._infer_layer(loc),
                "workflow": str(ev.get("workflow") or ev.get("run_id") or "runtime_trace"),
                "graph": str(ev.get("graph") or "llm_trace"),
                "route_name": str(ev.get("route_name") or ""),
                "model": str(ev.get("model") or ""),
                "provider": str(ev.get("provider") or ""),
                "prompt_id": str(ev.get("prompt_id") or ""),
                "adapter_id": str(ev.get("adapter_id") or ""),
                "system_prompt": str(ev.get("system_prompt") or ""),
                "user_prompt": str(ev.get("user_prompt") or ""),
                "source": str(ev.get("trace_path") or "runtime trace"),
                "editable": True,
            })
        return items

    def _read_live_events(self, *, limit: int) -> list[dict[str, Any]]:
        root = RUNTIME_TRACES / "llm"
        if not root.exists():
            return []
        paths = sorted(root.glob("*/*.json"), key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)[: max(limit * 3, limit)]
        out: list[dict[str, Any]] = []
        for path in paths:
            payload = self._read_json(path)
            if not isinstance(payload, dict):
                continue
            phase = self._phase_from_path(path)
            node_id = str(payload.get("node_id") or "unknown_node")
            adapter_id = payload.get("adapter_id") or ""
            prompt_id = payload.get("prompt_id") or ""
            event = {
                "timestamp": int(path.stat().st_mtime * 1000),
                "phase": phase,
                "run_id": str(payload.get("run_id") or path.parent.name),
                "node_id": node_id,
                "location": node_id,
                "layer": self._infer_layer(node_id),
                "workflow": str(payload.get("workflow") or path.parent.name),
                "graph": str(payload.get("graph") or "llm_trace"),
                "adapter_id": adapter_id,
                "prompt_id": prompt_id,
                "provider": str(payload.get("provider") or payload.get("provider_name") or ""),
                "model": str(payload.get("model") or payload.get("model_id") or ""),
                "system_prompt": payload.get("system_prompt") or "",
                "user_prompt": payload.get("user_prompt") or payload.get("rendered_user_prompt") or "",
                "result": payload.get("result") if isinstance(payload.get("result"), (dict, list, str)) else "",
                "trace_path": str(path),
            }
            out.append(event)
            if len(out) >= limit:
                break
        return out

    def _apply_overrides(self, defaults: list[dict[str, Any]], overrides: dict[str, Any]) -> list[dict[str, Any]]:
        entries = overrides.get("entries") if isinstance(overrides.get("entries"), dict) else {}
        out: list[dict[str, Any]] = []
        for item in defaults:
            loc = str(item.get("location") or "")
            merged = dict(item)
            ov = entries.get(loc) if isinstance(entries.get(loc), dict) else None
            if ov:
                for key in ("model", "provider", "system_prompt", "user_prompt", "prompt_id", "adapter_id"):
                    if key in ov:
                        merged[key] = ov.get(key)
                merged["override"] = ov
            out.append(merged)
        return out

    def _read_overrides(self) -> dict[str, Any]:
        payload = self._read_json(self.override_path)
        if not isinstance(payload, dict):
            return {"version": 1, "entries": {}}
        payload.setdefault("version", 1)
        payload.setdefault("entries", {})
        return payload

    def _read_json(self, path: Path) -> Any:
        try:
            if not path.exists():
                return {}
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _walk_mapping(self, value: Any, prefix: str = ""):
        if isinstance(value, dict):
            yield prefix, value
            for k, v in value.items():
                child = f"{prefix}.{k}" if prefix else str(k)
                yield from self._walk_mapping(v, child)
        elif isinstance(value, list):
            for i, v in enumerate(value):
                child = f"{prefix}[{i}]"
                yield from self._walk_mapping(v, child)

    def _phase_from_path(self, path: Path) -> str:
        name = path.stem
        parts = name.split("_", 1)
        return parts[1] if len(parts) > 1 else name

    def _infer_layer(self, node_id: str) -> str:
        text = str(node_id or "").lower()
        for layer in (
            "input_parsing",
            "intent_recognition",
            "requirement_completion",
            "context_awareness",
            "workflow_planning",
            "pre_execution_validation",
            "execution",
            "result_verification",
            "feedback_repair",
            "final_synthesis",
            "output",
        ):
            if layer in text:
                return layer
        return "runtime"

    def _now_ms(self) -> int:
        return int(time.time() * 1000)
