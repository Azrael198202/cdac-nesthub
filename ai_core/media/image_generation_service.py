from __future__ import annotations

import asyncio
import base64
import importlib
import json
import os
import shutil
import subprocess
import sys
import time
import traceback
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any
from uuid import uuid4

from ai_core.config.loader import ConfigLoader
from ai_core.config.paths import CONFIGS_DIR, RUNTIME_CONFIGS, RUNTIME_DIR, RUNTIME_DOWNLOADS
from ai_core.runtime.modeling import ModelStagePolicy, RuntimeExecutionPolicy
from ai_core.runtime.modeling.user_model_selection import UserModelSelectionStore


class ImageGenerationService:
    """Provider-routed image generation capability.

    The service is driven by runtime/provider configuration. Core code supports
    generic provider protocols and lifecycle hooks, while concrete models,
    checkpoints, workflow templates, endpoints, and install policies are read
    from configuration or runtime-generated provider records.
    """

    def __init__(self) -> None:
        self.loader = ConfigLoader()
        self.stage_policy = ModelStagePolicy()
        self.execution_policy = RuntimeExecutionPolicy()
        self.user_selection = UserModelSelectionStore()

    async def generate(self, *, prompt: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
        start_time = time.time()
        prompt = str(prompt or "").strip()
        options = options if isinstance(options, dict) else {}
        if not prompt:
            result = {"ok": False, "status": "requires_input", "missing_inputs": ["prompt"]}
            self._record_execution_event(result=result, duration_seconds=time.time() - start_time, attempted=[])
            return result

        config = self._provider_config()
        route, providers, stage_meta = self._route(config=config, options=options)
        attempted: list[dict[str, Any]] = []
        for provider_name in route:
            provider = dict(providers.get(provider_name, {}) or {})
            if not provider.get("enabled", True):
                attempted.append({"provider": provider_name, "status": "skipped", "reason": "disabled"})
                continue
            if not self._media_provider_allowed(provider_name, provider):
                attempted.append({"provider": provider_name, "status": "skipped", "reason": "not_allowed_by_runtime_source_policy"})
                continue
            result = await self._call_provider(provider_name=provider_name, provider=provider, prompt=prompt, options=options)
            attempted.append(self._attempt_record(provider_name=provider_name, result=result))
            if result.get("ok"):
                material = self._persist_image(result, provider_name=provider_name, stage_meta=stage_meta)
                final = {"ok": True, "status": "completed", "material": material, "attempted": attempted, "stage_policy": stage_meta}
                self._record_execution_event(result=final, duration_seconds=time.time() - start_time, attempted=attempted)
                return final
            if result.get("status") == "requires_setup":
                continue
        final = {
            "ok": False,
            "status": "requires_setup",
            "message": self._setup_message(attempted),
            "attempted": attempted,
            "setup_actions": self._setup_actions(route=route, providers=providers, attempted=attempted),
            "stage_policy": stage_meta,
        }
        self._record_execution_event(result=final, duration_seconds=time.time() - start_time, attempted=attempted)
        return final

    def _provider_config(self) -> dict[str, Any]:
        self._ensure_runtime_image_config()
        path = RUNTIME_CONFIGS / "models" / "providers.yaml"
        data = self.loader.load_yaml(path)
        config = data if isinstance(data, dict) else {}
        seeded = self._image_seed_config()
        if seeded:
            config = self._merge_provider_config(config, seeded)
        return config

    def _ensure_runtime_image_config(self) -> None:
        """Materialize a runtime-editable image capability config from the seed.

        The seed is only a bootstrap template. Runtime behavior should be
        adjusted through runtime configs or generated provider records without
        changing core source code.
        """
        runtime_path = RUNTIME_CONFIGS / "media" / "image_generation.yaml"
        if runtime_path.exists():
            return
        seed_path = CONFIGS_DIR / "image_generation.seed.yaml"
        if not seed_path.exists():
            return
        runtime_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(seed_path, runtime_path)

    def _image_seed_config(self) -> dict[str, Any]:
        # Load the packaged seed first, then overlay runtime overrides. This
        # keeps newly added provider templates available even when an older
        # runtime/configs/media/image_generation.yaml already exists.
        merged: dict[str, Any] = {}
        for path in [CONFIGS_DIR / "image_generation.seed.yaml", RUNTIME_CONFIGS / "media" / "image_generation.yaml"]:
            data = self.loader.load_yaml(path)
            if not isinstance(data, dict) or not data:
                continue
            merged = self._merge_provider_config(merged, data)
        return merged

    def _merge_provider_config(self, base: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
        merged = json.loads(json.dumps(base or {}))
        base_providers = merged.setdefault("providers", {})
        for name, provider in (extra.get("providers") or {}).items():
            if name not in base_providers:
                base_providers[name] = provider
            else:
                combined = dict(provider or {})
                combined.update(dict(base_providers.get(name) or {}))
                base_providers[name] = combined
        route = list(merged.get("default_route") or [])
        for item in extra.get("default_route") or []:
            if item not in route:
                route.append(item)
        merged["default_route"] = route
        return merged

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
        for name, provider in providers.items():
            if name not in route and self._provider_can_generate_image(provider) and self._media_provider_allowed(name, provider):
                route.append(name)
        selected_provider = str(options.get("selected_provider") or "").strip()
        if selected_provider and selected_provider in providers:
            route = [selected_provider] + [item for item in route if item != selected_provider]
        else:
            route = self._rank_route_by_observations(route, providers)
        return route, providers, meta

    def _media_provider_allowed(self, provider_name: str, provider: dict[str, Any]) -> bool:
        source_policy = provider.get("source_policy") if isinstance(provider.get("source_policy"), dict) else {}
        mode = str(source_policy.get("mode") or "").strip().lower()
        if mode in {"always_allowed", "fallback_allowed", "media_allowed"}:
            return True
        if mode in {"disabled", "never"}:
            return False
        return self.user_selection.route_allowed(provider_name, provider)

    def _rank_route_by_observations(self, route: list[str], providers: dict[str, Any]) -> list[str]:
        """Reorder equivalent providers using runtime observations.

        This is intentionally generic: it does not encode model names or
        capability-specific upgrade rules. It only prefers historically healthy
        and faster providers when the current user selection leaves routing to
        automatic mode.
        """
        if len(route) <= 1:
            return route
        observations = self._provider_observations()
        indexed = {name: index for index, name in enumerate(route)}

        def score(name: str) -> tuple[float, float, int]:
            stats = observations.get(name) or {}
            total = float(stats.get("total") or 0)
            success = float(stats.get("success") or 0)
            avg_duration = float(stats.get("avg_duration_seconds") or 1e9)
            success_rate = success / total if total > 0 else 0.5
            # Local providers stay preferred when observations are neutral.
            locality_bonus = 0.05 if self.user_selection.provider_is_local(name, providers.get(name) or {}) else 0.0
            return (-(success_rate + locality_bonus), avg_duration, indexed.get(name, 9999))

        return sorted(route, key=score)

    def _provider_observations(self) -> dict[str, dict[str, float]]:
        path = self._metrics_path()
        if not path.exists():
            return {}
        rows: list[dict[str, Any]] = []
        try:
            for line in path.read_text(encoding="utf-8").splitlines()[-200:]:
                try:
                    item = json.loads(line)
                except Exception:
                    continue
                if isinstance(item, dict):
                    rows.append(item)
        except Exception:
            return {}
        by_provider: dict[str, dict[str, float]] = {}
        for item in rows:
            provider = str(item.get("provider") or "").strip()
            if not provider:
                continue
            stats = by_provider.setdefault(provider, {"total": 0.0, "success": 0.0, "duration_sum": 0.0})
            stats["total"] += 1.0
            if bool(item.get("ok")):
                stats["success"] += 1.0
            stats["duration_sum"] += float(item.get("duration_seconds") or 0)
        for stats in by_provider.values():
            total = max(float(stats.get("total") or 0), 1.0)
            stats["avg_duration_seconds"] = float(stats.get("duration_sum") or 0) / total
        return by_provider

    def _provider_can_generate_image(self, provider: dict[str, Any]) -> bool:
        text = " ".join(str(provider.get(k) or "") for k in ("type", "protocol", "role"))
        caps = " ".join(str(x) for x in provider.get("capabilities", []) or [])
        modalities = json.dumps(provider.get("modalities") or {}, ensure_ascii=False)
        return "image_generation" in f"{text} {caps} {modalities}" or bool(provider.get("image_generation_endpoint") or provider.get("image_endpoint"))

    def _attempt_record(self, *, provider_name: str, result: dict[str, Any]) -> dict[str, Any]:
        record = {
            "provider": provider_name,
            "status": result.get("status") or result.get("ok"),
            "reason": result.get("reason"),
        }
        for key in ("endpoint", "root", "secret_key", "stderr", "log_path", "startup_log_tail", "missing_files", "returncode"):
            value = result.get(key)
            if value:
                record[key] = str(value)[-1000:] if key == "stderr" else value
        return record

    def _setup_message(self, attempted: list[dict[str, Any]]) -> str:
        if not attempted:
            return "Image generation is recognized, but no image provider is available in the current runtime route."
        parts = []
        for item in attempted[:5]:
            provider = str(item.get("provider") or "provider")
            reason = str(item.get("reason") or item.get("status") or "not_ready")
            parts.append(f"{provider}: {reason}")
        return "Image generation provider setup is required. Attempted providers: " + "; ".join(parts) + "."

    def _setup_actions(self, *, route: list[str], providers: dict[str, Any], attempted: list[dict[str, Any]]) -> list[dict[str, Any]]:
        actions: list[dict[str, Any]] = []
        attempted_by_provider = {str(x.get("provider") or ""): x for x in attempted if isinstance(x, dict)}
        for provider_name in route:
            provider = providers.get(provider_name) if isinstance(providers.get(provider_name), dict) else {}
            attempt = attempted_by_provider.get(provider_name, {})
            protocol = str(provider.get("protocol") or provider.get("type") or "").strip()
            reason = str(attempt.get("reason") or "").strip()
            if str(provider.get("api_key_env") or provider.get("secret_key") or "").strip():
                env_name = str(provider.get("api_key_env") or provider.get("secret_key"))
                actions.append({
                    "provider": provider_name,
                    "kind": "set_secret",
                    "env": env_name,
                    "message": f"Set {env_name} for this provider or disable it in runtime/configs/media/image_generation.yaml.",
                })
            if protocol in {"comfyui", "comfyui_runtime", "local_comfyui"} or "runtime" in provider:
                actions.append({
                    "provider": provider_name,
                    "kind": "prepare_local_runtime",
                    "message": "Prepare the configured local media runtime and model assets, or point runtime/configs/media/image_generation.yaml to an already running endpoint.",
                    "reason": reason or str(attempt.get("status") or "not_ready"),
                    "endpoint": provider.get("base_url") or (provider.get("runtime") or {}).get("base_url"),
                })
            if not provider:
                actions.append({"provider": provider_name, "kind": "register_provider", "message": "Register a provider record for this route."})
        return actions

    async def _call_provider(self, *, provider_name: str, provider: dict[str, Any], prompt: str, options: dict[str, Any]) -> dict[str, Any]:
        protocol = str(provider.get("protocol") or provider.get("type") or "").strip()
        if protocol in {"comfyui", "comfyui_runtime", "local_comfyui"}:
            return await asyncio.to_thread(self._call_comfyui, provider_name, provider, prompt, options)
        if protocol in {"python_function", "function"}:
            return await asyncio.to_thread(self._call_python_function, provider, prompt, options)
        if protocol in {"local_command", "command"}:
            return await asyncio.to_thread(self._call_local_command, provider, prompt, options)
        if protocol in {"generic_http_json", "openai_compatible_api", "openai_compatible_image", "http_json", "image_generation_http"} or provider.get("image_generation_endpoint") or provider.get("image_endpoint"):
            return await asyncio.to_thread(self._call_http_json, provider_name, provider, prompt, options)
        return {"ok": False, "status": "requires_setup", "reason": "unsupported_provider_protocol"}

    def _call_comfyui(self, provider_name: str, provider: dict[str, Any], prompt: str, options: dict[str, Any]) -> dict[str, Any]:
        runtime = self._runtime_settings(provider)
        endpoint = str(provider.get("base_url") or runtime.get("base_url") or "http://127.0.0.1:8188").rstrip("/")
        ensure = self._ensure_comfyui_runtime(provider=provider, runtime=runtime, endpoint=endpoint)
        if not ensure.get("ok"):
            return ensure
        assets = self._ensure_model_assets(provider=provider, runtime=runtime)
        if not assets.get("ok"):
            return assets
        workflow = self._render_workflow(provider=provider, runtime=runtime, prompt=prompt, options=options)
        if not workflow.get("ok"):
            return workflow
        queued = self._comfy_post_json(endpoint, "/prompt", {"prompt": workflow["workflow"]}, timeout=float(runtime.get("request_timeout_seconds") or 30))
        prompt_id = str((queued or {}).get("prompt_id") or "")
        if not prompt_id:
            return {"ok": False, "status": "failed", "reason": "missing_prompt_id", "response": queued}
        timeout_seconds = self._effective_generation_timeout(provider=provider, runtime=runtime, options=options)
        history = self._wait_comfy_history(endpoint=endpoint, prompt_id=prompt_id, timeout=timeout_seconds)
        if not history.get("ok"):
            history.setdefault("timeout_seconds", timeout_seconds)
            return history
        image = self._extract_comfy_image(endpoint=endpoint, history=history["history"], target_dir=self._provider_temp_dir(provider_name))
        if not image.get("ok"):
            return image
        return {"ok": True, "status": "completed", "file_path": image["file_path"], "provider_response": {"prompt_id": prompt_id}}

    def _runtime_settings(self, provider: dict[str, Any]) -> dict[str, Any]:
        runtime = provider.get("runtime") if isinstance(provider.get("runtime"), dict) else {}
        return dict(runtime or {})

    def _effective_generation_timeout(self, *, provider: dict[str, Any], runtime: dict[str, Any], options: dict[str, Any]) -> float:
        configured = options.get("generation_timeout_seconds") or runtime.get("generation_timeout_seconds") or provider.get("timeout_seconds") or options.get("timeout_seconds") or 300
        try:
            value = float(configured)
        except Exception:
            value = 300.0
        # Local media runtimes can legitimately finish after several minutes on
        # CPU/MPS/low-memory environments. Treat the seed/runtime value as a
        # lower bound, not as a hard business rule, so a successful backend job
        # is not reported as provider failure before it has time to produce the
        # artifact. Users may still reduce this per request with
        # strict_timeout_seconds when they intentionally want a fast cutoff.
        if options.get("strict_timeout_seconds") is not None:
            try:
                return max(1.0, float(options.get("strict_timeout_seconds")))
            except Exception:
                return max(1.0, value)
        floor = runtime.get("minimum_generation_timeout_seconds") or provider.get("minimum_generation_timeout_seconds") or 900
        try:
            floor_value = float(floor)
        except Exception:
            floor_value = 900.0
        return max(value, floor_value)

    def _provider_temp_dir(self, provider_name: str) -> Path:
        path = RUNTIME_DIR / "generated" / "media" / "temp" / provider_name
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _ensure_comfyui_runtime(self, *, provider: dict[str, Any], runtime: dict[str, Any], endpoint: str) -> dict[str, Any]:
        if self._comfy_healthy(endpoint, float(runtime.get("health_timeout_seconds") or 2)):
            self._log_comfy_bootstrap_event("health_check", {"ok": True, "endpoint": endpoint, "reason": "already_running"})
            return {"ok": True, "status": "ready"}
        if not bool(runtime.get("auto_start", True)):
            result = {"ok": False, "status": "requires_setup", "reason": "runtime_not_running", "endpoint": endpoint}
            self._log_comfy_bootstrap_event("health_check", result)
            return result
        root = self._resolve_runtime_root(runtime)
        install = runtime.get("install") if isinstance(runtime.get("install"), dict) else {}
        integrity = self._comfyui_runtime_integrity(root)
        if not integrity.get("ok"):
            self._log_comfy_bootstrap_event("integrity_check", {**integrity, "root": str(root)})
            installed = self._install_runtime(root=root, install=install, integrity=integrity)
            if not installed.get("ok"):
                return installed
            integrity = self._comfyui_runtime_integrity(root)
            if not integrity.get("ok"):
                result = {
                    "ok": False,
                    "status": "requires_setup",
                    "reason": "runtime_install_incomplete",
                    "root": str(root),
                    "missing_files": integrity.get("missing_files", []),
                    "log_path": str(self._comfy_bootstrap_log_path()),
                }
                self._log_comfy_bootstrap_event("install_incomplete", result)
                return result
        started = self._start_runtime_process(root=root, runtime=runtime)
        if not started.get("ok"):
            return started
        wait_seconds = float(runtime.get("startup_timeout_seconds") or 120)
        deadline = time.time() + wait_seconds
        while time.time() < deadline:
            if self._comfy_healthy(endpoint, float(runtime.get("health_timeout_seconds") or 3)):
                result = {"ok": True, "status": "ready", "started": True, "pid": started.get("pid")}
                self._log_comfy_bootstrap_event("startup_ready", {**result, "endpoint": endpoint, "root": str(root)})
                return result
            if started.get("pid") and not self._process_alive(int(started.get("pid"))):
                result = {
                    "ok": False,
                    "status": "requires_setup",
                    "reason": "runtime_exited_during_startup",
                    "endpoint": endpoint,
                    "root": str(root),
                    "pid": started.get("pid"),
                    "startup_log_tail": self._tail_file(Path(str(started.get("log_path") or "")), limit=4000),
                    "log_path": str(started.get("log_path") or ""),
                }
                self._log_comfy_bootstrap_event("startup_exit", result)
                return result
            time.sleep(2)
        result = {
            "ok": False,
            "status": "requires_setup",
            "reason": "runtime_start_timeout",
            "endpoint": endpoint,
            "root": str(root),
            "startup_timeout_seconds": wait_seconds,
            "startup_log_tail": self._tail_file(Path(str(started.get("log_path") or "")), limit=4000),
            "log_path": str(started.get("log_path") or ""),
        }
        self._log_comfy_bootstrap_event("startup_timeout", result)
        return result

    def _comfyui_runtime_integrity(self, root: Path) -> dict[str, Any]:
        required = ["main.py", "requirements.txt"]
        missing = [name for name in required if not (root / name).exists()]
        if not root.exists():
            return {"ok": False, "reason": "runtime_root_missing", "missing_files": required}
        if missing:
            return {"ok": False, "reason": "runtime_root_incomplete", "missing_files": missing}
        return {"ok": True, "reason": "runtime_root_complete"}

    def _repair_incomplete_runtime_root(self, *, root: Path, install: dict[str, Any]) -> dict[str, Any]:
        if install.get("repair_incomplete") is False:
            return {"ok": False, "status": "requires_setup", "reason": "runtime_root_incomplete", "root": str(root), "missing_files": self._comfyui_runtime_integrity(root).get("missing_files", [])}
        try:
            safe_parent = (RUNTIME_DIR / "external_runtimes").resolve()
            resolved = root.resolve()
            allow_external = bool(install.get("allow_external_runtime_cleanup", False))
            if safe_parent not in [resolved, *resolved.parents] and not allow_external:
                result = {"ok": False, "status": "requires_setup", "reason": "runtime_root_incomplete_manual_cleanup_required", "root": str(root), "safe_parent": str(safe_parent)}
                self._log_comfy_bootstrap_event("repair_refused", result)
                return result
            marker = root.with_name(root.name + f".incomplete.{int(time.time())}")
            if marker.exists():
                shutil.rmtree(marker, ignore_errors=True)
            root.rename(marker)
            self._log_comfy_bootstrap_event("repair_renamed_incomplete_root", {"ok": True, "from": str(root), "to": str(marker)})
            return {"ok": True, "status": "repaired", "old_root": str(marker)}
        except Exception as exc:
            result = {"ok": False, "status": "requires_setup", "reason": "runtime_root_repair_failed", "error_type": exc.__class__.__name__, "error": str(exc)[-2000:], "root": str(root)}
            self._log_comfy_bootstrap_event("repair_failed", result)
            return result

    def _comfy_logs_dir(self) -> Path:
        path = RUNTIME_DIR / "logs"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _comfy_bootstrap_log_path(self) -> Path:
        return self._comfy_logs_dir() / "comfyui_bootstrap.jsonl"

    def _comfy_named_log_path(self, name: str) -> Path:
        return self._comfy_logs_dir() / name

    def _append_text_log(self, path: Path, text: str) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8", errors="replace") as fh:
                fh.write("\n" + "=" * 80 + "\n")
                fh.write(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()) + "\n")
                fh.write(text or "")
                fh.write("\n")
        except Exception:
            return

    def _log_comfy_bootstrap_event(self, stage: str, payload: dict[str, Any]) -> None:
        try:
            event = {
                "event_type": "comfyui_bootstrap",
                "stage": stage,
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                **(payload if isinstance(payload, dict) else {}),
            }
            # Keep command diagnostics useful without leaking unlimited output.
            for key in ("stderr", "stdout", "error", "startup_log_tail"):
                if key in event and event[key] is not None:
                    event[key] = str(event[key])[-4000:]
            with self._comfy_bootstrap_log_path().open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(event, ensure_ascii=False) + "\n")
        except Exception:
            return

    def _tail_file(self, path: Path, *, limit: int = 4000) -> str:
        try:
            if not path or not path.exists():
                return ""
            data = path.read_bytes()[-limit:]
            return data.decode("utf-8", errors="replace")
        except Exception:
            return ""

    def _process_alive(self, pid: int) -> bool:
        try:
            if pid <= 0:
                return False
            os.kill(pid, 0)
            return True
        except Exception:
            return False

    def _resolve_runtime_root(self, runtime: dict[str, Any]) -> Path:
        root = self._resolve_config_value(str(runtime.get("root") or "").strip())
        if root:
            return Path(root).expanduser().resolve()
        return (RUNTIME_DIR / "external_runtimes" / "comfyui").resolve()

    def _runtime_python(self, *, root: Path, runtime: dict[str, Any], install: dict[str, Any] | None = None) -> str:
        install = install if isinstance(install, dict) else {}
        explicit = self._resolve_config_value(str(runtime.get("python") or install.get("python") or "").strip())
        if explicit:
            return explicit
        if bool(install.get("create_venv", runtime.get("create_venv", True))):
            venv_dir = root / str(install.get("venv_dir") or runtime.get("venv_dir") or ".venv")
            if os.name == "nt":
                candidate = venv_dir / "Scripts" / "python.exe"
            else:
                candidate = venv_dir / "bin" / "python"
            if candidate.exists():
                return str(candidate)
        return sys.executable

    def _venv_python_path(self, *, root: Path, install: dict[str, Any]) -> Path:
        venv_dir = root / str(install.get("venv_dir") or ".venv")
        if os.name == "nt":
            return venv_dir / "Scripts" / "python.exe"
        return venv_dir / "bin" / "python"

    def _ensure_runtime_python(self, *, root: Path, install: dict[str, Any]) -> dict[str, Any]:
        if not bool(install.get("create_venv", True)):
            return {"ok": True, "python": sys.executable, "venv": False}
        python_path = self._venv_python_path(root=root, install=install)
        if python_path.exists():
            return {"ok": True, "python": str(python_path), "venv": True}
        root.mkdir(parents=True, exist_ok=True)
        create = subprocess.run([sys.executable, "-m", "venv", str(python_path.parents[1])], text=True, capture_output=True, timeout=float(install.get("venv_timeout_seconds") or 600))
        if create.returncode != 0:
            return {"ok": False, "status": "requires_setup", "reason": "runtime_venv_create_failed", "stderr": create.stderr[-1000:], "root": str(root)}
        return {"ok": True, "python": str(python_path), "venv": True}

    def _install_runtime(self, *, root: Path, install: dict[str, Any], integrity: dict[str, Any] | None = None) -> dict[str, Any]:
        if not bool(install.get("enabled", True)):
            result = {"ok": False, "status": "requires_setup", "reason": "runtime_missing", "root": str(root)}
            self._log_comfy_bootstrap_event("install_disabled", result)
            return result
        repo = str(install.get("repository") or "https://github.com/comfyanonymous/ComfyUI.git").strip()
        root.parent.mkdir(parents=True, exist_ok=True)
        self._log_comfy_bootstrap_event("install_begin", {"root": str(root), "repository": repo, "integrity": integrity or {}})
        if root.exists() and not self._comfyui_runtime_integrity(root).get("ok"):
            repaired = self._repair_incomplete_runtime_root(root=root, install=install)
            if not repaired.get("ok"):
                return repaired
        if not root.exists():
            git = shutil.which("git")
            if not git:
                result = {"ok": False, "status": "requires_setup", "reason": "git_not_available", "root": str(root)}
                self._log_comfy_bootstrap_event("git_missing", result)
                return result
            clone_log = self._comfy_named_log_path("comfyui_clone.log")
            cmd = [git, "clone", "--depth", "1", repo, str(root)]
            self._log_comfy_bootstrap_event("git_clone_start", {"command": cmd, "root": str(root), "log_path": str(clone_log)})
            try:
                clone = subprocess.run(cmd, text=True, capture_output=True, timeout=float(install.get("clone_timeout_seconds") or 1800))
            except Exception as exc:
                result = {
                    "ok": False,
                    "status": "requires_setup",
                    "reason": "runtime_clone_exception",
                    "error_type": exc.__class__.__name__,
                    "error": str(exc)[-2000:],
                    "root": str(root),
                    "log_path": str(clone_log),
                }
                self._append_text_log(clone_log, traceback.format_exc())
                self._log_comfy_bootstrap_event("git_clone_exception", result)
                return result
            self._append_text_log(clone_log, "STDOUT:\n" + (clone.stdout or "") + "\nSTDERR:\n" + (clone.stderr or ""))
            if clone.returncode != 0:
                result = {"ok": False, "status": "requires_setup", "reason": "runtime_clone_failed", "returncode": clone.returncode, "stderr": (clone.stderr or "")[-4000:], "root": str(root), "log_path": str(clone_log)}
                self._log_comfy_bootstrap_event("git_clone_failed", result)
                return result
            self._log_comfy_bootstrap_event("git_clone_completed", {"ok": True, "root": str(root), "log_path": str(clone_log)})
        integrity_after_clone = self._comfyui_runtime_integrity(root)
        if not integrity_after_clone.get("ok"):
            result = {"ok": False, "status": "requires_setup", "reason": "runtime_clone_incomplete", "root": str(root), "missing_files": integrity_after_clone.get("missing_files", []), "log_path": str(self._comfy_bootstrap_log_path())}
            self._log_comfy_bootstrap_event("git_clone_incomplete", result)
            return result
        py = self._ensure_runtime_python(root=root, install=install)
        self._log_comfy_bootstrap_event("python_ready", {**py, "root": str(root)})
        if not py.get("ok"):
            return py
        if bool(install.get("install_requirements", True)):
            req = root / "requirements.txt"
            if req.exists():
                pip_log = self._comfy_named_log_path("comfyui_install.log")
                cmd = [str(py["python"]), "-m", "pip", "install", "-r", str(req)]
                self._log_comfy_bootstrap_event("pip_install_start", {"command": cmd, "root": str(root), "log_path": str(pip_log)})
                try:
                    pip = subprocess.run(cmd, text=True, capture_output=True, timeout=float(install.get("pip_timeout_seconds") or 3600))
                except Exception as exc:
                    result = {"ok": False, "status": "requires_setup", "reason": "runtime_dependency_install_exception", "error_type": exc.__class__.__name__, "error": str(exc)[-2000:], "root": str(root), "log_path": str(pip_log)}
                    self._append_text_log(pip_log, traceback.format_exc())
                    self._log_comfy_bootstrap_event("pip_install_exception", result)
                    return result
                self._append_text_log(pip_log, "STDOUT:\n" + (pip.stdout or "") + "\nSTDERR:\n" + (pip.stderr or ""))
                if pip.returncode != 0:
                    result = {"ok": False, "status": "requires_setup", "reason": "runtime_dependency_install_failed", "returncode": pip.returncode, "stderr": (pip.stderr or "")[-4000:], "root": str(root), "log_path": str(pip_log)}
                    self._log_comfy_bootstrap_event("pip_install_failed", result)
                    return result
                self._log_comfy_bootstrap_event("pip_install_completed", {"ok": True, "root": str(root), "log_path": str(pip_log)})
        result = {"ok": True, "status": "installed", "root": str(root), "python": str(py.get("python")), "log_path": str(self._comfy_bootstrap_log_path())}
        self._log_comfy_bootstrap_event("install_completed", result)
        return result

    def _start_runtime_process(self, *, root: Path, runtime: dict[str, Any]) -> dict[str, Any]:
        process_dir = RUNTIME_DIR / "processes"
        process_dir.mkdir(parents=True, exist_ok=True)
        log_path = self._comfy_named_log_path("comfyui_startup.log")
        command = runtime.get("start_command")
        if isinstance(command, str):
            command = [command]
        install = runtime.get("install") if isinstance(runtime.get("install"), dict) else {}
        if not isinstance(command, list) or not command:
            command = [self._runtime_python(root=root, runtime=runtime, install=install), "main.py", "--listen", str(runtime.get("host") or "127.0.0.1"), "--port", str(runtime.get("port") or "8188")]
        self._log_comfy_bootstrap_event("startup_begin", {"command": [str(x) for x in command], "root": str(root), "log_path": str(log_path)})
        try:
            with log_path.open("ab") as log:
                proc = subprocess.Popen([str(x) for x in command], cwd=str(root), stdout=log, stderr=log, start_new_session=True)
            (process_dir / "comfyui.pid").write_text(str(proc.pid), encoding="utf-8")
            result = {"ok": True, "status": "starting", "pid": proc.pid, "log_path": str(log_path)}
            self._log_comfy_bootstrap_event("startup_process_created", {**result, "root": str(root)})
            return result
        except Exception as exc:
            result = {"ok": False, "status": "requires_setup", "reason": "runtime_start_failed", "error_type": exc.__class__.__name__, "error": str(exc), "root": str(root), "log_path": str(log_path)}
            self._append_text_log(log_path, traceback.format_exc())
            self._log_comfy_bootstrap_event("startup_exception", result)
            return result

    def _comfy_healthy(self, endpoint: str, timeout: float) -> bool:
        try:
            with urllib.request.urlopen(endpoint.rstrip("/") + "/system_stats", timeout=timeout) as response:
                return 200 <= int(response.status) < 500
        except Exception:
            return False

    def _ensure_model_assets(self, *, provider: dict[str, Any], runtime: dict[str, Any]) -> dict[str, Any]:
        assets = provider.get("model_assets") or runtime.get("model_assets") or []
        if not isinstance(assets, list):
            return {"ok": False, "status": "requires_setup", "reason": "invalid_model_assets"}
        root = self._resolve_runtime_root(runtime)
        if not assets:
            return {"ok": True, "status": "ready", "assets": []}
        ready: list[dict[str, str]] = []
        for asset in assets:
            if not isinstance(asset, dict):
                continue
            target = self._asset_target(root=root, asset=asset)
            if target.exists() and target.stat().st_size > 0:
                ready.append({"target": str(target), "status": "exists"})
                continue
            if not bool(asset.get("auto_download", True)):
                return {"ok": False, "status": "requires_setup", "reason": "asset_missing", "target": str(target)}
            url = self._resolve_config_value(str(asset.get("url") or asset.get("source_url") or "").strip())
            if not url:
                return {"ok": False, "status": "requires_setup", "reason": "asset_url_missing", "target": str(target), "env_hint": asset.get("url_env")}
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                self._download_file(url=url, target=target, timeout=float(asset.get("timeout_seconds") or 7200))
            except Exception as exc:
                return {"ok": False, "status": "requires_setup", "reason": "asset_download_failed", "target": str(target), "error": str(exc)}
            ready.append({"target": str(target), "status": "downloaded"})
        return {"ok": True, "status": "ready", "assets": ready}

    def _asset_target(self, *, root: Path, asset: dict[str, Any]) -> Path:
        target = str(asset.get("target") or "").strip()
        if target:
            return Path(os.path.expandvars(target)).expanduser().resolve()
        subdir = str(asset.get("target_subdir") or "models/checkpoints").strip().strip("/")
        filename = self._resolve_config_value(str(asset.get("file_name") or asset.get("filename") or "").strip())
        if not filename:
            url = str(asset.get("url") or asset.get("source_url") or "").strip()
            filename = Path(urllib.parse.urlparse(url).path).name or "model.asset"
        return (root / subdir / filename).resolve()

    def _resolve_config_value(self, value: str) -> str:
        value = (value or "").strip()
        if value.startswith("env:"):
            return os.getenv(value.split(":", 1)[1], "")
        expanded = os.path.expandvars(value)
        if "${" in expanded or "$" in expanded:
            return ""
        return expanded

    def _download_file(self, *, url: str, target: Path, timeout: float) -> None:
        tmp = target.with_suffix(target.suffix + ".partial")
        req = urllib.request.Request(url, headers={"User-Agent": "ai-core-runtime"})
        with urllib.request.urlopen(req, timeout=timeout) as response, tmp.open("wb") as fh:
            shutil.copyfileobj(response, fh)
        tmp.replace(target)

    def _render_workflow(self, *, provider: dict[str, Any], runtime: dict[str, Any], prompt: str, options: dict[str, Any]) -> dict[str, Any]:
        template = options.get("workflow_template") or provider.get("workflow_template") or runtime.get("workflow_template")
        if isinstance(template, str):
            template_path = Path(os.path.expandvars(template)).expanduser()
            if template_path.exists():
                template = json.loads(template_path.read_text(encoding="utf-8"))
            else:
                try:
                    template = json.loads(template)
                except Exception:
                    template = None
        if not isinstance(template, dict):
            return {"ok": False, "status": "requires_setup", "reason": "workflow_template_missing"}
        substitutions = dict(provider.get("workflow_values") if isinstance(provider.get("workflow_values"), dict) else {})
        substitutions.update(dict(options.get("workflow_values") if isinstance(options.get("workflow_values"), dict) else {}))
        substitutions.setdefault("prompt", prompt)
        substitutions.setdefault("negative_prompt", str(options.get("negative_prompt") or provider.get("negative_prompt") or ""))
        substitutions.setdefault("seed", str(options.get("seed") or provider.get("seed") or int(time.time()) % 2147483647))
        substitutions.setdefault("width", str(options.get("width") or provider.get("width") or 512))
        substitutions.setdefault("height", str(options.get("height") or provider.get("height") or 512))
        workflow = self._replace_placeholders(template, substitutions)
        return {"ok": True, "status": "ready", "workflow": workflow}

    def _replace_placeholders(self, value: Any, substitutions: dict[str, Any]) -> Any:
        if isinstance(value, str):
            rendered = value
            for key, replacement in substitutions.items():
                rendered = rendered.replace("{" + str(key) + "}", str(replacement))
            return rendered
        if isinstance(value, list):
            return [self._replace_placeholders(item, substitutions) for item in value]
        if isinstance(value, dict):
            return {key: self._replace_placeholders(item, substitutions) for key, item in value.items()}
        return value

    def _comfy_post_json(self, endpoint: str, path: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
        req = urllib.request.Request(endpoint.rstrip("/") + path, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def _wait_comfy_history(self, *, endpoint: str, prompt_id: str, timeout: float) -> dict[str, Any]:
        deadline = time.time() + timeout
        url = endpoint.rstrip("/") + "/history/" + urllib.parse.quote(prompt_id)
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(url, timeout=10) as response:
                    data = json.loads(response.read().decode("utf-8"))
                if prompt_id in data:
                    return {"ok": True, "status": "completed", "history": data[prompt_id]}
            except Exception:
                pass
            time.sleep(2)
        return {"ok": False, "status": "failed", "reason": "generation_timeout", "prompt_id": prompt_id}

    def _extract_comfy_image(self, *, endpoint: str, history: dict[str, Any], target_dir: Path) -> dict[str, Any]:
        outputs = history.get("outputs") if isinstance(history.get("outputs"), dict) else {}
        for output in outputs.values():
            images = output.get("images") if isinstance(output, dict) else None
            if not isinstance(images, list):
                continue
            for item in images:
                if not isinstance(item, dict):
                    continue
                filename = str(item.get("filename") or "").strip()
                if not filename:
                    continue
                params = urllib.parse.urlencode({
                    "filename": filename,
                    "subfolder": str(item.get("subfolder") or ""),
                    "type": str(item.get("type") or "output"),
                })
                with urllib.request.urlopen(endpoint.rstrip("/") + "/view?" + params, timeout=60) as response:
                    data = response.read()
                target_dir.mkdir(parents=True, exist_ok=True)
                suffix = Path(filename).suffix or ".png"
                target = target_dir / f"comfyui_output_{uuid4().hex[:8]}{suffix}"
                target.write_bytes(data)
                return {"ok": True, "status": "completed", "file_path": str(target)}
        return {"ok": False, "status": "failed", "reason": "no_image_output"}

    def _call_python_function(self, provider: dict[str, Any], prompt: str, options: dict[str, Any]) -> dict[str, Any]:
        target = str(provider.get("callable") or provider.get("function") or "").strip()
        if not target or ":" not in target:
            return {"ok": False, "status": "requires_setup", "reason": "missing_callable"}
        module_name, func_name = target.split(":", 1)
        try:
            func = getattr(importlib.import_module(module_name), func_name)
            result = func(prompt=prompt, options=options, provider=provider)
            return self._normalize_provider_result(result)
        except Exception as exc:
            return {
                "ok": False,
                "status": "failed",
                "reason": "python_function_provider_failed",
                "error_type": exc.__class__.__name__,
                "error": str(exc)[-1000:],
                "callable": target,
            }

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
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                raw = response.read()
        except Exception as exc:
            return {"ok": False, "status": "failed", "reason": "provider_request_failed", "endpoint": endpoint, "error": str(exc)[-1000:]}
        try:
            data = json.loads(raw.decode("utf-8"))
        except Exception:
            data = {"image_bytes": base64.b64encode(raw).decode("ascii")}
        return self._normalize_provider_result(data, provider=provider)

    def _render_payload(self, *, provider: dict[str, Any], prompt: str, options: dict[str, Any]) -> dict[str, Any]:
        template = provider.get("request_template") if isinstance(provider.get("request_template"), dict) else {}
        if not template:
            template = {"prompt": "{prompt}"}
        rendered = json.loads(json.dumps(template))

        replacements = {"prompt": prompt}
        for key in ("model", "size", "quality", "style", "width", "height"):
            value = options.get(key, provider.get(key))
            if value is not None:
                replacements[key] = str(value)

        def walk(value: Any) -> Any:
            if isinstance(value, str):
                out = value
                for key, replacement in replacements.items():
                    out = out.replace("{" + key + "}", replacement)
                return out
            if isinstance(value, list):
                return [walk(x) for x in value]
            if isinstance(value, dict):
                return {k: walk(v) for k, v in value.items()}
            return value

        payload = walk(rendered)
        if isinstance(options.get("request_overrides"), dict):
            payload.update(options["request_overrides"])
        return payload

    def _normalize_provider_result(self, result: Any, provider: dict[str, Any] | None = None) -> dict[str, Any]:
        provider = provider if isinstance(provider, dict) else {}
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
                normalized = self._normalize_provider_result(item, provider=provider)
                if normalized.get("ok"):
                    return normalized
        if result.get("url"):
            if bool(provider.get("download_remote_url", True)):
                downloaded = self._download_remote_image(str(result.get("url") or ""), timeout=float(provider.get("download_timeout_seconds") or 180))
                if downloaded.get("ok"):
                    return downloaded
            return {"ok": False, "status": "requires_setup", "reason": "remote_url_download_not_configured"}
        return {"ok": False, "status": str(result.get("status") or "failed"), "reason": str(result.get("reason") or "no_image_material")}


    def _download_remote_image(self, url: str, *, timeout: float) -> dict[str, Any]:
        if not url.strip():
            return {"ok": False, "status": "failed", "reason": "empty_remote_url"}
        temp_dir = self._provider_temp_dir("remote_image")
        parsed = urllib.parse.urlparse(url)
        suffix = Path(parsed.path).suffix.lower()
        if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
            suffix = ".png"
        target = temp_dir / f"remote_{uuid4().hex[:12]}{suffix}"
        try:
            with urllib.request.urlopen(url, timeout=timeout) as response:
                target.write_bytes(response.read())
        except Exception as exc:
            return {"ok": False, "status": "failed", "reason": "remote_url_download_failed", "error": str(exc)[-1000:]}
        if target.stat().st_size <= 0:
            return {"ok": False, "status": "failed", "reason": "remote_url_empty_file"}
        return {"ok": True, "status": "completed", "file_path": str(target)}

    def _metrics_path(self) -> Path:
        path = RUNTIME_DIR / "generated" / "media" / "image_generation_metrics.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def _record_execution_event(self, *, result: dict[str, Any], duration_seconds: float, attempted: list[dict[str, Any]]) -> None:
        try:
            material = result.get("material") if isinstance(result.get("material"), dict) else {}
            provider = str(material.get("provider") or "").strip()
            if not provider and attempted:
                provider = str(attempted[-1].get("provider") or "").strip()
            event = {
                "event_type": "capability_execution_metric",
                "capability_type": "image_generation",
                "provider": provider,
                "ok": bool(result.get("ok")),
                "status": str(result.get("status") or ""),
                "duration_seconds": round(float(duration_seconds), 3),
                "attempted": attempted[-5:] if isinstance(attempted, list) else [],
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
            with self._metrics_path().open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(event, ensure_ascii=False) + "\n")
        except Exception:
            return

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
