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
