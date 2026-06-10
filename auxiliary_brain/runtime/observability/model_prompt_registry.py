from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import yaml

from ai_core.config.paths import CONFIGS_DIR, RUNTIME_CONFIGS, RUNTIME_TRACES, RUNTIME_GENERATED


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
            "options": self._discover_options(),
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
        for key in ("mode", "model", "provider", "system_prompt", "user_prompt", "prompt_id", "adapter_id"):
            if key in update:
                item[key] = update.get(key)
        item["updated_at"] = self._now_ms()
        item["location"] = location
        self.override_path.parent.mkdir(parents=True, exist_ok=True)
        self.override_path.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
        defaults = self._discover_defaults()
        return {
            "ok": True,
            "overrides": current,
            "effective": self._apply_overrides(defaults, current),
            "options": self._discover_options(),
        }

    def _discover_defaults(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        policy = self._read_yaml(CONFIGS_DIR / "brain_model_policy.yaml")
        base_runtime = self._runtime_execution_policy(policy)
        default_provider = self._first_non_empty(
            self._dig(policy, ["defaults", "provider"]),
            self._dig(policy, ["defaults", "route", "provider"]),
            "ollama",
        )
        default_model = self._first_non_empty(
            self._dig(policy, ["defaults", "model"]),
            self._dig(policy, ["defaults", "route", "model"]),
            base_runtime.get("default_local_model"),
            base_runtime.get("base_model"),
        )
        default_mode = str(base_runtime.get("default_mode") or "local_only")
        topology = self._read_json(CONFIGS_DIR / "model_routing_topology.json")
        routes = topology.get("routes") if isinstance(topology.get("routes"), dict) else {}
        nodes = topology.get("nodes") if isinstance(topology.get("nodes"), dict) else {}
        for node_id, node in sorted(nodes.items()):
            if not isinstance(node, dict):
                continue
            route_name = str(node.get("route_name") or node.get("route") or "")
            route = routes.get(route_name) if isinstance(routes.get(route_name), dict) else {}
            layer = self._infer_layer(str(node_id))
            task_policy = self._task_policy(policy, layer)
            model = self._first_non_empty(route.get("model"), route.get("model_id"), route.get("preferred_model"), task_policy.get("model"), default_model)
            provider = self._first_non_empty(route.get("provider"), route.get("provider_template"), task_policy.get("provider"), default_provider)
            items.append({
                "location": str(node_id),
                "layer": layer,
                "workflow": "runtime_default",
                "graph": "model_routing_topology",
                "route_name": route_name,
                "mode": default_mode,
                "model": model,
                "provider": provider,
                "prompt_id": f"{node_id}_default_prompt",
                "adapter_id": "",
                "system_prompt": self._default_system_prompt(layer=layer, location=str(node_id)),
                "user_prompt": self._default_user_prompt(layer=layer, location=str(node_id)),
                "source": str(CONFIGS_DIR / "model_routing_topology.json"),
                "editable": True,
            })
        stage_policy = self._read_json(CONFIGS_DIR / "model_stage_policy.seed.json")
        for node_id, node in self._walk_mapping(stage_policy):
            if not isinstance(node, dict):
                continue
            if any(k in node for k in ("model", "model_id", "provider", "system", "prompt", "system_prompt", "user_prompt")):
                loc = str(node.get("node_id") or node.get("stage") or node.get("id") or node_id)
                layer = self._infer_layer(loc)
                task_policy = self._task_policy(policy, layer)
                items.append({
                    "location": loc,
                    "layer": layer,
                    "workflow": str(node.get("workflow") or "runtime_stage_policy"),
                    "graph": str(node.get("graph") or "model_stage_policy"),
                    "route_name": str(node.get("route_name") or node.get("route") or ""),
                    "mode": str(node.get("mode") or default_mode),
                    "model": self._first_non_empty(node.get("model"), node.get("model_id"), task_policy.get("model"), default_model),
                    "provider": self._first_non_empty(node.get("provider"), node.get("provider_template"), task_policy.get("provider"), default_provider),
                    "prompt_id": str(node.get("prompt_id") or node.get("id") or f"{loc}_prompt"),
                    "adapter_id": str(node.get("adapter_id") or ""),
                    "system_prompt": node.get("system_prompt") or node.get("system") or self._default_system_prompt(layer=layer, location=loc),
                    "user_prompt": node.get("user_prompt") or node.get("prompt") or self._default_user_prompt(layer=layer, location=loc),
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
            layer = self._infer_layer(loc)
            task_policy = self._task_policy(policy, layer)
            items.append({
                "location": loc,
                "layer": layer,
                "workflow": str(ev.get("workflow") or ev.get("run_id") or "runtime_trace"),
                "graph": str(ev.get("graph") or "llm_trace"),
                "route_name": str(ev.get("route_name") or ""),
                "mode": str(ev.get("mode") or default_mode),
                "model": self._first_non_empty(ev.get("model"), task_policy.get("model"), default_model),
                "provider": self._first_non_empty(ev.get("provider"), task_policy.get("provider"), default_provider),
                "prompt_id": str(ev.get("prompt_id") or f"{loc}_runtime_prompt"),
                "adapter_id": str(ev.get("adapter_id") or ""),
                "system_prompt": str(ev.get("system_prompt") or self._default_system_prompt(layer=layer, location=loc)),
                "user_prompt": str(ev.get("user_prompt") or self._default_user_prompt(layer=layer, location=loc)),
                "source": str(ev.get("trace_path") or "runtime trace"),
                "editable": True,
            })
        return items

    def _discover_options(self) -> dict[str, Any]:
        policy = self._read_yaml(CONFIGS_DIR / "brain_model_policy.yaml")
        runtime_policy = self._runtime_execution_policy(policy)
        provider_templates = self._read_json(CONFIGS_DIR / "provider_runtime_templates.seed.json")
        provider_types = provider_templates.get("provider_types") if isinstance(provider_templates.get("provider_types"), dict) else {}
        providers = sorted({"ollama", "openai", "claude"} | set(str(k) for k in provider_types.keys()))
        models = set()
        for _, node in self._walk_mapping(policy):
            if isinstance(node, dict):
                for key in ("model", "default_local_model", "base_model", "local_fallback_model"):
                    val = node.get(key)
                    if isinstance(val, str) and val.strip():
                        models.add(val.strip())
        return {
            "modes": ["local_only", "api_only", "hybrid"],
            "providers": providers,
            "models": sorted(models) or ["qwen3.5:2b"],
            "default_mode": str(runtime_policy.get("default_mode") or "local_only"),
        }

    def _json_pretty(self, value: Any) -> str:
        if value in (None, "", [], {}):
            return ""
        if isinstance(value, str):
            return value
        try:
            return json.dumps(value, ensure_ascii=False, indent=2)
        except Exception:
            return str(value)

    def _normal_provider(self, value: Any) -> str:
        text = str(value or "").strip()
        low = text.casefold()
        for provider in ("ollama", "openai", "anthropic", "claude", "azure", "vllm", "local"):
            if provider in low:
                return "claude" if provider == "anthropic" else provider
        return text

    def _adapter_from_provider(self, value: Any) -> str:
        text = str(value or "").strip()
        low = text.casefold()
        if not text:
            return ""
        if low in {"ollama", "openai", "claude", "anthropic", "azure", "vllm", "local"}:
            return ""
        return text

    def _event_key(self, event: dict[str, Any]) -> str:
        return "|".join([
            str(event.get("run_id") or ""),
            str(event.get("node_id") or event.get("location") or ""),
            str(event.get("workflow") or ""),
            str(event.get("graph") or ""),
            str(event.get("model") or ""),
            str(event.get("provider") or ""),
        ])

    def _merge_live_events(self, events: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
        grouped: dict[str, dict[str, Any]] = {}
        for event in events:
            key = self._event_key(event)
            current = grouped.get(key)
            if current is None:
                current = dict(event)
                current["phases"] = []
                current["trace_paths"] = []
                grouped[key] = current
            current["timestamp"] = max(int(current.get("timestamp") or 0), int(event.get("timestamp") or 0))
            phase = str(event.get("phase") or "event")
            if phase not in current["phases"]:
                current["phases"].append(phase)
            path = str(event.get("trace_path") or "")
            if path and path not in current["trace_paths"]:
                current["trace_paths"].append(path)
            for field in ("system_prompt", "user_prompt", "assistant_response", "response_text", "raw_response", "parsed_result", "result"):
                if not current.get(field) and event.get(field):
                    current[field] = event.get(field)
            if phase.endswith("response") or "response" in phase:
                for field in ("assistant_response", "response_text", "raw_response", "parsed_result", "result"):
                    if event.get(field):
                        current[field] = event.get(field)
            if event.get("adapter_id") and not current.get("adapter_id"):
                current["adapter_id"] = event.get("adapter_id")
        out = []
        for idx, item in enumerate(grouped.values()):
            phases = item.get("phases") if isinstance(item.get("phases"), list) else []
            item["phase"] = " + ".join(phases) if phases else str(item.get("phase") or "event")
            item["event_id"] = f"{item.get('run_id','')}:{item.get('node_id') or item.get('location','')}:{idx}"
            if not item.get("trace_path") and item.get("trace_paths"):
                item["trace_path"] = item["trace_paths"][0]
            out.append(item)
        out.sort(key=lambda x: int(x.get("timestamp") or 0), reverse=True)
        return out[:limit]

    def _read_live_events(self, *, limit: int) -> list[dict[str, Any]]:
        raw_events: list[dict[str, Any]] = []
        root = RUNTIME_TRACES / "llm"
        paths: list[Path] = []
        if root.exists():
            paths = sorted(root.glob("*/*.json"), key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)[: max(limit * 4, limit)]
        for path in paths:
            payload = self._read_json(path)
            if not isinstance(payload, dict):
                continue
            phase = self._phase_from_path(path)
            node_id = str(payload.get("node_id") or "unknown_node")
            raw_provider = payload.get("provider") or payload.get("provider_name") or ""
            adapter_id = self._first_non_empty(payload.get("adapter_id"), self._adapter_from_provider(raw_provider))
            prompt_id = payload.get("prompt_id") or ""
            prompt_obj = payload.get("prompt") if isinstance(payload.get("prompt"), dict) else {}
            system_prompt = self._first_non_empty(
                payload.get("system_prompt"),
                prompt_obj.get("system"),
                payload.get("system"),
            )
            user_prompt = self._first_non_empty(
                payload.get("user_prompt"),
                payload.get("rendered_user_prompt"),
                prompt_obj.get("user"),
                payload.get("prompt_text"),
            )
            result_obj = payload.get("result")
            response_obj = self._first_non_empty(
                payload.get("assistant_response"),
                payload.get("response_text"),
                payload.get("text"),
                payload.get("content"),
                payload.get("raw_response"),
            )
            assistant_response = response_obj or self._json_pretty(result_obj)
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
                "provider": self._normal_provider(raw_provider),
                "model": str(payload.get("model") or payload.get("model_id") or ""),
                "mode": str(payload.get("mode") or ""),
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "assistant_response": assistant_response,
                "response_text": assistant_response,
                "raw_response": self._json_pretty(result_obj),
                "parsed_result": self._json_pretty(result_obj),
                "result": result_obj if isinstance(result_obj, (dict, list, str)) else "",
                "trace_path": str(path),
            }
            raw_events.append(event)
        if len(raw_events) < limit:
            raw_events.extend(self._read_model_decision_events(limit=limit-len(raw_events)))
        return self._merge_live_events(raw_events, limit=limit)

    def _read_model_decision_events(self, *, limit: int) -> list[dict[str, Any]]:
        """Expose model routing decisions as runtime usage when raw LLM traces are absent.

        Some flows use a model through the code-generation/provider selection path
        but older builds did not persist PromptIORecorder files.  This creates a
        read-only runtime event from the durable model decision plus nearby
        acquisition input, so the UI no longer appears empty.
        """
        path = RUNTIME_GENERATED / "model_decisions" / "brain_model_decisions.jsonl"
        if not path.exists():
            return []
        rows: list[dict[str, Any]] = []
        try:
            lines = path.read_text(encoding="utf-8").splitlines()[-max(limit * 3, limit):]
        except Exception:
            return []
        for idx, line in enumerate(reversed(lines)):
            try:
                payload = json.loads(line)
            except Exception:
                continue
            if not isinstance(payload, dict):
                continue
            route = payload.get("route") if isinstance(payload.get("route"), dict) else {}
            context = payload.get("context") if isinstance(payload.get("context"), dict) else {}
            tool_id = str(context.get("tool_id") or context.get("capability_id") or "model_decision")
            run_id = self._latest_related_run_id(tool_id)
            user_prompt = self._latest_related_user_input(run_id=run_id, tool_id=tool_id)
            task_type = str(route.get("task_type") or context.get("task_type") or "runtime_model_decision")
            node_id = f"{route.get('brain') or 'runtime'}:{task_type}"
            rows.append({
                "timestamp": self._parse_time_ms(payload.get("created_at")) or int(time.time() * 1000) - idx,
                "phase": "model_decision",
                "run_id": run_id or "runtime",
                "node_id": node_id,
                "location": node_id,
                "layer": str(route.get("brain") or "runtime"),
                "workflow": "capability_acquisition" if tool_id != "model_decision" else "runtime_model_routing",
                "graph": "model_decision_log",
                "adapter_id": "",
                "prompt_id": f"{task_type}_decision",
                "provider": self._normal_provider(route.get("provider") or ""),
                "model": str(route.get("model") or ""),
                "mode": str(route.get("mode") or ""),
                "adapter_id": self._adapter_from_provider(route.get("provider") or ""),
                "system_prompt": "Runtime model routing decision. This entry is reconstructed from durable model decision logs because no PromptIORecorder trace file was available for this run.",
                "user_prompt": user_prompt or json.dumps({"route": route, "context": context}, ensure_ascii=False, indent=2),
                "assistant_response": json.dumps(route, ensure_ascii=False, indent=2),
                "response_text": json.dumps(route, ensure_ascii=False, indent=2),
                "raw_response": json.dumps(payload, ensure_ascii=False, indent=2),
                "parsed_result": json.dumps(route, ensure_ascii=False, indent=2),
                "result": route,
                "trace_path": str(path),
            })
            if len(rows) >= limit:
                break
        return rows

    def _latest_related_run_id(self, tool_id: str) -> str:
        root = RUNTIME_TRACES / "capability_acquisition"
        try:
            candidates = sorted(root.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
        except Exception:
            candidates = []
        for path in candidates[:20]:
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            if tool_id and tool_id in text:
                return path.stem
        return ""

    def _latest_related_user_input(self, *, run_id: str, tool_id: str) -> str:
        paths = []
        if run_id:
            paths.append(RUNTIME_GENERATED / "capability_gap_resolutions" / f"{run_id}.json")
            paths.append(RUNTIME_TRACES / "conversation_core" / f"{run_id}.json")
        for path in paths:
            payload = self._read_json(path)
            if isinstance(payload, dict):
                value = payload.get("user_input") or payload.get("original_user_input")
                if isinstance(value, str) and value.strip():
                    return value
        return ""

    def _parse_time_ms(self, value: Any) -> int:
        try:
            from datetime import datetime
            return int(datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp() * 1000)
        except Exception:
            return 0

    def _apply_overrides(self, defaults: list[dict[str, Any]], overrides: dict[str, Any]) -> list[dict[str, Any]]:
        entries = overrides.get("entries") if isinstance(overrides.get("entries"), dict) else {}
        out: list[dict[str, Any]] = []
        for item in defaults:
            loc = str(item.get("location") or "")
            merged = dict(item)
            ov = entries.get(loc) if isinstance(entries.get(loc), dict) else None
            if ov:
                for key in ("mode", "model", "provider", "system_prompt", "user_prompt", "prompt_id", "adapter_id"):
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

    def _read_yaml(self, path: Path) -> Any:
        try:
            if not path.exists():
                return {}
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
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

    def _runtime_execution_policy(self, policy: dict[str, Any]) -> dict[str, Any]:
        value = self._dig(policy, ["brains", "ai_core", "runtime_execution_policy"])
        if isinstance(value, dict):
            return value
        stage = self._read_json(CONFIGS_DIR / "model_stage_policy.seed.json")
        value = self._dig(stage, ["global_policy", "runtime_execution_policy"])
        return value if isinstance(value, dict) else {}

    def _task_policy(self, policy: dict[str, Any], layer: str) -> dict[str, Any]:
        candidates = [
            self._dig(policy, ["brains", "ai_core", "tasks", layer]),
            self._dig(policy, ["brains", "auxiliary_brain", "tasks", layer]),
            self._dig(policy, ["brains", "ai_core", "default"]),
            self._dig(policy, ["defaults", "route"]),
            self._dig(policy, ["defaults"]),
        ]
        for item in candidates:
            if isinstance(item, dict) and item:
                return item
        return {}

    def _dig(self, value: Any, keys: list[str]) -> Any:
        cur = value
        for key in keys:
            if not isinstance(cur, dict):
                return None
            cur = cur.get(key)
        return cur

    def _first_non_empty(self, *values: Any) -> str:
        for value in values:
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    def _default_system_prompt(self, *, layer: str, location: str) -> str:
        return (
            "You are executing a generic AI runtime stage. "
            "Follow the layer contract, preserve explicit user inputs, avoid business-domain hardcoding, "
            "return structured output when the caller requires a schema, and do not perform work outside the current stage.\n"
            f"Layer: {layer}\nLocation: {location}"
        )

    def _default_user_prompt(self, *, layer: str, location: str) -> str:
        return (
            "Runtime will render the current request, clean context, workflow state, required schema, "
            "and available evidence here at execution time. This editable default describes the prompt slot, "
            "not a fixed business instruction.\n"
            f"Layer: {layer}\nLocation: {location}"
        )

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
