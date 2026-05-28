from __future__ import annotations

import asyncio
from pathlib import Path

from ai_core.capabilities.capability_dispatcher import CapabilityDispatcher
from auxiliary_brain.studio.service import AgentStudioService


def test_dispatcher_routes_text_to_image_generation() -> None:
    async def handler(request: dict) -> dict:
        return {"status": "completed", "final_answer": "handled", "request": request}

    dispatcher = CapabilityDispatcher(handlers={"image_generation": handler})
    result = asyncio.run(dispatcher.dispatch(text="Generate an image of a 3D cartoon AI agent working inside a task graph scene.", context={}))
    assert result is not None
    assert result["status"] == "completed"
    assert result["capability_profile"]["capability_type"] == "image_generation"
    assert result["capability_profile"]["output_modality"] == "image"
    assert result["fallback_isolated"] is True


def test_dispatcher_reserves_video_generation_without_chat_fallback() -> None:
    dispatcher = CapabilityDispatcher(handlers={})
    result = asyncio.run(dispatcher.dispatch(text="Generate a video from this task graph.", context={}))
    assert result is not None
    assert result["status"] == "requires_setup"
    assert result["capability_profile"]["capability_type"] == "video_generation"
    assert result["fallback_isolated"] is True


def test_agent_studio_direct_capability_runs_before_model_preflight() -> None:
    class FakeDispatcher:
        async def dispatch(self, *, text: str, context: dict | None = None) -> dict:
            return {"status": "completed", "final_answer": "image route ok"}

    class FailingPreflight:
        async def check_before_runtime(self) -> dict:
            raise AssertionError("text model preflight must not run for direct output-modality dispatch")

    service = AgentStudioService()
    service.direct_capability_dispatcher = FakeDispatcher()
    service.model_preflight = FailingPreflight()
    result = asyncio.run(service.handle_message("Generate an image of a 3D cartoon AI agent working inside a task graph scene."))
    assert result["status"] == "completed"
    assert result["final_answer"] == "image route ok"


def test_image_generation_bootstrap_exposes_provider_setup_actions(monkeypatch) -> None:
    from ai_core.media.image_generation_service import ImageGenerationService

    service = ImageGenerationService()

    async def fake_call_provider(*, provider_name: str, provider: dict, prompt: str, options: dict) -> dict:
        if provider_name == "external_image_generation":
            return {"ok": False, "status": "requires_setup", "reason": "missing_secret", "secret_key": "OPENAI_API_KEY"}
        return {"ok": False, "status": "requires_setup", "reason": "runtime_not_running", "endpoint": "http://127.0.0.1:8188"}

    monkeypatch.setattr(service, "_call_provider", fake_call_provider)
    result = asyncio.run(service.generate(prompt="Generate an image of a neutral scene."))
    assert result["status"] == "requires_setup"
    assert result["message"] != "No configured image generation provider produced image material."
    assert result["attempted"]
    assert any(action.get("kind") == "set_secret" for action in result.get("setup_actions", []))
    assert any(action.get("kind") == "prepare_local_runtime" for action in result.get("setup_actions", []))


def test_image_generation_seed_registers_external_fallback() -> None:
    from ai_core.media.image_generation_service import ImageGenerationService

    service = ImageGenerationService()
    config = service._provider_config()
    providers = config.get("providers") or {}
    assert "local_image_generation" in providers
    assert "external_image_generation" in providers
    assert "external_image_generation" in (config.get("default_route") or [])


def test_comfyui_generation_timeout_has_safe_floor() -> None:
    from ai_core.media.image_generation_service import ImageGenerationService

    service = ImageGenerationService()
    timeout = service._effective_generation_timeout(
        provider={"timeout_seconds": 300},
        runtime={"generation_timeout_seconds": 300},
        options={},
    )
    assert timeout >= 900


def test_comfyui_generation_timeout_can_be_strict_per_request() -> None:
    from ai_core.media.image_generation_service import ImageGenerationService

    service = ImageGenerationService()
    timeout = service._effective_generation_timeout(
        provider={"timeout_seconds": 900},
        runtime={"generation_timeout_seconds": 900},
        options={"strict_timeout_seconds": 120},
    )
    assert timeout == 120


def test_dispatcher_routes_animation_to_video_generation() -> None:
    async def handler(request: dict) -> dict:
        return {"status": "completed", "final_answer": "video handled", "request": request}

    dispatcher = CapabilityDispatcher(handlers={"video_generation": handler})
    result = asyncio.run(dispatcher.dispatch(text="Generate an animation of the 3D agent working in a task graph.", context={}))
    assert result is not None
    assert result["status"] == "completed"
    assert result["capability_profile"]["capability_type"] == "video_generation"
    assert result["capability_profile"]["output_modality"] == "video"
    assert result["fallback_isolated"] is True


