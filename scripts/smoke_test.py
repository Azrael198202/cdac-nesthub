import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ai_core.orchestration.workflow_engine import WorkflowEngine

async def main():
    engine = WorkflowEngine()
    events = []
    async for ev in engine.run("Create a short implementation plan for a new feature."):
        events.append(ev.to_dict())
    assert any(e["type"] == "bootstrap" for e in events)
    assert any(e["type"] == "workflow" for e in events)
    print("smoke test ok; events=", len(events))

if __name__ == "__main__":
    asyncio.run(main())
