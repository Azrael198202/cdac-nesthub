import asyncio
from ai_core.orchestration.workflow_engine import WorkflowEngine

async def main():
    engine = WorkflowEngine()
    events = []
    async for e in engine.run_stream("Please check the weather forecast for Tokyo tomorrow and then book a flight to Tokyo."):
        events.append(e.type)
        print(e.type, e.title)
    assert "final" in events
    assert "tool_result" in events
    print("OK")

asyncio.run(main())
