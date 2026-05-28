from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import shutil
import subprocess
import time
import traceback
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any
from uuid import uuid4

from ai_core.config.paths import CONFIGS_DIR, RUNTIME_CONFIGS, RUNTIME_DIR, RUNTIME_DOWNLOADS, RUNTIME_GENERATED
from ai_core.dependencies import RuntimeDependencyInstaller
from ai_core.media.image_generation_service import ImageGenerationService
from ai_core.secrets.secret_store import SecretStore


class VideoGenerationService(ImageGenerationService):
    """Provider-routed video generation capability.

    This keeps ai_core generic: the core knows only modality/capability routing,
    provider protocols, and artifact contracts. Concrete animation/video behavior
    is supplied by runtime configuration, generated provider records, workflows,
    commands, or external endpoints.
    """

    capability_type = "video_generation"

    async def generate(self, *, prompt: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
        start_time = time.time()
        prompt = str(prompt or "").strip()
        options = options if isinstance(options, dict) else {}
        attempted: list[dict[str, Any]] = []
        stage_meta: dict[str, Any] = {}
        route: list[str] = []
        providers: dict[str, Any] = {}

        try:
            if not prompt:
                result = {"ok": False, "status": "requires_input", "missing_inputs": ["prompt"]}
                self._record_execution_event(result=result, duration_seconds=time.time() - start_time, attempted=attempted)
                self._record_diagnostic_event(
                    level="info",
                    reason="missing_prompt",
                    result=result,
                    attempted=attempted,
                    duration_seconds=time.time() - start_time,
                )
                return result

            config = self._provider_config()
            route, providers, stage_meta = self._route(config=config, options=options)
            self._record_diagnostic_event(
                level="debug",
                reason="video_generation_route_selected",
                result={"ok": False, "status": "routing", "route": route, "provider_count": len(providers)},
                attempted=attempted,
                duration_seconds=time.time() - start_time,
            )

            for provider_name in route:
                provider = dict(providers.get(provider_name, {}) or {})
                if not provider.get("enabled", True):
                    attempted.append({"provider": provider_name, "status": "skipped", "reason": "disabled"})
                    continue
                if not self._media_provider_allowed(provider_name, provider):
                    attempted.append({"provider": provider_name, "status": "skipped", "reason": "not_allowed_by_runtime_source_policy"})
                    continue
                try:
                    result = await self._call_provider_with_dependency_recovery(provider_name=provider_name, provider=provider, prompt=prompt, options=options)
                except Exception as exc:
                    result = {
                        "ok": False,
                        "status": "failed",
                        "reason": "provider_exception",
                        "error_type": exc.__class__.__name__,
                        "error": str(exc)[-1000:],
                        "traceback": traceback.format_exc(limit=8),
                    }
                attempt = self._attempt_record(provider_name=provider_name, result=result)
                attempted.append(attempt)
                self._record_diagnostic_event(
                    level="info",
                    reason=str(result.get("reason") or result.get("status") or "provider_result"),
                    result=result,
                    attempted=[attempt],
                    duration_seconds=time.time() - start_time,
                )
                if result.get("ok"):
                    try:
                        material = self._persist_video(result, provider_name=provider_name, stage_meta=stage_meta)
                    except Exception as exc:
                        persist_attempt = {
                            "provider": provider_name,
                            "status": "failed",
                            "reason": "artifact_persist_failed",
                            "error_type": exc.__class__.__name__,
                            "error": str(exc)[-1000:],
                            "traceback": traceback.format_exc(limit=8),
                        }
                        attempted.append(persist_attempt)
                        self._record_diagnostic_event(
                            level="error",
                            reason="artifact_persist_failed",
                            result=persist_attempt,
                            attempted=attempted,
                            duration_seconds=time.time() - start_time,
                        )
                        continue
                    final = {"ok": True, "status": "completed", "material": material, "attempted": attempted, "stage_policy": stage_meta}
                    self._record_execution_event(result=final, duration_seconds=time.time() - start_time, attempted=attempted)
                    self._record_diagnostic_event(
                        level="info",
                        reason="completed",
                        result=final,
                        attempted=attempted,
                        duration_seconds=time.time() - start_time,
                    )
                    return final

            final = {
                "ok": False,
                "status": "requires_setup",
                "message": self._setup_message(attempted),
                "attempted": attempted,
                "setup_actions": self._setup_actions(route=route, providers=providers, attempted=attempted),
                "interaction_request": self._first_missing_secret_action(attempted),
                "stage_policy": stage_meta,
            }
            self._record_execution_event(result=final, duration_seconds=time.time() - start_time, attempted=attempted)
            self._record_diagnostic_event(
                level="warning",
                reason="requires_setup",
                result=final,
                attempted=attempted,
                duration_seconds=time.time() - start_time,
            )
            return final

        except Exception as exc:
            final = {
                "ok": False,
                "status": "failed",
                "reason": "video_generation_unhandled_exception",
                "error_type": exc.__class__.__name__,
                "error": str(exc)[-1000:],
                "traceback": traceback.format_exc(limit=12),
                "attempted": attempted,
                "stage_policy": stage_meta,
            }
            self._record_execution_event(result=final, duration_seconds=time.time() - start_time, attempted=attempted)
            self._record_diagnostic_event(
                level="error",
                reason="video_generation_unhandled_exception",
                result=final,
                attempted=attempted,
                duration_seconds=time.time() - start_time,
            )
            return final

    def _provider_config(self) -> dict[str, Any]:
        self._ensure_runtime_video_config()
        # Video generation is a media artifact capability, not a text model
        # stage.  Do not start from runtime/configs/models/providers.yaml here,
        # because generic LLM providers such as ollama/vllm may be injected by
        # stage policy and later reported as unsupported video providers.
        # Runtime video providers are loaded only from the media capability
        # seed/override files.
        return self._video_seed_config()

    def _ensure_runtime_video_config(self) -> None:
        media_dir = RUNTIME_CONFIGS / "media"
        media_dir.mkdir(parents=True, exist_ok=True)
        runtime_path = media_dir / "video_generation.yaml"
        seed_path = CONFIGS_DIR / "video_generation.seed.yaml"
        if seed_path.exists() and not runtime_path.exists():
            shutil.copyfile(seed_path, runtime_path)

        # ComfyUI video model/custom-node dependencies live in runtime config,
        # not in ai_core logic.  The seed is only a manifest contract and can be
        # replaced by runtime-generated or user-provided manifests.
        manifest_runtime = media_dir / "video_model_dependency_manifest.yaml"
        manifest_seed = CONFIGS_DIR / "video_model_dependency_manifest.seed.yaml"
        if manifest_seed.exists() and not manifest_runtime.exists():
            shutil.copyfile(manifest_seed, manifest_runtime)

    def _video_seed_config(self) -> dict[str, Any]:
        merged: dict[str, Any] = {}
        for path in [CONFIGS_DIR / "video_generation.seed.yaml", RUNTIME_CONFIGS / "media" / "video_generation.yaml"]:
            data = self.loader.load_yaml(path)
            if not isinstance(data, dict) or not data:
                continue
            merged = self._merge_provider_config(merged, data)
        return merged

    def _route(self, *, config: dict[str, Any], options: dict[str, Any]) -> tuple[list[str], dict[str, Any], dict[str, Any]]:
        providers = dict(config.get("providers") or {})
        base_route = list(config.get("default_route") or [])
        requested_route = list(options.get("provider_route") or base_route)
        config2, route, meta = self.stage_policy.apply_to_route(
            config=config,
            route=requested_route,
            node_id="video_generation",
            adapter={"model_stage": "video_generation", "preferred_local_model": options.get("preferred_local_model")},
            route_name="video_generation",
            escalated=bool(options.get("force_external")),
        )
        providers = dict(config2.get("providers") or providers)

        # Keep the stage policy useful for ordering/escalation, but isolate this
        # artifact route from normal LLM providers. Only providers whose records
        # explicitly advertise video generation are allowed into the executable
        # route. This prevents messages such as "ollama: unsupported_provider_protocol"
        # for text-only model providers.
        raw_route = self.execution_policy.snapshot(provider_config=config2).filter_route(route or requested_route, providers)
        media_route = [
            name for name in raw_route
            if self._provider_can_generate_video(providers.get(name) if isinstance(providers.get(name), dict) else {})
            and self._media_provider_allowed(name, providers.get(name) if isinstance(providers.get(name), dict) else {})
        ]
        if not media_route:
            media_route = [
                name for name in requested_route
                if self._provider_can_generate_video(providers.get(name) if isinstance(providers.get(name), dict) else {})
                and self._media_provider_allowed(name, providers.get(name) if isinstance(providers.get(name), dict) else {})
            ]
        for name, provider in providers.items():
            if name not in media_route and self._provider_can_generate_video(provider) and self._media_provider_allowed(name, provider):
                media_route.append(name)
        selected_provider = str(options.get("selected_provider") or "").strip()
        if selected_provider and selected_provider in providers and self._provider_can_generate_video(providers.get(selected_provider) or {}):
            media_route = [selected_provider] + [item for item in media_route if item != selected_provider]
        else:
            media_route = self._rank_route_by_observations(media_route, providers)
        meta = dict(meta or {})
        meta["route_isolated_to_capability"] = "video_generation"
        return media_route, providers, meta

    def _provider_can_generate_video(self, provider: dict[str, Any]) -> bool:
        if not isinstance(provider, dict):
            return False
        protocol = str(provider.get("protocol") or provider.get("type") or "").strip()
        supported_protocols = {
            "comfyui",
            "comfyui_runtime",
            "local_comfyui",
            "python_function",
            "function",
            "local_command",
            "command",
            "generic_http_json",
            "openai_compatible_api",
            "openai_compatible_video",
            "http_json",
            "video_generation_http",
        }
        endpoint = bool(provider.get("video_generation_endpoint") or provider.get("video_endpoint"))
        if protocol not in supported_protocols and not endpoint:
            return False
        text = " ".join(str(provider.get(k) or "") for k in ("type", "protocol", "role"))
        caps = " ".join(str(x) for x in provider.get("capabilities", []) or [])
        modalities = json.dumps(provider.get("modalities") or {}, ensure_ascii=False)
        return "video_generation" in f"{text} {caps} {modalities}" or endpoint


    async def _call_provider_with_dependency_recovery(self, *, provider_name: str, provider: dict[str, Any], prompt: str, options: dict[str, Any]) -> dict[str, Any]:
        installer = RuntimeDependencyInstaller()
        declared_results = installer.install_declared_dependencies(provider)
        try:
            result = await self._call_provider(provider_name=provider_name, provider=provider, prompt=prompt, options=options)
            if declared_results:
                result = dict(result)
                result.setdefault("dependency_recovery", declared_results)
            return result
        except (ModuleNotFoundError, ImportError) as exc:
            missing = installer.missing_import_from_exception(exc)
            install_result = installer.install_for_missing_import(missing, provider=provider)
            if not install_result.get("ok"):
                return {
                    "ok": False,
                    "status": install_result.get("status") or "requires_setup",
                    "reason": "python_dependency_missing",
                    "missing_import": missing,
                    "dependency_install": install_result,
                    "dependency_recovery": declared_results,
                    "error_type": exc.__class__.__name__,
                    "error": str(exc)[-1000:],
                }
            result = await self._call_provider(provider_name=provider_name, provider=provider, prompt=prompt, options=options)
            result = dict(result)
            recovery = list(declared_results)
            recovery.append(install_result)
            result["dependency_recovery"] = recovery
            return result

    async def _call_provider(self, *, provider_name: str, provider: dict[str, Any], prompt: str, options: dict[str, Any]) -> dict[str, Any]:
        protocol = str(provider.get("protocol") or provider.get("type") or "").strip()
        if protocol in {"comfyui", "comfyui_runtime", "local_comfyui"}:
            return await asyncio.to_thread(self._call_comfyui_video, provider_name, provider, prompt, options)
        if protocol in {"python_function", "function"}:
            return await asyncio.to_thread(self._call_python_function, provider, prompt, options)
        if protocol in {"local_command", "command"}:
            return await asyncio.to_thread(self._call_local_command, provider, prompt, options)
        if protocol in {"generic_http_json", "openai_compatible_api", "openai_compatible_video", "http_json", "video_generation_http"} or provider.get("video_generation_endpoint") or provider.get("video_endpoint"):
            return await asyncio.to_thread(self._call_http_json, provider_name, provider, prompt, options)
        return {"ok": False, "status": "requires_setup", "reason": "unsupported_provider_protocol"}

    def _call_comfyui_video(self, provider_name: str, provider: dict[str, Any], prompt: str, options: dict[str, Any]) -> dict[str, Any]:
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
        video = self._extract_comfy_video(endpoint=endpoint, history=history["history"], target_dir=self._provider_temp_dir(provider_name))
        if not video.get("ok"):
            return video
        return {"ok": True, "status": "completed", "file_path": video["file_path"], "provider_response": {"prompt_id": prompt_id}}

    def _extract_comfy_video(self, *, endpoint: str, history: dict[str, Any], target_dir: Path) -> dict[str, Any]:
        outputs = history.get("outputs") if isinstance(history.get("outputs"), dict) else {}
        media_keys = ("videos", "video", "gifs", "animated", "animations", "files", "images")
        valid_suffixes = {".mp4", ".webm", ".gif", ".mov", ".mkv"}
        for output in outputs.values():
            if not isinstance(output, dict):
                continue
            for key in media_keys:
                items = output.get(key)
                if isinstance(items, dict):
                    items = [items]
                if not isinstance(items, list):
                    continue
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    filename = str(item.get("filename") or "").strip()
                    if not filename:
                        continue
                    suffix = Path(filename).suffix.lower()
                    if suffix not in valid_suffixes:
                        continue
                    params = urllib.parse.urlencode({
                        "filename": filename,
                        "subfolder": str(item.get("subfolder") or ""),
                        "type": str(item.get("type") or "output"),
                    })
                    with urllib.request.urlopen(endpoint.rstrip("/") + "/view?" + params, timeout=180) as response:
                        data = response.read()
                    target_dir.mkdir(parents=True, exist_ok=True)
                    target = target_dir / f"comfyui_video_{uuid4().hex[:8]}{suffix}"
                    target.write_bytes(data)
                    return {"ok": True, "status": "completed", "file_path": str(target)}
        return {"ok": False, "status": "failed", "reason": "no_video_output"}

    def _render_workflow(self, *, provider: dict[str, Any], runtime: dict[str, Any], prompt: str, options: dict[str, Any]) -> dict[str, Any]:
        provider_for_render = self._provider_with_video_workflow_values(provider=provider, prompt=prompt, options=options)
        rendered = super()._render_workflow(provider=provider_for_render, runtime=runtime, prompt=prompt, options=options)
        if rendered.get("ok") or rendered.get("reason") != "workflow_template_missing":
            return rendered
        boot = self._bootstrap_video_workflow_template(provider=provider, runtime=runtime)
        if not boot.get("ok"):
            return {
                "ok": False,
                "status": "requires_setup",
                "reason": str(boot.get("reason") or "workflow_template_bootstrap_failed"),
                "bootstrap": boot,
            }
        provider2 = dict(provider_for_render)
        provider2["workflow_template"] = str(boot.get("workflow_template"))
        return super()._render_workflow(provider=provider2, runtime=runtime, prompt=prompt, options=options)

    def _provider_with_video_workflow_values(self, *, provider: dict[str, Any], prompt: str, options: dict[str, Any]) -> dict[str, Any]:
        provider2 = dict(provider)
        values = dict(provider.get("workflow_values") if isinstance(provider.get("workflow_values"), dict) else {})
        frame_count = options.get("frame_count") or options.get("frames") or provider.get("frame_count") or provider.get("frames") or 16
        replacements = {
            "prompt": prompt,
            "PROMPT": prompt,
            "negative_prompt": str(options.get("negative_prompt") or provider.get("negative_prompt") or ""),
            "NEGATIVE_PROMPT": str(options.get("negative_prompt") or provider.get("negative_prompt") or ""),
            "frame_count": str(frame_count),
            "FRAME_COUNT": str(frame_count),
            "width": str(options.get("width") or provider.get("width") or 512),
            "WIDTH": str(options.get("width") or provider.get("width") or 512),
            "height": str(options.get("height") or provider.get("height") or 512),
            "HEIGHT": str(options.get("height") or provider.get("height") or 512),
            "seed": str(options.get("seed") or provider.get("seed") or int(time.time()) % 2147483647),
            "SEED": str(options.get("seed") or provider.get("seed") or int(time.time()) % 2147483647),
        }
        values.update(replacements)
        provider2["workflow_values"] = values
        return provider2

    def _bootstrap_video_workflow_template(self, *, provider: dict[str, Any], runtime: dict[str, Any]) -> dict[str, Any]:
        """Resolve/download a ComfyUI video workflow template using runtime config.

        The core remains generic: it does not know AnimateDiff, model names, or
        a fixed workflow. Runtime configuration supplies either a URL, repository,
        file path, or discovery directories. Missing values are surfaced as setup
        actions so the UI can collect them without falling back to chat.
        """
        bootstrap = provider.get("workflow_bootstrap") if isinstance(provider.get("workflow_bootstrap"), dict) else {}
        runtime_bootstrap = runtime.get("workflow_bootstrap") if isinstance(runtime.get("workflow_bootstrap"), dict) else {}
        cfg = {**runtime_bootstrap, **bootstrap}
        if cfg and cfg.get("enabled") is False:
            return {"ok": False, "status": "requires_setup", "reason": "workflow_template_missing"}
        target_dir = self._workflow_template_target_dir(cfg)
        target_dir.mkdir(parents=True, exist_ok=True)

        discovered = self._discover_existing_workflow_template(provider=provider, runtime=runtime, cfg=cfg, target_dir=target_dir)
        if discovered.get("ok"):
            return discovered

        downloaded = self._download_workflow_template_from_config(provider=provider, runtime=runtime, cfg=cfg, target_dir=target_dir)
        if downloaded.get("ok"):
            return downloaded

        cloned = self._clone_workflow_template_repo(provider=provider, runtime=runtime, cfg=cfg, target_dir=target_dir)
        if cloned.get("ok"):
            return cloned
        if cloned.get("reason") and cloned.get("reason") != "workflow_repository_source_missing":
            return cloned

        return {
            "ok": False,
            "status": "requires_setup",
            "reason": downloaded.get("reason") or "workflow_template_source_missing",
            "expected_inputs": [
                "AI_CORE_VIDEO_WORKFLOW_TEMPLATE_URL",
                "AI_CORE_VIDEO_WORKFLOW_TEMPLATE_REPOSITORY",
                "AI_CORE_VIDEO_WORKFLOW_TEMPLATE_FILE",
            ],
            "target_dir": str(target_dir),
        }

    def _workflow_template_target_dir(self, cfg: dict[str, Any]) -> Path:
        configured = self._resolve_config_value(str(cfg.get("target_dir") or "").strip())
        if configured:
            raw = Path(configured).expanduser()
            return raw.resolve() if raw.is_absolute() else (CONFIGS_DIR.parent / raw).resolve()
        return (RUNTIME_GENERATED / "workflow_templates" / "video_generation").resolve()

    def _discover_existing_workflow_template(self, *, provider: dict[str, Any], runtime: dict[str, Any], cfg: dict[str, Any], target_dir: Path) -> dict[str, Any]:
        explicit_file = self._resolve_config_value(str(cfg.get("file") or cfg.get("workflow_template_file") or os.getenv(str(cfg.get("file_env") or "AI_CORE_VIDEO_WORKFLOW_TEMPLATE_FILE"), "") or "").strip())
        candidates: list[Path] = []
        if explicit_file:
            candidates.append(Path(explicit_file).expanduser())
        candidates.extend(sorted(target_dir.glob("*.json")))
        raw_dirs = cfg.get("search_dirs") if isinstance(cfg.get("search_dirs"), list) else []
        for item in raw_dirs:
            d = self._resolve_config_value(str(item or "").strip())
            if d:
                candidates.extend(sorted(Path(d).expanduser().glob("**/*.json"))[:50])
        root = self._resolve_runtime_root(runtime)
        for rel in ["workflows", "user/default/workflows", "custom_nodes"]:
            d = root / rel
            if d.exists():
                candidates.extend(sorted(d.glob("**/*.json"))[:50])
        for candidate in candidates:
            try:
                path = candidate.expanduser().resolve()
                if not path.exists() or path.suffix.lower() != ".json":
                    continue
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return {"ok": True, "status": "ready", "workflow_template": str(path), "source": "discovered"}
            except Exception:
                continue
        return {"ok": False, "status": "requires_setup", "reason": "workflow_template_not_discovered"}

    def _download_workflow_template_from_config(self, *, provider: dict[str, Any], runtime: dict[str, Any], cfg: dict[str, Any], target_dir: Path) -> dict[str, Any]:
        urls: list[str] = []
        raw_urls = cfg.get("urls") or provider.get("workflow_template_urls") or runtime.get("workflow_template_urls")
        if isinstance(raw_urls, list):
            urls.extend(str(x).strip() for x in raw_urls if str(x).strip())
        for key in ["url", "workflow_template_url"]:
            value = str(cfg.get(key) or provider.get(key) or runtime.get(key) or "").strip()
            if value:
                urls.append(value)
        env_name = str(cfg.get("url_env") or "AI_CORE_VIDEO_WORKFLOW_TEMPLATE_URL").strip()
        env_value = os.getenv(env_name, "").strip() if env_name else ""
        if env_value:
            urls.insert(0, env_value)
        urls = [self._resolve_config_value(x) for x in urls]
        urls = [x for x in urls if x]
        if not urls:
            return {"ok": False, "status": "requires_setup", "reason": "workflow_template_source_missing", "env": env_name}
        last_error = ""
        for idx, url in enumerate(urls):
            try:
                parsed = urllib.parse.urlparse(url)
                suffix = Path(parsed.path).suffix.lower() or ".json"
                target = target_dir / f"video_workflow_{idx}{suffix}"
                self._download_file(url=url, target=target, timeout=float(cfg.get("download_timeout_seconds") or 600))
                json.loads(target.read_text(encoding="utf-8"))
                return {"ok": True, "status": "downloaded", "workflow_template": str(target), "source_url": self._redact_url(url)}
            except Exception as exc:
                last_error = str(exc)[-1000:]
                continue
        return {"ok": False, "status": "requires_setup", "reason": "workflow_template_download_failed", "error": last_error}

    def _clone_workflow_template_repo(self, *, provider: dict[str, Any], runtime: dict[str, Any], cfg: dict[str, Any], target_dir: Path) -> dict[str, Any]:
        repo = self._resolve_config_value(str(cfg.get("repository") or os.getenv(str(cfg.get("repository_env") or "AI_CORE_VIDEO_WORKFLOW_TEMPLATE_REPOSITORY"), "") or "").strip())
        if not repo:
            return {"ok": False, "status": "requires_setup", "reason": "workflow_repository_source_missing"}
        git = shutil.which("git")
        if not git:
            return {"ok": False, "status": "requires_setup", "reason": "git_not_available"}
        repo_dir = target_dir / "workflow_repo"
        if not repo_dir.exists():
            proc = subprocess.run([git, "clone", "--depth", "1", repo, str(repo_dir)], text=True, capture_output=True, timeout=float(cfg.get("clone_timeout_seconds") or 600))
            if proc.returncode != 0:
                return {"ok": False, "status": "requires_setup", "reason": "workflow_repository_clone_failed", "stderr": proc.stderr[-1000:]}
        pattern = str(cfg.get("repository_file") or os.getenv(str(cfg.get("repository_file_env") or "AI_CORE_VIDEO_WORKFLOW_TEMPLATE_REPOSITORY_FILE"), "") or "**/*.json")
        for candidate in sorted(repo_dir.glob(pattern))[:100]:
            try:
                data = json.loads(candidate.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return {"ok": True, "status": "downloaded", "workflow_template": str(candidate), "source_repository": self._redact_url(repo)}
            except Exception:
                continue
        return {"ok": False, "status": "requires_setup", "reason": "workflow_repository_no_json_template", "repository": self._redact_url(repo)}

    def _ensure_model_assets(self, *, provider: dict[str, Any], runtime: dict[str, Any]) -> dict[str, Any]:
        """Ensure model assets and custom nodes described by runtime manifest.

        Video workflows are not hard-coded in ai_core.  Runtime configuration may
        provide a model dependency manifest with model files, custom node repos,
        and optional Python package steps.  This method resolves that manifest,
        downloads missing model files, prepares custom nodes, and then delegates
        to the generic media asset checker for the final model file validation.
        """
        manifest = self._load_video_model_dependency_manifest(provider=provider, runtime=runtime)
        if manifest.get("status") == "invalid":
            return manifest
        custom_nodes = manifest.get("custom_nodes") if isinstance(manifest.get("custom_nodes"), list) else []
        custom_ready = self._ensure_comfyui_custom_nodes(custom_nodes=custom_nodes, runtime=runtime, manifest=manifest)
        if not custom_ready.get("ok"):
            return custom_ready

        provider2 = dict(provider)
        runtime2 = dict(runtime)
        provider_assets = provider.get("model_assets") if isinstance(provider.get("model_assets"), list) else []
        runtime_assets = runtime.get("model_assets") if isinstance(runtime.get("model_assets"), list) else []
        manifest_assets = manifest.get("model_assets") if isinstance(manifest.get("model_assets"), list) else []
        merged_assets = [self._normalize_manifest_asset(x) for x in (list(provider_assets) + list(runtime_assets) + list(manifest_assets)) if isinstance(x, dict)]
        provider2["model_assets"] = merged_assets
        result = super()._ensure_model_assets(provider=provider2, runtime=runtime2)
        if result.get("ok"):
            result = dict(result)
            result["dependency_manifest"] = {
                "profile": manifest.get("profile"),
                "manifest_path": manifest.get("manifest_path"),
                "model_asset_count": len(manifest_assets),
                "custom_node_count": len(custom_nodes),
                "custom_nodes": custom_ready.get("custom_nodes", []),
            }
        return result

    def _load_video_model_dependency_manifest(self, *, provider: dict[str, Any], runtime: dict[str, Any]) -> dict[str, Any]:
        manifest_cfg = provider.get("model_dependency_manifest") if isinstance(provider.get("model_dependency_manifest"), dict) else {}
        runtime_cfg = runtime.get("model_dependency_manifest") if isinstance(runtime.get("model_dependency_manifest"), dict) else {}
        cfg = {**runtime_cfg, **manifest_cfg}
        if cfg and cfg.get("enabled") is False:
            return {"ok": True, "status": "ready", "profile": "disabled", "model_assets": [], "custom_nodes": []}

        profile = str(cfg.get("profile") or provider.get("model_dependency_profile") or runtime.get("model_dependency_profile") or "text_to_video").strip()
        manifest_path = self._resolve_config_value(str(cfg.get("manifest_file") or cfg.get("path") or "runtime/configs/media/video_model_dependency_manifest.yaml").strip())
        if manifest_path:
            raw_path = Path(manifest_path).expanduser()
            path = raw_path.resolve() if raw_path.is_absolute() else (CONFIGS_DIR.parent / raw_path).resolve()
        else:
            path = (RUNTIME_CONFIGS / "media" / "video_model_dependency_manifest.yaml").resolve()
        if not path.exists():
            seed = CONFIGS_DIR / "video_model_dependency_manifest.seed.yaml"
            if seed.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(seed, path)
        data = self.loader.load_yaml(path)
        if not isinstance(data, dict):
            return {"ok": False, "status": "invalid", "reason": "invalid_model_dependency_manifest", "manifest_path": str(path)}
        profiles = data.get("profiles") if isinstance(data.get("profiles"), dict) else {}
        selected = profiles.get(profile) if isinstance(profiles.get(profile), dict) else {}
        if not selected and profiles:
            # Keep execution generic: fallback to the first configured profile
            # instead of knowing model/workflow names in code.
            first_name, first_profile = next(iter(profiles.items()))
            profile = str(first_name)
            selected = first_profile if isinstance(first_profile, dict) else {}
        root_items = {
            "model_assets": data.get("model_assets") if isinstance(data.get("model_assets"), list) else [],
            "custom_nodes": data.get("custom_nodes") if isinstance(data.get("custom_nodes"), list) else [],
            "python_packages": data.get("python_packages") if isinstance(data.get("python_packages"), list) else [],
        }
        selected_assets = selected.get("model_assets") if isinstance(selected.get("model_assets"), list) else []
        selected_nodes = selected.get("custom_nodes") if isinstance(selected.get("custom_nodes"), list) else []
        selected_packages = selected.get("python_packages") if isinstance(selected.get("python_packages"), list) else []
        return {
            "ok": True,
            "status": "ready",
            "profile": profile,
            "manifest_path": str(path),
            "model_assets": list(root_items["model_assets"]) + list(selected_assets),
            "custom_nodes": list(root_items["custom_nodes"]) + list(selected_nodes),
            "python_packages": list(root_items["python_packages"]) + list(selected_packages),
            "raw": data,
        }

    def _normalize_manifest_asset(self, asset: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(asset)
        for env_key, value_key in [("url_env", "url"), ("source_url_env", "source_url"), ("target_env", "target")]:
            env_name = str(normalized.get(env_key) or "").strip()
            if env_name and not normalized.get(value_key):
                env_value = os.getenv(env_name, "").strip()
                if env_value:
                    normalized[value_key] = env_value
        if normalized.get("source_url") and not normalized.get("url"):
            normalized["url"] = normalized.get("source_url")
        return normalized

    def _ensure_comfyui_custom_nodes(self, *, custom_nodes: list[Any], runtime: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
        if not custom_nodes:
            return {"ok": True, "status": "ready", "custom_nodes": []}
        root = self._resolve_runtime_root(runtime)
        nodes_root = root / "custom_nodes"
        nodes_root.mkdir(parents=True, exist_ok=True)
        ready: list[dict[str, Any]] = []
        git = shutil.which("git")
        for item in custom_nodes:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or item.get("id") or "custom_node").strip()
            target_name = str(item.get("target_dir") or name or "custom_node").strip().replace("/", "_").replace("\\", "_")
            target = (nodes_root / target_name).resolve()
            if target.exists():
                ready.append({"name": name, "target": str(target), "status": "exists"})
                continue
            if not bool(item.get("auto_install", True)):
                return {"ok": False, "status": "requires_setup", "reason": "custom_node_missing", "name": name, "target": str(target)}
            repo = self._resolve_config_value(str(item.get("repository") or item.get("repo") or item.get("url") or "").strip())
            env_name = str(item.get("repository_env") or item.get("url_env") or "").strip()
            if env_name and not repo:
                repo = self._resolve_config_value(os.getenv(env_name, ""))
            if not repo:
                return {"ok": False, "status": "requires_setup", "reason": "custom_node_repository_missing", "name": name, "env_hint": env_name}
            if not git:
                return {"ok": False, "status": "requires_setup", "reason": "git_not_available", "name": name}
            try:
                proc = subprocess.run([git, "clone", "--depth", "1", repo, str(target)], text=True, capture_output=True, timeout=float(item.get("clone_timeout_seconds") or 900))
                if proc.returncode != 0:
                    return {"ok": False, "status": "requires_setup", "reason": "custom_node_clone_failed", "name": name, "stderr": proc.stderr[-1000:]}
                if bool(item.get("install_requirements", True)):
                    req = target / "requirements.txt"
                    if req.exists():
                        py = self._runtime_python(root=root, runtime=runtime, install=(runtime.get("install") if isinstance(runtime.get("install"), dict) else {}))
                        pip = subprocess.run([py, "-m", "pip", "install", "-r", str(req)], text=True, capture_output=True, timeout=float(item.get("pip_timeout_seconds") or 1800))
                        if pip.returncode != 0:
                            return {"ok": False, "status": "requires_setup", "reason": "custom_node_requirements_install_failed", "name": name, "stderr": pip.stderr[-1000:]}
                ready.append({"name": name, "target": str(target), "status": "installed"})
            except Exception as exc:
                return {"ok": False, "status": "requires_setup", "reason": "custom_node_install_failed", "name": name, "error": str(exc)[-1000:]}
        package_result = self._install_manifest_python_packages(packages=manifest.get("python_packages") or [], runtime=runtime)
        if not package_result.get("ok"):
            return package_result
        return {"ok": True, "status": "ready", "custom_nodes": ready, "python_packages": package_result.get("packages", [])}

    def _install_manifest_python_packages(self, *, packages: list[Any], runtime: dict[str, Any]) -> dict[str, Any]:
        if not packages:
            return {"ok": True, "status": "ready", "packages": []}
        root = self._resolve_runtime_root(runtime)
        py = self._runtime_python(root=root, runtime=runtime, install=(runtime.get("install") if isinstance(runtime.get("install"), dict) else {}))
        ready: list[dict[str, Any]] = []
        for item in packages:
            package = str(item.get("package") if isinstance(item, dict) else item).strip()
            if not package:
                continue
            proc = subprocess.run([py, "-m", "pip", "install", package], text=True, capture_output=True, timeout=float((item.get("timeout_seconds") if isinstance(item, dict) else 1800) or 1800))
            if proc.returncode != 0:
                return {"ok": False, "status": "requires_setup", "reason": "manifest_python_package_install_failed", "package": package, "stderr": proc.stderr[-1000:]}
            ready.append({"package": package, "status": "installed_or_satisfied"})
        return {"ok": True, "status": "ready", "packages": ready}

    def _asset_target(self, *, root: Path, asset: dict[str, Any]) -> Path:
        # Video manifests often describe ComfyUI-relative targets.  Preserve the
        # generic image implementation but also accept env-backed filenames.
        target = self._resolve_config_value(str(asset.get("target") or "").strip())
        if target:
            return Path(target).expanduser().resolve()
        asset2 = dict(asset)
        env_name = str(asset2.get("file_name_env") or asset2.get("filename_env") or "").strip()
        if env_name and not asset2.get("file_name") and not asset2.get("filename"):
            env_value = os.getenv(env_name, "").strip()
            if env_value:
                asset2["file_name"] = env_value
        return super()._asset_target(root=root, asset=asset2)

    def _download_file(self, *, url: str, target: Path, timeout: float) -> None:
        super()._download_file(url=url, target=target, timeout=timeout)
        # Optional manifest checksum validation.  The expected hash is supplied
        # via the caller by writing a sidecar only when configured; ordinary
        # downloads remain unchanged.

    def _provider_secret(self, secret_key: str) -> str:
        key = str(secret_key or "").strip()
        if not key:
            return ""
        value = os.getenv(key, "")
        if value:
            return value
        try:
            return SecretStore().get(key) or ""
        except Exception:
            return ""

    def _missing_secret_interaction(self, *, provider_name: str, secret_key: str) -> dict[str, Any]:
        return {
            "kind": "secret_input",
            "capability_type": "video_generation",
            "provider": provider_name,
            "secret_key": secret_key,
            "message": f"{provider_name} requires {secret_key}. Please enter the key to continue, or choose a local provider.",
            "secret_fields": [
                {
                    "name": secret_key,
                    "secret_key": secret_key,
                    "interaction_type": "secret",
                    "provider": provider_name,
                    "required": True,
                }
            ],
        }

    def _first_missing_secret_action(self, attempted: list[dict[str, Any]]) -> dict[str, Any] | None:
        for item in attempted:
            reason = str(item.get("reason") or "")
            if reason == "missing_secret":
                secret_key = str(item.get("secret_key") or "").strip()
                provider = str(item.get("provider") or "external_video_generation").strip()
                if secret_key:
                    return self._missing_secret_interaction(provider_name=provider, secret_key=secret_key)
            if reason == "missing_endpoint":
                provider = str(item.get("provider") or "external_video_generation").strip()
                return self._missing_endpoint_interaction(provider_name=provider)
        return None

    def _missing_endpoint_interaction(self, *, provider_name: str) -> dict[str, Any]:
        return {
            "type": "runtime_config_input",
            "kind": "endpoint_input",
            "provider": provider_name,
            "message": "Please enter the video generation endpoint for this external provider.",
            "config_fields": [
                {
                    "name": "VIDEO_GENERATION_ENDPOINT",
                    "env": "VIDEO_GENERATION_ENDPOINT",
                    "interaction_type": "endpoint",
                    "provider": provider_name,
                    "required": True,
                }
            ],
        }

    def _redact_url(self, url: str) -> str:
        return re.sub(r"([?&][^=]*(?:key|token|secret|credential)[^=]*=)[^&]+", r"\1***", str(url), flags=re.IGNORECASE)

    def _call_local_command(self, provider: dict[str, Any], prompt: str, options: dict[str, Any]) -> dict[str, Any]:
        command = provider.get("command") or provider.get("commands")
        if isinstance(command, str):
            command = [command]
        if not isinstance(command, list) or not command:
            return {"ok": False, "status": "requires_setup", "reason": "missing_command"}
        timeout = float(provider.get("timeout_seconds") or options.get("timeout_seconds") or 600)
        env = os.environ.copy()
        env["AI_CORE_VIDEO_PROMPT"] = prompt
        proc = subprocess.run([str(x) for x in command], input=prompt, text=True, capture_output=True, timeout=timeout, env=env)
        if proc.returncode != 0:
            return {"ok": False, "status": "failed", "stderr": proc.stderr[-1000:]}
        output = (proc.stdout or "").strip()
        try:
            return self._normalize_provider_result(json.loads(output), provider=provider)
        except Exception:
            return self._normalize_provider_result({"file_path": output}, provider=provider)

    def _call_http_json(self, provider_name: str, provider: dict[str, Any], prompt: str, options: dict[str, Any]) -> dict[str, Any]:
        endpoint = self._resolve_config_value(str(provider.get("video_generation_endpoint") or provider.get("video_endpoint") or provider.get("endpoint") or "").strip())
        if not endpoint:
            base = self._resolve_config_value(str(provider.get("base_url") or "").rstrip("/"))
            path = str(provider.get("video_generation_path") or provider.get("path") or "").strip("/")
            endpoint = f"{base}/{path}" if base and path else ""
        if not endpoint:
            return {"ok": False, "status": "requires_setup", "reason": "missing_endpoint"}
        secret_key = str(provider.get("secret_key") or provider.get("api_key_env") or "").strip()
        secret = self._provider_secret(secret_key)
        if secret_key and not secret:
            return {"ok": False, "status": "requires_setup", "reason": "missing_secret", "secret_key": secret_key, "interaction_type": "secret_input"}
        payload = self._render_payload(provider=provider, prompt=prompt, options=options)
        headers = {"Content-Type": "application/json"}
        if secret:
            headers[str(provider.get("authorization_header") or "Authorization")] = str(provider.get("authorization_prefix") or "Bearer ") + secret
        req = urllib.request.Request(endpoint, data=json.dumps(payload).encode("utf-8"), headers=headers, method=str(provider.get("method") or "POST"))
        timeout = float(provider.get("timeout_seconds") or options.get("timeout_seconds") or 600)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                raw = response.read()
        except Exception as exc:
            return {"ok": False, "status": "failed", "reason": "provider_request_failed", "endpoint": endpoint, "error": str(exc)[-1000:]}
        try:
            data = json.loads(raw.decode("utf-8"))
        except Exception:
            data = {"video_bytes": base64.b64encode(raw).decode("ascii")}
        return self._normalize_provider_result(data, provider=provider)

    def _normalize_provider_result(self, result: Any, provider: dict[str, Any] | None = None) -> dict[str, Any]:
        provider = provider if isinstance(provider, dict) else {}
        if not isinstance(result, dict):
            return {"ok": False, "status": "failed", "reason": "invalid_provider_result"}
        valid_suffixes = {".mp4", ".webm", ".gif", ".mov", ".mkv"}
        for key in ("file_path", "path", "output_path", "video_path"):
            value = result.get(key)
            if value and Path(str(value)).exists() and Path(str(value)).suffix.lower() in valid_suffixes:
                return {"ok": True, "status": "completed", "file_path": str(value)}
        for key in ("video_base64", "video_bytes", "b64_json", "base64"):
            value = result.get(key)
            if isinstance(value, str) and value.strip():
                return {"ok": True, "status": "completed", "video_base64": value.strip(), "suffix": str(result.get("suffix") or provider.get("default_suffix") or ".mp4")}
        data = result.get("data")
        if isinstance(data, list):
            for item in data:
                normalized = self._normalize_provider_result(item, provider=provider)
                if normalized.get("ok"):
                    return normalized
        for key in ("url", "video_url", "download_url"):
            if result.get(key):
                if bool(provider.get("download_remote_url", True)):
                    downloaded = self._download_remote_video(str(result.get(key) or ""), timeout=float(provider.get("download_timeout_seconds") or 1800))
                    if downloaded.get("ok"):
                        return downloaded
                return {"ok": False, "status": "requires_setup", "reason": "remote_url_download_not_configured"}
        return {"ok": False, "status": str(result.get("status") or "failed"), "reason": str(result.get("reason") or "no_video_material")}

    def _download_remote_video(self, url: str, *, timeout: float) -> dict[str, Any]:
        if not url.strip():
            return {"ok": False, "status": "failed", "reason": "empty_remote_url"}
        temp_dir = self._provider_temp_dir("remote_video")
        parsed = urllib.parse.urlparse(url)
        suffix = Path(parsed.path).suffix.lower()
        if suffix not in {".mp4", ".webm", ".gif", ".mov", ".mkv"}:
            suffix = ".mp4"
        target = temp_dir / f"remote_{uuid4().hex[:12]}{suffix}"
        try:
            with urllib.request.urlopen(url, timeout=timeout) as response:
                target.write_bytes(response.read())
        except Exception as exc:
            return {"ok": False, "status": "failed", "reason": "remote_url_download_failed", "error": str(exc)[-1000:]}
        if target.stat().st_size <= 0:
            return {"ok": False, "status": "failed", "reason": "remote_url_empty_file"}
        return {"ok": True, "status": "completed", "file_path": str(target)}

    def _effective_generation_timeout(self, *, provider: dict[str, Any], runtime: dict[str, Any], options: dict[str, Any]) -> float:
        configured = options.get("generation_timeout_seconds") or runtime.get("generation_timeout_seconds") or provider.get("timeout_seconds") or options.get("timeout_seconds") or 900
        try:
            value = float(configured)
        except Exception:
            value = 900.0
        if options.get("strict_timeout_seconds") is not None:
            try:
                return max(1.0, float(options.get("strict_timeout_seconds")))
            except Exception:
                return max(1.0, value)
        floor = runtime.get("minimum_generation_timeout_seconds") or provider.get("minimum_generation_timeout_seconds") or 1800
        try:
            floor_value = float(floor)
        except Exception:
            floor_value = 1800.0
        return max(value, floor_value)

    def _setup_message(self, attempted: list[dict[str, Any]]) -> str:
        if not attempted:
            return "Video generation is recognized, but no video provider is available in the current runtime route."
        parts = []
        for item in attempted[:5]:
            provider = str(item.get("provider") or "provider")
            reason = str(item.get("reason") or item.get("status") or "not_ready")
            detail = str(item.get("error_type") or item.get("missing_import") or "").strip()
            parts.append(f"{provider}: {reason}" + (f" ({detail})" if detail else ""))
        return "Video generation provider setup is required. Attempted providers: " + "; ".join(parts) + "."

    def _setup_actions(self, *, route: list[str], providers: dict[str, Any], attempted: list[dict[str, Any]]) -> list[dict[str, Any]]:
        actions: list[dict[str, Any]] = []
        attempted_by_provider = {str(x.get("provider") or ""): x for x in attempted if isinstance(x, dict)}
        for provider_name in route:
            provider = providers.get(provider_name) if isinstance(providers.get(provider_name), dict) else {}
            attempt = attempted_by_provider.get(provider_name, {})
            protocol = str(provider.get("protocol") or provider.get("type") or "").strip()
            reason = str(attempt.get("reason") or "").strip()
            if reason == "missing_endpoint":
                actions.append({
                    "provider": provider_name,
                    "kind": "set_endpoint",
                    "env": "VIDEO_GENERATION_ENDPOINT",
                    "message": "Set VIDEO_GENERATION_ENDPOINT for this provider or disable it in runtime/configs/media/video_generation.yaml.",
                })
            if str(provider.get("api_key_env") or provider.get("secret_key") or "").strip():
                env_name = str(provider.get("api_key_env") or provider.get("secret_key"))
                actions.append({
                    "provider": provider_name,
                    "kind": "set_secret",
                    "env": env_name,
                    "message": f"Set {env_name} for this provider or disable it in runtime/configs/media/video_generation.yaml.",
                })
            if protocol in {"comfyui", "comfyui_runtime", "local_comfyui"} or "runtime" in provider:
                action = {
                    "provider": provider_name,
                    "kind": "prepare_local_video_runtime",
                    "message": "Prepare the configured local video runtime, workflow template, custom nodes, and model assets, or point runtime/configs/media/video_generation.yaml to an already running video provider.",
                    "reason": reason or str(attempt.get("status") or "not_ready"),
                    "endpoint": provider.get("base_url") or (provider.get("runtime") or {}).get("base_url"),
                }
                if reason in {"workflow_template_missing", "workflow_template_source_missing", "workflow_template_download_failed", "workflow_repository_clone_failed"}:
                    action["env"] = "AI_CORE_VIDEO_WORKFLOW_TEMPLATE"
                    action["url_env"] = "AI_CORE_VIDEO_WORKFLOW_TEMPLATE_URL"
                    action["repository_env"] = "AI_CORE_VIDEO_WORKFLOW_TEMPLATE_REPOSITORY"
                    action["message"] = "Provide AI_CORE_VIDEO_WORKFLOW_TEMPLATE_URL or AI_CORE_VIDEO_WORKFLOW_TEMPLATE_REPOSITORY. The runtime will download/discover the ComfyUI video workflow template automatically before execution. AI_CORE_VIDEO_WORKFLOW_TEMPLATE is still accepted when a local workflow file already exists."
                actions.append(action)
            if not provider:
                actions.append({"provider": provider_name, "kind": "register_provider", "message": "Register a provider record for this video generation route."})
        return actions

    def _diagnostic_log_path(self) -> Path:
        path = RUNTIME_DIR / "logs" / "video_generation_diagnostics.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def _record_diagnostic_event(self, *, level: str, reason: str, result: dict[str, Any], attempted: list[dict[str, Any]], duration_seconds: float) -> None:
        """Write traceable diagnostics for video generation failures.

        This is intentionally generic: it records provider protocol/status/error
        metadata and redacts large material fields. It does not inspect business
        semantics or model-specific content.
        """
        try:
            safe_result = dict(result or {})
            for key in ("video_base64", "image_base64", "binary", "data"):
                if key in safe_result:
                    safe_result[key] = "<redacted>"
            event = {
                "event_type": "video_generation_diagnostic",
                "capability_type": "video_generation",
                "level": str(level or "info"),
                "reason": str(reason or safe_result.get("reason") or safe_result.get("status") or "unknown"),
                "ok": bool(safe_result.get("ok")),
                "status": str(safe_result.get("status") or ""),
                "duration_seconds": round(float(duration_seconds), 3),
                "attempted": attempted[-10:] if isinstance(attempted, list) else [],
                "result": safe_result,
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
            with self._diagnostic_log_path().open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(event, ensure_ascii=False) + "\n")
        except Exception:
            return

    def _attempt_record(self, *, provider_name: str, result: dict[str, Any]) -> dict[str, Any]:
        record = super()._attempt_record(provider_name=provider_name, result=result)
        for key in ("error_type", "error", "traceback", "frame_count", "minimum_required_frames", "module", "package", "endpoint"):
            value = result.get(key) if isinstance(result, dict) else None
            if value:
                text = str(value)
                record[key] = text[-4000:] if key == "traceback" else text[-1000:]
        return record

    def _metrics_path(self) -> Path:
        path = RUNTIME_DIR / "generated" / "media" / "video_generation_metrics.jsonl"
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
                "capability_type": "video_generation",
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

    def _persist_video(self, result: dict[str, Any], *, provider_name: str, stage_meta: dict[str, Any]) -> dict[str, Any]:
        download_id = f"video_{uuid4().hex[:12]}"
        target_dir = RUNTIME_DOWNLOADS / download_id
        target_dir.mkdir(parents=True, exist_ok=True)
        source_path = result.get("file_path")
        if source_path:
            src = Path(str(source_path))
            suffix = src.suffix if src.suffix.lower() in {".mp4", ".webm", ".gif", ".mov", ".mkv"} else ".mp4"
            filename = f"generated_video{suffix}"
            target = target_dir / filename
            target.write_bytes(src.read_bytes())
        else:
            suffix = str(result.get("suffix") or ".mp4")
            if not suffix.startswith("."):
                suffix = "." + suffix
            filename = f"generated_video{suffix}"
            target = target_dir / filename
            target.write_bytes(base64.b64decode(str(result.get("video_base64") or "")))
        size = target.stat().st_size
        download_url = f"/api/downloads/{download_id}/{filename}"
        mime = "video/mp4"
        if filename.lower().endswith(".webm"):
            mime = "video/webm"
        elif filename.lower().endswith(".gif"):
            mime = "image/gif"
        elif filename.lower().endswith(".mov"):
            mime = "video/quicktime"
        artifact_metadata = result.get("artifact_metadata") if isinstance(result.get("artifact_metadata"), dict) else {}
        material = {
            "type": "video",
            "download_id": download_id,
            "file_name": filename,
            "file_path": str(target),
            "download_url": download_url,
            "preview_url": download_url,
            "mime_type": mime,
            "size": size,
            "provider": provider_name,
            "stage_policy": stage_meta,
        }
        (target_dir / "metadata.json").write_text(json.dumps(material, ensure_ascii=False, indent=2), encoding="utf-8")
        return material
