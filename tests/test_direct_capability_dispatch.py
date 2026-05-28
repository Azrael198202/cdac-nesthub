from __future__ import annotations

import asyncio

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