def test_video_generation_seed_registers_local_and_external_routes() -> None:
    from ai_core.media.video_generation_service import VideoGenerationService

    service = VideoGenerationService()
    config = service._provider_config()
    providers = config.get("providers") or {}
    assert "local_video_generation" in providers
    assert "external_video_generation" in providers
    assert "local_video_generation" in (config.get("default_route") or [])
    assert "external_video_generation" in (config.get("default_route") or [])


def test_video_generation_can_persist_provider_file(tmp_path) -> None:
    from ai_core.media.video_generation_service import VideoGenerationService

    src = tmp_path / "sample.mp4"
    src.write_bytes(b"video-bytes")
    service = VideoGenerationService()
    material = service._persist_video({"file_path": str(src)}, provider_name="test_video_provider", stage_meta={})
    assert material["type"] == "video"
    assert material["download_url"].endswith("generated_video.mp4")
    assert material["mime_type"] == "video/mp4"
    assert Path(material["file_path"]).exists()


def test_video_generation_route_filters_text_model_providers() -> None:
    from ai_core.media.video_generation_service import VideoGenerationService

    service = VideoGenerationService()
    config = {
        "default_route": ["ollama", "local_video_generation", "external_video_generation"],
        "providers": {
            "ollama": {"enabled": True, "protocol": "ollama", "role": "text_model", "capabilities": ["chat"]},
            "stage_video_generation_ollama_local_video_generator": {"enabled": True, "protocol": "ollama", "capabilities": ["chat"]},
            "local_video_generation": {"enabled": True, "protocol": "comfyui", "capabilities": ["video_generation"], "source_policy": {"mode": "media_allowed"}},
            "external_video_generation": {"enabled": True, "protocol": "generic_http_json", "capabilities": ["video_generation"], "source_policy": {"mode": "fallback_allowed"}, "video_generation_endpoint": "http://example.invalid/video"},
        },
    }
    route, providers, meta = service._route(config=config, options={})
    assert "ollama" not in route
    assert "stage_video_generation_ollama_local_video_generator" not in route
    assert route[:2] == ["local_video_generation", "external_video_generation"]
    assert meta.get("route_isolated_to_capability") == "video_generation"


def test_video_generation_setup_actions_explain_workflow_template() -> None:
    from ai_core.media.video_generation_service import VideoGenerationService

    service = VideoGenerationService()
    actions = service._setup_actions(
        route=["local_video_generation"],
        providers={
            "local_video_generation": {
                "protocol": "comfyui",
                "runtime": {"base_url": "http://127.0.0.1:8188"},
                "capabilities": ["video_generation"],
            }
        },
        attempted=[{"provider": "local_video_generation", "reason": "workflow_template_missing"}],
    )
    assert any(action.get("env") == "AI_CORE_VIDEO_WORKFLOW_TEMPLATE" for action in actions)


def test_video_generation_seed_registers_generic_text_animation_fallback() -> None:
    from ai_core.media.video_generation_service import VideoGenerationService

    service = VideoGenerationService()
    config = service._provider_config()
    providers = config.get("providers") or {}
    route = config.get("default_route") or []
    assert "generic_text_animation" in providers
    assert "generic_text_animation" in route
    assert route.index("generic_text_animation") < route.index("external_video_generation")


def test_generic_text_animation_provider_produces_real_gif() -> None:
    from ai_core.media.providers.generic_text_animation_provider import generate_text_animation

    result = generate_text_animation(prompt="Generate an animation of a task graph.", options={"frames": 8, "width": 320, "height": 180})
    assert result["ok"] is True
    assert result["file_path"].endswith(".gif")
    assert Path(result["file_path"]).exists()
    assert Path(result["file_path"]).stat().st_size > 0


def test_video_workflow_template_bootstrap_downloads_from_url(tmp_path, monkeypatch) -> None:
    from ai_core.media.video_generation_service import VideoGenerationService

    src = tmp_path / "source_workflow.json"
    src.write_text('{"1": {"class_type": "TestNode", "inputs": {"text": "{prompt}"}}}', encoding="utf-8")
    target_dir = tmp_path / "templates"
    monkeypatch.setenv("AI_CORE_VIDEO_WORKFLOW_TEMPLATE_URL", src.as_uri())
    service = VideoGenerationService()
    provider = {"workflow_bootstrap": {"target_dir": str(target_dir), "url_env": "AI_CORE_VIDEO_WORKFLOW_TEMPLATE_URL"}}
    boot = service._bootstrap_video_workflow_template(provider=provider, runtime={})
    assert boot["ok"] is True
    assert Path(boot["workflow_template"]).exists()
    rendered = service._render_workflow(provider=provider, runtime={}, prompt="hello", options={})
    assert rendered["ok"] is True
    assert rendered["workflow"]["1"]["inputs"]["text"] == "hello"


