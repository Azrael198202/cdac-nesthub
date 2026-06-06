from __future__ import annotations

import asyncio
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def test_imports() -> None:
    from presentation_brain import PresentationBrain, PresentationRequest
    from ai_core.executors.output_executor import OutputExecutor
    assert PresentationBrain is not None
    assert PresentationRequest is not None
    assert OutputExecutor is not None


async def test_presentation_brain_synthesis() -> None:
    from presentation_brain import PresentationBrain, PresentationRequest
    brain = PresentationBrain()
    result = await brain.synthesize(PresentationRequest(
        run_id="verify_v22_1",
        node_id="output",
        original_input="Return final answer",
        state={"runtime": {"output_policy": {"disable_model_synthesis": True}}},
        materials=[{"source": "test", "status": "success", "content": {"final_answer": "Hello from Presentation Brain"}}],
        trust_summary={"trust_level": "verified"},
    ))
    assert result.status == "completed"
    assert "Hello from Presentation Brain" in result.final_answer


def test_no_runtime_framework_code() -> None:
    assert not Path("runtime/model_routing").exists()
    assert Path("presentation_brain/brain.py").exists()


if __name__ == "__main__":
    test_imports()
    asyncio.run(test_presentation_brain_synthesis())
    test_no_runtime_framework_code()
    print("verify_v22_1_presentation_brain: OK")
