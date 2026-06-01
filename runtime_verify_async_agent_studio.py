import asyncio
import httpx
import apps.api.server as server

async def _fake_handle_message(*args, **kwargs):
    await asyncio.sleep(0.05)
    return {"ok": True, "status": "completed", "final_answer": "verified", "action": "conversation_message"}

async def main() -> None:
    original = server.studio_service.handle_message
    server.studio_service.handle_message = _fake_handle_message
    try:
        run_id = "verify_async_terminal"
        transport = httpx.ASGITransport(app=server.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.post("/api/agent-studio/message", json={"message": "verify", "client_run_id": run_id})
            assert r.status_code == 200, r.text
            first = r.json()
            assert first["status"] == "running", first
            terminal = None
            for _ in range(80):
                await asyncio.sleep(0.05)
                state = (await client.get(f"/api/agent-studio/run-status/{run_id}")).json()
                if state.get("status") != "running":
                    terminal = state
                    break
            assert terminal is not None, "run did not reach terminal status"
            assert terminal["status"] == "completed", terminal
            assert terminal["result"]["final_answer"] == "verified", terminal
        print("async_agent_studio_terminal_status_ok")
    finally:
        server.studio_service.handle_message = original

if __name__ == "__main__":
    asyncio.run(main())