def test_external_video_missing_secret_uses_secret_input_interaction(monkeypatch) -> None:
    from ai_core.media.video_generation_service import VideoGenerationService

    monkeypatch.delenv("VIDEO_GENERATION_API_KEY", raising=False)
    service = VideoGenerationService()
    result = service._call_http_json(
        "external_video_generation",
        {
            "protocol": "generic_http_json",
            "video_generation_endpoint": "http://example.invalid/video",
            "api_key_env": "VIDEO_GENERATION_API_KEY",
        },
        "make video",
        {},
    )
    assert result["reason"] == "missing_secret"
    attempted = [{"provider": "external_video_generation", "reason": "missing_secret", "secret_key": "VIDEO_GENERATION_API_KEY"}]
    interaction = service._first_missing_secret_action(attempted)
    assert interaction["kind"] == "secret_input"
    assert interaction["secret_key"] == "VIDEO_GENERATION_API_KEY"


def test_runtime_dependency_installer_maps_import_to_package() -> None:
    from ai_core.dependencies import RuntimeDependencyInstaller

    installer = RuntimeDependencyInstaller()
    result = installer.install_for_missing_import(
        "PIL",
        provider={"python_import_package_map": {"PIL": "Pillow>=10.0.0"}},
    )
    assert result["ok"] is True
    assert result["status"] in {"already_available", "installed"}


def test_generic_text_animation_provider_declares_python_dependency() -> None:
    from ai_core.media.video_generation_service import VideoGenerationService

    config = VideoGenerationService()._video_seed_config()
    provider = config["providers"]["generic_text_animation"]
    deps = provider.get("python_dependencies") or []
    assert any((item.get("import") == "PIL" and "Pillow" in item.get("package", "")) for item in deps)


def test_generic_text_animation_provider_has_no_import_time_pillow_dependency(monkeypatch):
    import builtins
    import importlib
    from pathlib import Path

    module = importlib.import_module("ai_core.media.providers.generic_text_animation_provider")
    real_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name == "PIL" or name.startswith("PIL."):
            raise ModuleNotFoundError("No module named 'PIL'", name="PIL")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    result = module.generate_text_animation(prompt="fallback animation", options={"frames": 8, "width": 160, "height": 90})
    assert result["ok"] is False
    assert result["reason"] == "generic_text_animation_render_failed"
    assert result["minimum_required_frames"] == 8


def test_external_video_missing_endpoint_uses_endpoint_input_interaction(monkeypatch):
    from ai_core.media.video_generation_service import VideoGenerationService

    monkeypatch.delenv("VIDEO_GENERATION_ENDPOINT", raising=False)
    service = VideoGenerationService()
    result = service._call_http_json(
        "external_video_generation",
        {
            "protocol": "generic_http_json",
            "video_generation_endpoint": "${VIDEO_GENERATION_ENDPOINT}",
            "api_key_env": "VIDEO_GENERATION_API_KEY",
        },
        "make video",
        {},
    )
    assert result["reason"] == "missing_endpoint"
    attempted = [{"provider": "external_video_generation", "reason": "missing_endpoint"}]
    interaction = service._first_missing_secret_action(attempted)
    assert interaction["kind"] in {"endpoint_input", "video_generation_setup_wizard"}
    assert interaction["config_fields"][0]["env"] == "VIDEO_GENERATION_ENDPOINT"
    actions = service._setup_actions(
        route=["external_video_generation"],
        providers={
            "external_video_generation": {
                "protocol": "generic_http_json",
                "capabilities": ["video_generation"],
                "video_generation_endpoint": "${VIDEO_GENERATION_ENDPOINT}",
                "api_key_env": "VIDEO_GENERATION_API_KEY",
            }
        },
        attempted=attempted,
    )
    assert any(action.get("kind") == "set_endpoint" for action in actions)


