import asyncio
from typing import Any

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from pydantic import BaseModel

from ai_core.evolution.approval_learning import ApprovalLearningService
from ai_core.orchestration.workflow_runtime import WorkflowRuntime
from ai_core.events.event_bus import event_bus
from auxiliary_brain.studio.service import AgentStudioService

approval_learning = ApprovalLearningService()
app = FastAPI()
runtime = WorkflowRuntime()
studio_service = AgentStudioService()


@app.on_event("startup")
async def agent_studio_runtime_loop_startup():
    async def _loop():
        while True:
            try:
                studio_service.run_due_tasks()
            except Exception:
                pass
            await asyncio.sleep(1)
    asyncio.create_task(_loop())



class ChatRequest(BaseModel):
    message: str
    local_model: str | None = None


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
            "X-AI-Core-Version": "v70.29",
        },
    )


@app.get("/agent-studio")
async def agent_studio_page():
    html = open("apps/web/agent_studio.html", "r", encoding="utf-8").read()
    return HTMLResponse(
        html,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
            "X-Runtime-Page": "agent-studio",
        },
    )


class StudioMessageRequest(BaseModel):
    message: str
    provided_inputs: dict[str, Any] | None = None


class StudioRuntimeInputRequest(BaseModel):
    input_id: str
    value: str


@app.get("/api/agent-studio/state")
async def agent_studio_state():
    return JSONResponse(studio_service.snapshot())


@app.get("/api/agent-studio/commands")
async def agent_studio_commands():
    return JSONResponse(studio_service.command_config.load())


@app.post("/api/agent-studio/message")
async def agent_studio_message(req: StudioMessageRequest):
    return JSONResponse(await studio_service.handle_message_async(req.message, provided_inputs=req.provided_inputs))


@app.post("/api/agent-studio/runtime-input")
async def agent_studio_runtime_input(req: StudioRuntimeInputRequest):
    return JSONResponse(studio_service.accept_runtime_input(req.input_id, req.value))


@app.post("/api/agent-studio/task/start")
async def agent_studio_task_start(req: StudioMessageRequest):
    return JSONResponse(studio_service.update_latest_task_graph("running", req.message))


@app.post("/api/agent-studio/task/run-due")
async def agent_studio_task_run_due():
    return JSONResponse(studio_service.run_due_tasks())


@app.post("/api/agent-studio/task/stop")
async def agent_studio_task_stop(req: StudioMessageRequest):
    return JSONResponse(studio_service.update_latest_task_graph("stopped", req.message))


@app.get("/api/version")
async def version():
    return JSONResponse({"version": "v70.29", "name": "structured_fact_synthesis_and_credential_recovery_v70_29"})


@app.post("/api/chat")
async def chat(req: ChatRequest):
    run_id, state = await runtime.prepare(req.message, local_model=req.local_model)
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
