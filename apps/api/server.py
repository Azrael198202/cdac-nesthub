import asyncio
from typing import Any

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from pydantic import BaseModel

from ai_core.evolution.approval_learning import ApprovalLearningService
from ai_core.orchestration.workflow_runtime import WorkflowRuntime
from ai_core.events.event_bus import event_bus

approval_learning = ApprovalLearningService()
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
            "X-AI-Core-Version": "v38",
        },
    )


@app.get("/api/version")
async def version():
    return JSONResponse({"version": "v38", "name": "ai_core_human_interaction_runtime_v38"})


@app.post("/api/chat")
async def chat(req: ChatRequest):
    run_id, state = await runtime.prepare(req.message)
    asyncio.create_task(runtime.run_prepared(state))
    return {"run_id": run_id}


@app.post("/api/resume")
async def resume(req: ResumeRequest):
    try:
        if req.decision == "approve":
            state = runtime.checkpoints.load(req.run_id)
            pending = state.get("pending_action", {}) if state else {}
            node_id = pending.get("node_id")
            approved_output = state.get("results", {}).get(node_id, {}) if state and node_id else {}
            if node_id and isinstance(approved_output, dict):
                approval_learning.record_approval(
                    run_id=req.run_id,
                    node_id=node_id,
                    user_input=state.get("input", ""),
                    approved_output=approved_output,
                    feedback=req.feedback or "",
                )
                await runtime._emit(req.run_id, {
                    "type": "APPROVAL_RECORDED_API",
                    "title": "Approval recorded",
                    "message": f"Saved approved output pattern for node={node_id}.",
                    "node_id": node_id,
                })
    except Exception as approval_exc:
        try:
            await runtime._emit(req.run_id, {
                "type": "APPROVAL_RECORD_FAILED",
                "title": "Approval record failed",
                "message": str(approval_exc),
            })
        except Exception:
            pass

    asyncio.create_task(runtime.resume(req.run_id, req.decision, req.modified_result, req.feedback))
    return {"ok": True, "run_id": req.run_id}


@app.get("/api/events/{run_id}")
async def events(run_id: str):
    return StreamingResponse(event_bus.stream(run_id), media_type="text/event-stream")
