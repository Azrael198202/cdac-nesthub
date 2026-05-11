import asyncio
from pathlib import Path

from ai_core.orchestration.workflow_engine import WorkflowEngine


async def main() -> None:
    engine = WorkflowEngine(config_root=str(Path("configs")))
    workflow = engine.load_workflow("workflows/default_orchestration.yaml")
    result = await engine.run(workflow, initial_state={"input": "hello"})
    print(result)


if __name__ == "__main__":
    asyncio.run(main())
