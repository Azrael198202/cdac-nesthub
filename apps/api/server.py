import asyncio
from typing import Any
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from pydantic import BaseModel

from ai_core.orchestration.workflow_runtime import WorkflowRuntime
from ai_core.events.event_bus import event_bus

app = FastAPI()
runtime = WorkflowRuntime()


class ChatRequest(BaseModel):
    message: str


class ResumeRequest(BaseModel):
    run_id: str
    decision: str = "approve"
    modified_result: dict[str, Any] | None = None
    feedback: str | None = None


@app.get("/")
async def home():
    html = open("apps/web/index.html", "r", encoding="utf-8").read()
    return HTMLResponse(
        html,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
            "X-AI-Core-Version": "v13",
        },
    )


@app.get("/api/version")
async def version():
    return JSONResponse({"version": "v13", "name": "ai_core_config_driven_node_runtime_v13"})


@app.post("/api/chat")
async def chat(req: ChatRequest):
    run_id, state = await runtime.prepare(req.message)
    asyncio.create_task(runtime.run_prepared(state))
    return {"run_id": run_id}


@app.post("/api/resume")
async def resume(req: ResumeRequest):
    asyncio.create_task(runtime.resume(req.run_id, req.decision, req.modified_result, req.feedback))
    return {"ok": True, "run_id": req.run_id}


@app.get("/api/events/{run_id}")
async def events(run_id: str):
    return StreamingResponse(event_bus.stream(run_id), media_type="text/event-stream")
