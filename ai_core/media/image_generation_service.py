from __future__ import annotations

import asyncio
import base64
import importlib
import json
import os
import subprocess
import urllib.request
from pathlib import Path
from typing import Any

from ai_core.config.loader import ConfigLoader
from ai_core.config.paths import RUNTIME_CONFIGS, RUNTIME_DOWNLOADS
from ai_core.runtime.modeling import ModelStagePolicy, RuntimeExecutionPolicy
from ai_core.runtime.modeling.user_model_selection import UserModelSelectionStore
from uuid import uuid4


class ImageGenerationService:
    """Provider-routed image generation capability.

    The service is capability- and provider-config driven.  It does not embed a
    concrete vendor, model, domain, or prompt policy.  Providers are read from
    runtime model configuration and selected by the shared model stage policy.
    """

    def __init__(self) -> None:
        self.loader = ConfigLoader()
        self.stage_policy = ModelStagePolicy()
        self.execution_policy = RuntimeExecutionPolicy()
        self.user_selection = UserModelSelectionStore()

    async def generate(self, *, prompt: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
        prompt = str(prompt or "").strip()
        options = options if isinstance(options, dict) else {}
        if not prompt:
            return {"ok": False, "status": "requires_input", "missing_inputs": ["prompt"]}

        config = self._provider_config()
        route, providers, stage_meta = self._route(config=config, options=options)
        attempted: list[dict[str, Any]] = []
        for provider_name in route:
            provider = dict(providers.get(provider_name, {}) or {})
            if not provider.get("enabled", True):
                attempted.append({"provider": provider_name, "status": "skipped", "reason": "disabled"})
                continue
            if not self.user_selection.route_allowed(provider_name, provider):
                attempted.append({"provider": provider_name, "status": "skipped", "reason": "not_allowed_by_user_model_source"})
                continue
            result = await self._call_provider(provider_name=provider_name, provider=provider, prompt=prompt, options=options)
            attempted.append({"provider": provider_name, "status": result.get("status") or result.get("ok")})
            if result.get("ok"):
                material = self._persist_image(result, provider_name=provider_name, stage_meta=stage_meta)
                return {"ok": True, "status": "completed", "material": material, "attempted": attempted, "stage_policy": stage_meta}
            if result.get("status") == "requires_setup":
                continue
        return {
            "ok": False,
            "status": "requires_setup",
            "message": "No configured image generation provider produced image material.",
            "attempted": attempted,
            "stage_policy": stage_meta,
        }

    def _provider_config(self) -> dict[str, Any]:
        path = RUNTIME_CONFIGS / "models" / "providers.yaml"
        data = self.loader.load_yaml(path)
        return data if isinstance(data, dict) else {}

    def _route(self, *, config: dict[str, Any], options: dict[str, Any]) -> tuple[list[str], dict[str, Any], dict[str, Any]]:
        providers = dict(config.get("providers") or {})
        base_route = list(config.get("default_route") or [])
        stage_route = list(options.get("provider_route") or base_route)
        config2, route, meta = self.stage_policy.apply_to_route(
            config=config,
            route=stage_route,
            node_id="image_generation",
            adapter={"model_stage": "image_generation", "preferred_local_model": options.get("preferred_local_model")},
            route_name="image_generation",
            escalated=bool(options.get("force_external")),
        )
        providers = dict(config2.get("providers") or providers)
        route = self.execution_policy.snapshot(provider_config=config2).filter_route(route or stage_route, providers)
        if not route:
            route = [name for name, provider in providers.items() if self._provider_can_generate_image(provider)]
        selected_provider = str(options.get("selected_provider") or "").strip()
        if selected_provider and selected_provider in providers:
            route = [selected_provider] + [item for item in route if item != selected_provider]
        return route, providers, meta

    def _provider_can_generate_image(self, provider: dict[str, Any]) -> bool:
        text = " ".join(str(provider.get(k) or "") for k in ("type", "protocol", "role"))
        caps = " ".join(str(x) for x in provider.get("capabilities", []) or [])
        modalities = json.dumps(provider.get("modalities") or {}, ensure_ascii=False)
        return "image_generation" in f"{text} {caps} {modalities}" or bool(provider.get("image_generation_endpoint") or provider.get("image_endpoint"))

    async def _call_provider(self, *, provider_name: str, provider: dict[str, Any], prompt: str, options: dict[str, Any]) -> dict[str, Any]:
        protocol = str(provider.get("protocol") or provider.get("type") or "").strip()
        if protocol in {"python_function", "function"}:
            return await asyncio.to_thread(self._call_python_function, provider, prompt, options)
        if protocol in {"local_command", "command"}:
            return await asyncio.to_thread(self._call_local_command, provider, prompt, options)
        if protocol in {"generic_http_json", "openai_compatible_api", "openai_compatible_image", "http_json", "image_generation_http"} or provider.get("image_generation_endpoint") or provider.get("image_endpoint"):
            return await asyncio.to_thread(self._call_http_json, provider_name, provider, prompt, options)
        return {"ok": False, "status": "requires_setup", "reason": "unsupported_provider_protocol"}

    def _call_python_function(self, provider: dict[str, Any], prompt: str, options: dict[str, Any]) -> dict[str, Any]:
        target = str(provider.get("callable") or provider.get("function") or "").strip()
        if not target or ":" not in target:
            return {"ok": False, "status": "requires_setup", "reason": "missing_callable"}
        module_name, func_name = target.split(":", 1)
        func = getattr(importlib.import_module(module_name), func_name)
        result = func(prompt=prompt, options=options, provider=provider)
        return self._normalize_provider_result(result)

    def _call_local_command(self, provider: dict[str, Any], prompt: str, options: dict[str, Any]) -> dict[str, Any]:
        command = provider.get("command") or provider.get("commands")
        if isinstance(command, str):
            command = [command]
        if not isinstance(command, list) or not command:
            return {"ok": False, "status": "requires_setup", "reason": "missing_command"}
        timeout = float(provider.get("timeout_seconds") or options.get("timeout_seconds") or 180)
        env = os.environ.copy()
        env["AI_CORE_IMAGE_PROMPT"] = prompt
        proc = subprocess.run([str(x) for x in command], input=prompt, text=True, capture_output=True, timeout=timeout, env=env)
        if proc.returncode != 0:
            return {"ok": False, "status": "failed", "stderr": proc.stderr[-1000:]}
        output = (proc.stdout or "").strip()
        try:
            return self._normalize_provider_result(json.loads(output))
        except Exception:
            return self._normalize_provider_result({"file_path": output})

    def _call_http_json(self, provider_name: str, provider: dict[str, Any], prompt: str, options: dict[str, Any]) -> dict[str, Any]:
        endpoint = str(provider.get("image_generation_endpoint") or provider.get("image_endpoint") or provider.get("endpoint") or "").strip()
        if not endpoint:
            base = str(provider.get("base_url") or "").rstrip("/")
            path = str(provider.get("image_generation_path") or provider.get("path") or "").strip("/")
            endpoint = f"{base}/{path}" if base and path else ""
        if not endpoint:
            return {"ok": False, "status": "requires_setup", "reason": "missing_endpoint"}
        secret_key = str(provider.get("secret_key") or provider.get("api_key_env") or "").strip()
        secret = os.getenv(secret_key) if secret_key else ""
        if secret_key and not secret:
            return {"ok": False, "status": "requires_setup", "reason": "missing_secret", "secret_key": secret_key}
        payload = self._render_payload(provider=provider, prompt=prompt, options=options)
        headers = {"Content-Type": "application/json"}
        if secret:
            headers[str(provider.get("authorization_header") or "Authorization")] = str(provider.get("authorization_prefix") or "Bearer ") + secret
        req = urllib.request.Request(endpoint, data=json.dumps(payload).encode("utf-8"), headers=headers, method=str(provider.get("method") or "POST"))
        timeout = float(provider.get("timeout_seconds") or options.get("timeout_seconds") or 180)
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read()
        try:
            data = json.loads(raw.decode("utf-8"))
        except Exception:
            data = {"image_bytes": base64.b64encode(raw).decode("ascii")}
        return self._normalize_provider_result(data)

    def _render_payload(self, *, provider: dict[str, Any], prompt: str, options: dict[str, Any]) -> dict[str, Any]:
        template = provider.get("request_template") if isinstance(provider.get("request_template"), dict) else {}
        if not template:
            template = {"prompt": "{prompt}"}
        rendered = json.loads(json.dumps(template))
        def walk(value: Any) -> Any:
            if isinstance(value, str):
                return value.replace("{prompt}", prompt)
            if isinstance(value, list):
                return [walk(x) for x in value]
            if isinstance(value, dict):
                return {k: walk(v) for k, v in value.items()}
            return value
        payload = walk(rendered)
        if isinstance(options.get("request_overrides"), dict):
            payload.update(options["request_overrides"])
        return payload

    def _normalize_provider_result(self, result: Any) -> dict[str, Any]:
        if not isinstance(result, dict):
            return {"ok": False, "status": "failed", "reason": "invalid_provider_result"}
        for key in ("file_path", "path", "output_path"):
            value = result.get(key)
            if value and Path(str(value)).exists():
                return {"ok": True, "status": "completed", "file_path": str(value)}
        for key in ("image_base64", "image_bytes", "b64_json", "base64"):
            value = result.get(key)
            if isinstance(value, str) and value.strip():
                return {"ok": True, "status": "completed", "image_base64": value.strip()}
        data = result.get("data")
        if isinstance(data, list):
            for item in data:
                normalized = self._normalize_provider_result(item)
                if normalized.get("ok"):
                    return normalized
        if result.get("url"):
            return {"ok": False, "status": "requires_setup", "reason": "remote_url_download_not_configured"}
        return {"ok": False, "status": str(result.get("status") or "failed"), "reason": str(result.get("reason") or "no_image_material")}

    def _persist_image(self, result: dict[str, Any], *, provider_name: str, stage_meta: dict[str, Any]) -> dict[str, Any]:
        download_id = f"image_{uuid4().hex[:12]}"
        target_dir = RUNTIME_DOWNLOADS / download_id
        target_dir.mkdir(parents=True, exist_ok=True)
        source_path = result.get("file_path")
        if source_path:
            src = Path(str(source_path))
            suffix = src.suffix or ".png"
            filename = f"generated_image{suffix}"
            target = target_dir / filename
            target.write_bytes(src.read_bytes())
        else:
            filename = "generated_image.png"
            target = target_dir / filename
            target.write_bytes(base64.b64decode(str(result.get("image_base64") or "")))
        size = target.stat().st_size
        download_url = f"/api/downloads/{download_id}/{filename}"
        material = {
            "type": "image",
            "download_id": download_id,
            "file_name": filename,
            "file_path": str(target),
            "download_url": download_url,
            "preview_url": download_url,
            "mime_type": "image/png" if filename.lower().endswith(".png") else "application/octet-stream",
            "size": size,
            "provider": provider_name,
            "stage_policy": stage_meta,
        }
        (target_dir / "metadata.json").write_text(json.dumps(material, ensure_ascii=False, indent=2), encoding="utf-8")
        return material
