from __future__ import annotations

import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ai_core.orchestration.engine import VerifiedOrchestrationEngine

async def main():
    engine = VerifiedOrchestrationEngine()
    result = await engine.run("Please check the weather forecast for Tokyo tomorrow and then book a flight to Tokyo.")
    assert "Tokyo weather" in result["final_answer"]
    assert "departure_city" in result["final_answer"]
    print("SMOKE TEST OK")
    print(result["final_answer"])
    print(result["trace_file"])

if __name__ == "__main__":
    asyncio.run(main())
