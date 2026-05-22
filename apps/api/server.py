import asyncio
from typing import Any

from fastapi import FastAPI, UploadFile, File
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from pydantic import BaseModel
from pathlib import Path
from uuid import uuid4
import json

from ai_core.evolution.approval_learning import ApprovalLearningService
from ai_core.orchestration.workflow_runtime import WorkflowRuntime
from ai_core.events.event_bus import event_bus
from auxiliary_brain.studio import AgentStudioService
from ai_core.runtime.bootstrap import RuntimeBootstrapService
from ai_core.runtime.modeling.user_model_selection import UserModelSelectionStore

import traceback
approval_learning = ApprovalLearningService()
app = FastAPI()
runtime = WorkflowRuntime()
studio_service = AgentStudioService()
bootstrap_service = RuntimeBootstrapService()
model_selection_store = UserModelSelectionStore()


class ChatRequest(BaseModel):
    message: str
    local_model: str | None = None


class AgentStudioRequest(BaseModel):
    message: str
    provided_inputs: dict[str, Any] | None = None
    uploaded_artifacts: list[dict[str, Any]] | None = None


class AgentStudioSecretRequest(BaseModel):
    key: str
    value: str


class AgentStudioModelSelectionRequest(BaseModel):
    mode: str
    initial_model_id: str | None = None
    selected_local_model_id: str | None = None
    selected_api_model_id: str | None = None
    allow_escalation: bool = True
    ask_for_missing_keys_at_start: bool = True


class AgentStudioResumeRunRequest(BaseModel):
    run_id: str
    provided_inputs: dict[str, Any] | None = None


class ResumeRequest(BaseModel):
    run_id: str
    decision: str = "approve"
    modified_result: dict[str, Any] | None = None
    feedback: str | None = None


@app.on_event("startup")
async def runtime_bootstrap_on_startup():
    # Fast boot rule: API startup must not wait for model/provider preparation.
    # Runtime topology bootstrap is seed/config based and is scheduled in the
    # background. Any failure is handled by runtime fallback paths.
    async def _background_bootstrap():
        try:
            await bootstrap_service.bootstrap(force=False)
        except Exception:
            pass

    asyncio.create_task(_background_bootstrap())


@app.post("/api/runtime/bootstrap")
async def runtime_bootstrap():
    return JSONResponse(await bootstrap_service.bootstrap(force=True))


@app.get("/api/runtime/bootstrap")
async def runtime_bootstrap_state():
    return JSONResponse(await bootstrap_service.bootstrap(force=False))


@app.get("/")
async def home():
    html = open("apps/web/index.html", "r", encoding="utf-8").read()
    return HTMLResponse(
        html,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
            "X-AI-Core-Version": "v3.1.2",
        },
    )




@app.get("/agent-studio")
async def agent_studio_home():
    html = open("apps/web/agent_studio.html", "r", encoding="utf-8").read()
    return HTMLResponse(
        html,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )






def _artifact_registry_path() -> Path:
    path = Path("runtime") / "uploads" / "artifact_registry.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text("[]", encoding="utf-8")
    return path

def _read_artifact_registry() -> list[dict[str, Any]]:
    path = _artifact_registry_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []

def _write_artifact_registry(items: list[dict[str, Any]]) -> None:
    path = _artifact_registry_path()
    path.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")

@app.get("/api/agent-studio/artifacts")
async def agent_studio_artifacts():
    return JSONResponse({"ok": True, "artifacts": _read_artifact_registry()})

@app.post("/api/agent-studio/artifacts")
async def agent_studio_upload_artifacts(files: list[UploadFile] = File(...)):
    upload_dir = Path("runtime") / "uploads" / "files"
    upload_dir.mkdir(parents=True, exist_ok=True)
    registry = _read_artifact_registry()
    existing_ids = {str(item.get("artifact_id")) for item in registry if isinstance(item, dict)}
    created: list[dict[str, Any]] = []
    for file in files:
        original_name = Path(file.filename or "uploaded_file").name
        suffix = Path(original_name).suffix
        artifact_id = f"artifact_{uuid4().hex[:12]}"
        while artifact_id in existing_ids:
            artifact_id = f"artifact_{uuid4().hex[:12]}"
        existing_ids.add(artifact_id)
        stored_name = f"{artifact_id}{suffix}"
        target = upload_dir / stored_name
        content = await file.read()
        target.write_bytes(content)
        item = {
            "artifact_id": artifact_id,
            "name": original_name,
            "filename": original_name,
            "path": str(target),
            "mime_type": file.content_type or "application/octet-stream",
            "size_bytes": len(content),
            "role": "method_candidate",
            "source": "agent_studio_upload",
        }
        registry.append(item)
        created.append(item)
    _write_artifact_registry(registry)
    return JSONResponse({"ok": True, "artifacts": created, "registry": registry})

@app.get("/api/agent-studio/model-selection")
async def agent_studio_model_selection_state():
    return JSONResponse(model_selection_store.state())


@app.post("/api/agent-studio/model-selection")
async def agent_studio_model_selection_update(req: AgentStudioModelSelectionRequest):
    return JSONResponse(model_selection_store.update(req.dict()))

@app.get("/api/agent-studio/state")
async def agent_studio_state():
    return JSONResponse(studio_service.snapshot())


@app.post("/api/agent-studio/message")
async def agent_studio_message(req: AgentStudioRequest):
    try:
        payload = await studio_service.handle_message(req.message, provided_inputs=req.provided_inputs, uploaded_artifacts=req.uploaded_artifacts)
        return JSONResponse(payload)
    except Exception as exc:
        return JSONResponse(
            {
                "ok": False,
                "status": "failed",
                "error": {
                    "type": exc.__class__.__name__,
                    "message": str(exc),
                },
                "traceback": traceback.format_exc(limit=8),
            },
            status_code=500,
        )


@app.post("/api/agent-studio/secret")
async def agent_studio_secret(req: AgentStudioSecretRequest):
    from ai_core.secrets.secret_store import SecretStore

    key = (req.key or "runtime_access_key").strip() or "runtime_access_key"
    value = (req.value or "").strip()
    if not value:
        return JSONResponse({"ok": False, "status": "blocked", "message": "Secret value is required."}, status_code=400)
    SecretStore().set(key, value)
    return JSONResponse({"ok": True, "status": "saved", "key": key, "path": "runtime/configs/secrets/secrets.json"})


@app.post("/api/agent-studio/resume-run")
async def agent_studio_resume_run(req: AgentStudioResumeRunRequest):
    return JSONResponse(await studio_service.resume_run(req.run_id, provided_inputs=req.provided_inputs))


@app.get("/api/version")
async def version():
    return JSONResponse({"version": "v3.1.2", "name": "model-provider-preflight"})


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