def test_generic_text_animation_default_and_prompt_frame_count(tmp_path, monkeypatch):
    from ai_core.config import paths
    monkeypatch.setattr(paths, "RUNTIME_DIR", tmp_path)
    import ai_core.media.providers.generic_text_animation_provider as provider_mod
    monkeypatch.setattr(provider_mod, "RUNTIME_DIR", tmp_path)
    result_default = provider_mod.generate_text_animation(prompt="Generate an animation of a graph", provider={"frames": 8, "max_frames": 64})
    assert result_default["ok"] is True
    assert result_default["artifact_metadata"]["frame_count"] == 8
    result_explicit = provider_mod.generate_text_animation(prompt="Generate an animation with 12 frames", provider={"frames": 8, "max_frames": 64})
    assert result_explicit["ok"] is True
    assert result_explicit["artifact_metadata"]["frame_count"] == 12


def test_generic_text_animation_caps_frame_count(tmp_path, monkeypatch):
    from ai_core.config import paths
    monkeypatch.setattr(paths, "RUNTIME_DIR", tmp_path)
    import ai_core.media.providers.generic_text_animation_provider as provider_mod
    monkeypatch.setattr(provider_mod, "RUNTIME_DIR", tmp_path)
    result = provider_mod.generate_text_animation(prompt="Generate an animation with 999 frames", provider={"frames": 8, "max_frames": 24})
    assert result["ok"] is True
    assert result["artifact_metadata"]["frame_count"] == 24


def test_video_generation_requires_setup_is_logged_without_unhandled_name_error(tmp_path, monkeypatch):
    from ai_core.config import paths
    from ai_core.media.video_generation_service import VideoGenerationService

    monkeypatch.setattr(paths, "RUNTIME_DIR", tmp_path)
    import ai_core.media.image_generation_service as image_service_mod
    import ai_core.media.video_generation_service as video_service_mod
    monkeypatch.setattr(image_service_mod, "RUNTIME_DIR", tmp_path)
    monkeypatch.setattr(video_service_mod, "RUNTIME_DIR", tmp_path)

    service = VideoGenerationService()
    monkeypatch.setattr(service, "_provider_config", lambda: {"default_route": [], "providers": {}})
    result = asyncio.run(service.generate(prompt="Generate an animation of a graph"))
    assert result["ok"] is False
    assert result["status"] == "requires_setup"
    assert result.get("reason") != "video_generation_unhandled_exception"
    log_path = tmp_path / "logs" / "video_generation_diagnostics.jsonl"
    assert log_path.exists()
    assert "requires_setup" in log_path.read_text(encoding="utf-8")


def test_video_generation_unhandled_exception_is_returned_and_logged(tmp_path, monkeypatch):
    from ai_core.config import paths
    from ai_core.media.video_generation_service import VideoGenerationService

    monkeypatch.setattr(paths, "RUNTIME_DIR", tmp_path)
    import ai_core.media.image_generation_service as image_service_mod
    import ai_core.media.video_generation_service as video_service_mod
    monkeypatch.setattr(image_service_mod, "RUNTIME_DIR", tmp_path)
    monkeypatch.setattr(video_service_mod, "RUNTIME_DIR", tmp_path)

    service = VideoGenerationService()
    def boom():
        raise RuntimeError("forced diagnostics failure")
    monkeypatch.setattr(service, "_provider_config", boom)
    result = asyncio.run(service.generate(prompt="Generate an animation of a graph"))
    assert result["ok"] is False
    assert result["status"] == "failed"
    assert result["reason"] == "video_generation_unhandled_exception"
    assert result["error_type"] == "RuntimeError"
    log_path = tmp_path / "logs" / "video_generation_diagnostics.jsonl"
    assert log_path.exists()
    text = log_path.read_text(encoding="utf-8")
    assert "forced diagnostics failure" in text
    assert "video_generation_unhandled_exception" in text


def test_runtime_dependency_installer_allows_development_administrator_specs() -> None:
    from ai_core.dependencies import RuntimeDependencyInstaller

    installer = RuntimeDependencyInstaller()
    assert installer._safe_package_spec("Pillow>=10.0.0") is True
    assert installer._safe_package_spec("Pillow==10.4.0") is True
    assert installer._safe_package_spec("package-name[extra]>=1.2.3") is True
    assert installer._safe_package_spec("https://example.com/pkg.whl") is True
    assert installer._safe_package_spec("git+https://example.com/repo.git") is True
    assert installer._safe_package_spec("/tmp/local_pkg.whl") is True
    assert installer._safe_package_spec("Pillow; echo test") is True


