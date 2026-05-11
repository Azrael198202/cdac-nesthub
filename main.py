from __future__ import annotations

import argparse
import asyncio
import uvicorn

from ai_core.api.server import create_app
from ai_core.bootstrap.runtime_bootstrap import RuntimeBootstrap
from ai_core.orchestration.engine import VerifiedOrchestrationEngine

DEMO_TEXT = "Please check the weather forecast for Tokyo tomorrow and then book a flight to Tokyo."


async def run_demo() -> None:
    RuntimeBootstrap().ensure_runtime_base()
    engine = VerifiedOrchestrationEngine()
    result = await engine.run(DEMO_TEXT, interactive=False)
    print("\n=== FINAL ANSWER ===")
    print(result.get("final_answer"))
    print("\n=== TRACE FILE ===")
    print(result.get("trace_file"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    RuntimeBootstrap().ensure_runtime_base()
    if args.demo:
        asyncio.run(run_demo())
        return

    uvicorn.run(create_app(), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