def test_runtime_dependency_installer_can_be_restricted_for_production() -> None:
    from ai_core.dependencies import RuntimeDependencyInstaller
    from ai_core.runtime.environment.permission_policy import RuntimePermissionPolicy

    policy = RuntimePermissionPolicy(
        level="restricted",
        allow_arbitrary_package_spec=False,
        allow_arbitrary_url=False,
        allow_arbitrary_path=False,
        allow_command_concat=False,
        allow_shell_injection=False,
    )
    installer = RuntimeDependencyInstaller(policy=policy)
    assert installer._safe_package_spec("Pillow>=10.0.0") is True
    assert installer._safe_package_spec("Pillow; rm -rf /") is False
    assert installer._safe_package_spec("https://example.com/pkg.whl") is False


def test_runtime_permission_policy_defaults_to_administrator_install() -> None:
    from ai_core.runtime.environment.permission_policy import RuntimePermissionPolicy

    policy = RuntimePermissionPolicy.from_env()
    assert policy.level == "administrator"
    assert policy.can_execute(kind="install") is True
    assert policy.can_use_arbitrary_runtime_material(material_type="package_spec") is True
    assert policy.allow_shell_injection is True


def test_agent_studio_renders_gif_artifact_as_image_not_video() -> None:
    html = Path("apps/web/agent_studio.html").read_text(encoding="utf-8")
    assert "function isGifDownloadUrl" in html
    assert "answerGifPreview" in html
    assert "renderVideoLikeMedia(url, label" in html
    assert "<img class=\"answerGifPreview\"" in html


def test_video_model_dependency_manifest_seed_is_loaded() -> None:
    from ai_core.media.video_generation_service import VideoGenerationService

    service = VideoGenerationService()
    config = service._video_seed_config()
    provider = config["providers"]["local_video_generation"]
    assert provider["model_dependency_manifest"]["enabled"] is True
    manifest = service._load_video_model_dependency_manifest(provider=provider, runtime={})
    assert manifest["ok"] is True
    assert manifest["profile"] == "text_to_video"
    assert "model_assets" in manifest
    assert "custom_nodes" in manifest


def test_video_model_dependency_manifest_downloads_model_asset(tmp_path, monkeypatch) -> None:
    import ai_core.media.video_generation_service as video_service_mod
    from ai_core.media.video_generation_service import VideoGenerationService

    project_root = tmp_path / "project"
    runtime_dir = project_root / "runtime"
    configs_dir = project_root / "configs"
    (runtime_dir / "configs" / "media").mkdir(parents=True)
    configs_dir.mkdir(parents=True)
    monkeypatch.setattr(video_service_mod, "RUNTIME_CONFIGS", runtime_dir / "configs")
    monkeypatch.setattr(video_service_mod, "RUNTIME_DIR", runtime_dir)
    monkeypatch.setattr(video_service_mod, "CONFIGS_DIR", configs_dir)

    source = tmp_path / "model.bin"
    source.write_bytes(b"model-bytes")
    manifest = runtime_dir / "configs" / "media" / "video_model_dependency_manifest.yaml"
    manifest.write_text(
        f"""
version: 1.0
profiles:
  text_to_video:
    model_assets:
      - name: tiny_test_model
        target_subdir: models/checkpoints
        file_name: tiny_test_model.bin
        url: {source.as_uri()}
        auto_download: true
""".strip(),
        encoding="utf-8",
    )
    service = VideoGenerationService()
    runtime = {"root": str(tmp_path / "comfyui")}
    provider = {
        "model_dependency_manifest": {
            "enabled": True,
            "manifest_file": str(manifest),
            "profile": "text_to_video",
        }
    }
    result = service._ensure_model_assets(provider=provider, runtime=runtime)
    assert result["ok"] is True
    target = tmp_path / "comfyui" / "models" / "checkpoints" / "tiny_test_model.bin"
    assert target.read_bytes() == b"model-bytes"
    assert result["dependency_manifest"]["model_asset_count"] == 1


def test_video_workflow_values_include_frame_count_and_uppercase_placeholders(tmp_path) -> None:
    from ai_core.media.video_generation_service import VideoGenerationService

    workflow = tmp_path / "workflow.json"
    workflow.write_text(
        '{"1":{"class_type":"Prompt","inputs":{"text":"{PROMPT}","frames":"{FRAME_COUNT}","w":"{WIDTH}","h":"{HEIGHT}"}}}',
        encoding="utf-8",
    )
    service = VideoGenerationService()
    result = service._render_workflow(
        provider={"workflow_template": str(workflow), "width": 320, "height": 180},
        runtime={},
        prompt="hello video",
        options={"frames": 12},
    )
    assert result["ok"] is True
    inputs = result["workflow"]["1"]["inputs"]
    assert inputs["text"] == "hello video"
    assert inputs["frames"] == "12"
    assert inputs["w"] == "320"
    assert inputs["h"] == "180"
