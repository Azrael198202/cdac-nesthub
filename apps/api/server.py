import asyncio
from typing import Any

from fastapi import FastAPI, UploadFile, File
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse, FileResponse
from pydantic import BaseModel
from pathlib import Path
from uuid import uuid4
import json
import base64

from ai_core.artifacts.artifact_registry import UploadedArtifactRegistry
from ai_core.artifacts.artifact_edit_service import ArtifactEditService
from ai_core.commands import CommandSetService

from ai_core.evolution.approval_learning import ApprovalLearningService
from ai_core.orchestration.workflow_runtime import WorkflowRuntime
from ai_core.events.event_bus import event_bus
from auxiliary_brain.studio import AgentStudioService
from ai_core.runtime.bootstrap import RuntimeBootstrapService
from ai_core.runtime.modeling.user_model_selection import UserModelSelectionStore
from ai_core.context.session_memory_store import SessionMemoryStore
from ai_core.knowledge.knowledge_service import KnowledgeService
from ai_core.config.paths import RUNTIME_DOWNLOADS
from ai_core.tools.runtime_registered_tool_service import RuntimeRegisteredToolService
from ai_core.runtime.approval_policy_store import RuntimeApprovalPolicyStore
from ai_core.graph.graph_visualization import GraphVisualStateBuilder
from ai_core.runtime.observability.runtime_console import emit_console_event, list_console_sources, read_console_source

import traceback
approval_learning = ApprovalLearningService()
app = FastAPI()
runtime = WorkflowRuntime()
studio_service = AgentStudioService()
bootstrap_service = RuntimeBootstrapService()
model_selection_store = UserModelSelectionStore()
session_store = SessionMemoryStore()
graph_visual_builder = GraphVisualStateBuilder()
knowledge_service = KnowledgeService()
registered_tool_service = RuntimeRegisteredToolService()
approval_policy_store = RuntimeApprovalPolicyStore()


def _write_api_error_log(*, area: str, exc: Exception, context: dict[str, Any] | None = None) -> None:
    try:
        path = Path("runtime") / "logs" / "api_errors.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        event = {
            "event_type": "api_error",
            "area": area,
            "error_type": exc.__class__.__name__,
            "error": str(exc)[-2000:],
            "traceback": traceback.format_exc(limit=12),
            "context": context or {},
        }
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=False) + "\n")
    except Exception:
        return


class ChatRequest(BaseModel):
    message: str
    local_model: str | None = None
    session_id: str | None = None


class ConversationFeedbackRequest(BaseModel):
    session_id: str
    run_id: str
    rating: str
    note: str | None = None




class RegisteredToolExecuteRequest(BaseModel):
    tool_id: str
    input_data: Any | None = None
    profile_id: str | None = None
    approval_confirmed: bool = False
    remember_approval: bool = False




class RuntimeApprovalPolicyRequest(BaseModel):
    tool_id: str
    profile_id: str | None = None
    mode: str = "always"

class RuntimeToolProfileRequest(BaseModel):
    tool_id: str
    profile_id: str | None = None
    config: dict[str, Any] | None = None
    secrets: dict[str, Any] | None = None

class AgentStudioRequest(BaseModel):
    message: str
    provided_inputs: dict[str, Any] | None = None
    uploaded_artifacts: list[dict[str, Any]] | None = None
    session_id: str | None = None




class KnowledgeQueryRequest(BaseModel):
    query: str
    knowledge_base_id: str | None = None
    limit: int = 5
    synthesize: bool = True
    response_profile: dict[str, Any] | None = None

class AgentStudioSecretRequest(BaseModel):
    key: str
    value: str


class VideoGenerationSetupRequest(BaseModel):
    provided_inputs: dict[str, Any] | None = None


class ClientErrorRequest(BaseModel):
    url: str | None = None
    error: str | None = None
    elapsed_ms: int | None = None
    hint: str | None = None
    context: dict[str, Any] | None = None


class ArtifactEditRequest(BaseModel):
    instruction: str
    feedback: str | None = None
    base_proposal_id: str | None = None
    new_content: str | None = None


class ArtifactProposalActionRequest(BaseModel):
    feedback: str | None = None
    new_content: str | None = None


class ArtifactUploadItem(BaseModel):
    filename: str
    content_base64: str
    content_type: str | None = None


class ArtifactUploadJsonRequest(BaseModel):
    files: list[ArtifactUploadItem]


class AgentStudioModelSelectionRequest(BaseModel):
    mode: str
    initial_model_id: str | None = None
    selected_local_model_id: str | None = None
    selected_api_model_id: str | None = None
    selected_provider: str | None = None
    custom_endpoint: str | None = None
    allow_escalation: bool = True
    ask_for_missing_keys_at_start: bool = True




class CommandSetUpdateRequest(BaseModel):
    commands: list[dict[str, Any]] | None = None
    # Backward-compatible input only. CommandSetService migrates this into
    # commands[] before saving; routing never reads command_phrases directly.
    command_phrases: dict[str, list[str]] | None = None
    feedback_intents: dict[str, list[str]] | None = None
    raw_update: dict[str, Any] | None = None


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






@app.get("/settings")
async def runtime_settings_home():
    html = open("apps/web/settings.html", "r", encoding="utf-8").read()
    return HTMLResponse(
        html,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@app.get("/graph-runtime")
async def graph_runtime_home():
    html = open("apps/web/graph_runtime.html", "r", encoding="utf-8").read()
    return HTMLResponse(
        html,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@app.get("/runtime-console")
async def runtime_console_home():
    html = open("apps/web/runtime_console.html", "r", encoding="utf-8").read()
    return HTMLResponse(
        html,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@app.get("/api/runtime-console/sources")
async def runtime_console_sources():
    return JSONResponse({"ok": True, "sources": list_console_sources()})


@app.get("/api/runtime-console/read")
async def runtime_console_read(source: str | None = None, cursor: int = 0, limit_bytes: int = 65536, tail: bool = False):
    return JSONResponse(read_console_source(source, cursor=cursor, limit_bytes=limit_bytes, tail=tail))


@app.get("/api/graph-runtime/state")
async def graph_runtime_state(graph_id: str | None = None):
    try:
        snapshot = studio_service.snapshot()
        graphs = [item for item in snapshot.get("task_graphs", []) if isinstance(item, dict)] if isinstance(snapshot, dict) else []
        if not graphs and not graph_id:
            return JSONResponse({
                "ok": True,
                "status": "idle",
                "graph_id": "runtime_graph",
                "nodes": [],
                "edges": [],
                "lanes": [],
                "events": [],
                "summary": {"node_count": 0, "edge_count": 0, "completed_count": 0, "running_count": 0, "failed_count": 0, "skipped_count": 0, "reused_count": 0, "repair_count": 0},
                "repair_plan": [],
                "available_graphs": [],
                "source": "agent_studio_snapshot",
            })
        visual_state = graph_visual_builder.from_snapshot(snapshot, graph_id=graph_id)
        payload = graph_visual_builder.to_dict(visual_state)
        payload["source"] = "agent_studio_snapshot"
        payload["available_graphs"] = [
            {
                "graph_id": str(item.get("graph_id") or item.get("task_name") or item.get("id") or "runtime_graph"),
                "task_name": str(item.get("task_name") or item.get("graph_id") or item.get("id") or "runtime_graph"),
                "status": str(item.get("status") or "pending"),
            }
            for item in snapshot.get("task_graphs", [])
            if isinstance(item, dict)
        ]
        return JSONResponse(payload)
    except Exception as exc:
        return JSONResponse(
            {
                "ok": False,
                "status": "failed",
                "graph_id": graph_id or "runtime_graph",
                "nodes": [],
                "edges": [],
                "lanes": [],
                "events": [{"event": "graph_state_load_failed", "error": str(exc)}],
                "summary": {"node_count": 0, "edge_count": 0, "completed_count": 0, "running_count": 0, "failed_count": 1},
                "repair_plan": [{"action": "check_runtime_snapshot", "error": str(exc)}],
                "source": "agent_studio_snapshot",
            },
            status_code=200,
        )




@app.get("/knowledge")
async def knowledge_home():
    html = open("apps/web/knowledge.html", "r", encoding="utf-8").read()
    return HTMLResponse(
        html,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@app.get("/api/knowledge/status")
async def knowledge_status():
    return JSONResponse({"ok": True, "status": knowledge_service.status()})


@app.get("/api/knowledge/documents")
async def knowledge_documents(knowledge_base_id: str | None = None):
    return JSONResponse(knowledge_service.list_documents(knowledge_base_id=knowledge_base_id))


@app.post("/api/knowledge/upload")
async def knowledge_upload(files: list[UploadFile] = File(...), knowledge_base_id: str | None = None):
    upload_dir = Path("runtime") / "knowledge" / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    for file in files:
        safe_name = Path(file.filename or "uploaded_document").name
        target = upload_dir / f"kb_{uuid4().hex[:12]}_{safe_name}"
        target.write_bytes(await file.read())
        try:
            results.append(knowledge_service.ingest_file(
                file_path=target,
                original_name=safe_name,
                content_type=file.content_type or "application/octet-stream",
                knowledge_base_id=knowledge_base_id or "default",
            ))
        except Exception as exc:
            results.append({
                "ok": False,
                "filename": safe_name,
                "status": "failed",
                "error": str(exc),
            })
    return JSONResponse({"ok": all(item.get("ok") for item in results), "results": results, "documents": knowledge_service.list_documents(knowledge_base_id=knowledge_base_id or "default").get("documents", [])})


@app.post("/api/knowledge/query")
async def knowledge_query(req: KnowledgeQueryRequest):
    payload = await knowledge_service.rag_answer(
        req.query,
        knowledge_base_id=req.knowledge_base_id,
        limit=req.limit,
        synthesize=req.synthesize,
        response_profile=req.response_profile,
    )
    return JSONResponse(payload)

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






artifact_registry = UploadedArtifactRegistry()
artifact_edit_service = ArtifactEditService()
command_set_service = CommandSetService()

def _read_artifact_registry() -> list[dict[str, Any]]:
    return artifact_registry.list()

def _write_artifact_registry(items: list[dict[str, Any]]) -> None:
    artifact_registry.write(items)

@app.get("/api/agent-studio/artifacts")
async def agent_studio_artifacts():
    return JSONResponse({"ok": True, "artifacts": _read_artifact_registry()})

def _store_uploaded_artifact_items(items: list[dict[str, Any]]) -> dict[str, Any]:
    upload_dir = Path("runtime") / "uploads" / "files"
    upload_dir.mkdir(parents=True, exist_ok=True)
    registry = _read_artifact_registry()
    existing_ids = {str(item.get("artifact_id")) for item in registry if isinstance(item, dict)}
    created: list[dict[str, Any]] = []
    for source in items:
        original_name = Path(str(source.get("filename") or "uploaded_file")).name
        suffix = Path(original_name).suffix
        artifact_id = f"artifact_{uuid4().hex[:12]}"
        while artifact_id in existing_ids:
            artifact_id = f"artifact_{uuid4().hex[:12]}"
        existing_ids.add(artifact_id)
        stored_name = f"{artifact_id}{suffix}"
        target = upload_dir / stored_name
        content = bytes(source.get("content") or b"")
        target.write_bytes(content)
        item = {
            "artifact_id": artifact_id,
            "name": original_name,
            "filename": original_name,
            "path": str(target),
            "mime_type": str(source.get("content_type") or "application/octet-stream"),
            "size_bytes": len(content),
            "role": "method_candidate",
            "source": str(source.get("source") or "agent_studio_upload"),
        }
        registry.append(item)
        created.append(item)
    _write_artifact_registry(registry)
    return {"ok": True, "artifacts": created, "registry": registry}


@app.post("/api/agent-studio/artifacts")
async def agent_studio_upload_artifacts(files: list[UploadFile] = File(...)):
    items: list[dict[str, Any]] = []
    for file in files:
        items.append({
            "filename": file.filename or "uploaded_file",
            "content_type": file.content_type or "application/octet-stream",
            "content": await file.read(),
            "source": "agent_studio_upload_multipart",
        })
    return JSONResponse(_store_uploaded_artifact_items(items))


@app.post("/api/agent-studio/artifacts-json")
async def agent_studio_upload_artifacts_json(req: ArtifactUploadJsonRequest):
    items: list[dict[str, Any]] = []
    for file in req.files:
        try:
            content = base64.b64decode(file.content_base64.encode("ascii"), validate=True)
        except Exception as exc:
            return JSONResponse({"ok": False, "message": f"invalid base64 content for {file.filename}: {exc}"}, status_code=400)
        items.append({
            "filename": file.filename or "uploaded_file",
            "content_type": file.content_type or "application/octet-stream",
            "content": content,
            "source": "agent_studio_upload_json",
        })
    return JSONResponse(_store_uploaded_artifact_items(items))


@app.post("/api/agent-studio/artifacts/{artifact_id}/edit-proposal")
async def agent_studio_artifact_edit_proposal(artifact_id: str, req: ArtifactEditRequest):
    payload = await artifact_edit_service.propose_edit(
        artifact_id=artifact_id,
        instruction=req.instruction,
        feedback=req.feedback or "",
        base_proposal_id=req.base_proposal_id or "",
        new_content=req.new_content,
    )
    return JSONResponse(payload, status_code=200 if payload.get("ok") else 400)




@app.get("/api/downloads/{download_id}/{filename}")
async def download_runtime_file(download_id: str, filename: str):
    safe_id = Path(download_id).name
    safe_name = Path(filename).name
    path = (RUNTIME_DOWNLOADS / safe_id / safe_name).resolve()
    root = RUNTIME_DOWNLOADS.resolve()
    try:
        path.relative_to(root)
    except ValueError:
        return JSONResponse({"ok": False, "status": "invalid_path"}, status_code=400)
    if not path.exists() or not path.is_file():
        return JSONResponse({"ok": False, "status": "not_found"}, status_code=404)
    return FileResponse(str(path), filename=safe_name)

@app.get("/api/agent-studio/artifact-edit/{proposal_id}/download")
async def agent_studio_artifact_edit_download(proposal_id: str):
    meta = artifact_edit_service._read_meta(proposal_id)
    if not meta:
        return JSONResponse({"ok": False, "status": "not_found"}, status_code=404)
    path = artifact_edit_service._safe_path(str(meta.get("draft_path") or ""))
    if not path or not path.exists():
        return JSONResponse({"ok": False, "status": "missing_file"}, status_code=404)
    return FileResponse(str(path), filename=Path(str(meta.get("artifact_name") or path.name)).name)


@app.post("/api/agent-studio/artifact-edit/{proposal_id}/confirm")
async def agent_studio_artifact_edit_confirm(proposal_id: str, req: ArtifactProposalActionRequest | None = None):
    if req and req.new_content is not None:
        meta = artifact_edit_service._read_meta(proposal_id)
        if meta:
            draft_path = artifact_edit_service._safe_path(str(meta.get("draft_path") or ""))
            if draft_path:
                draft_path.write_text(req.new_content, encoding="utf-8")
    payload = artifact_edit_service.confirm(proposal_id)
    return JSONResponse(payload, status_code=200 if payload.get("ok") else 400)


@app.post("/api/agent-studio/artifact-edit/{proposal_id}/cancel")
async def agent_studio_artifact_edit_cancel(proposal_id: str):
    payload = artifact_edit_service.cancel(proposal_id)
    return JSONResponse(payload, status_code=200 if payload.get("ok") else 400)


@app.post("/api/agent-studio/artifact-edit/{proposal_id}/revise")
async def agent_studio_artifact_edit_revise(proposal_id: str, req: ArtifactProposalActionRequest):
    meta = artifact_edit_service._read_meta(proposal_id)
    if not meta:
        return JSONResponse({"ok": False, "status": "not_found"}, status_code=404)
    payload = await artifact_edit_service.propose_edit(
        artifact_id=str(meta.get("artifact_id") or ""),
        instruction=str(meta.get("instruction") or ""),
        feedback=req.feedback or "",
        base_proposal_id=proposal_id,
    )
    return JSONResponse(payload, status_code=200 if payload.get("ok") else 400)


@app.get("/api/agent-studio/model-selection")
async def agent_studio_model_selection_state():
    return JSONResponse(model_selection_store.state())


@app.post("/api/agent-studio/model-selection")
async def agent_studio_model_selection_update(req: AgentStudioModelSelectionRequest):
    return JSONResponse(model_selection_store.update(req.dict()))



@app.get("/api/agent-studio/command-set")
async def agent_studio_command_set():
    return JSONResponse(command_set_service.list_commands())


@app.post("/api/agent-studio/command-set")
async def agent_studio_command_set_update(req: CommandSetUpdateRequest):
    update = req.raw_update if isinstance(req.raw_update, dict) else {}
    if req.commands is not None:
        update.setdefault("commands", []).extend(req.commands)
    if req.command_phrases is not None:
        # Legacy client input. Service migrates it to commands[].
        update.setdefault("command_phrases", {}).update(req.command_phrases)
    if req.feedback_intents is not None:
        update.setdefault("feedback_intents", {}).update(req.feedback_intents)
    payload = command_set_service.update_runtime(update)
    try:
        studio_service.router.reload()
    except Exception:
        pass
    return JSONResponse(payload)




@app.get("/api/agent-studio/sessions")
async def agent_studio_sessions(limit: int = 50):
    return JSONResponse({"ok": True, "sessions": session_store.list_sessions(limit=limit)})


@app.post("/api/agent-studio/sessions")
async def agent_studio_create_session(payload: dict[str, Any] | None = None):
    meta = payload if isinstance(payload, dict) else {}
    sid = session_store.start_or_get_session(None, metadata={"title": str(meta.get("title") or "New session")})
    return JSONResponse({"ok": True, "session_id": sid, "session": session_store.get_session_snapshot(sid)})


@app.get("/api/agent-studio/sessions/{session_id}")
async def agent_studio_session_snapshot(session_id: str, limit: int = 20):
    return JSONResponse({"ok": True, "session": session_store.get_session_snapshot(session_id, limit=limit)})


@app.post("/api/agent-studio/sessions/{session_id}/rename")
async def agent_studio_rename_session(session_id: str, payload: dict[str, Any]):
    return JSONResponse({"ok": True, "session": session_store.rename_session(session_id, str(payload.get("title") or ""))})



@app.get("/api/agent-studio/runtime-tools")
async def agent_studio_runtime_tools():
    return JSONResponse({"ok": True, "tools": registered_tool_service.list_tools()})


@app.get("/api/runtime/settings")
async def runtime_settings():
    return JSONResponse({
        "ok": True,
        "tools": registered_tool_service.list_tools(),
        "profiles": registered_tool_service.list_profiles(),
        "approval_policies": approval_policy_store.list_policies(),
    })


@app.post("/api/runtime/settings/tool-approval")
async def runtime_settings_tool_approval(req: RuntimeApprovalPolicyRequest):
    payload = approval_policy_store.set_tool_policy(
        tool_id=req.tool_id,
        profile_id=req.profile_id or "default",
        mode=req.mode or "always",
    )
    return JSONResponse({"ok": True, "policy": payload})


@app.get("/api/agent-studio/runtime-tool-profiles")
async def agent_studio_runtime_tool_profiles(tool_id: str | None = None):
    return JSONResponse({"ok": True, "profiles": registered_tool_service.list_profiles(tool_id)})


@app.post("/api/agent-studio/runtime-tool-profiles")
async def agent_studio_save_runtime_tool_profile(req: RuntimeToolProfileRequest):
    try:
        payload = registered_tool_service.configure_tool_profile(
            tool_id=req.tool_id,
            profile_id=req.profile_id or "default",
            config=req.config if req.config is not None else {},
            secrets=req.secrets if req.secrets is not None else {},
        )
        status = 200 if payload.get("ok") else 400
        return JSONResponse(payload, status_code=status)
    except Exception as exc:
        _write_api_error_log(area="agent_studio_save_runtime_tool_profile", exc=exc, context={"tool_id": req.tool_id})
        return JSONResponse({"ok": False, "status": "failed", "error": {"type": exc.__class__.__name__, "message": str(exc)}}, status_code=500)


@app.post("/api/agent-studio/runtime-tools/execute")
async def agent_studio_execute_runtime_tool(req: RegisteredToolExecuteRequest):
    try:
        payload = registered_tool_service.execute_tool(
            tool_id=req.tool_id,
            input_data=req.input_data if req.input_data is not None else {},
            run_id="agent_studio_registered_tool",
            profile_id=req.profile_id or "default",
            approval_confirmed=bool(req.approval_confirmed),
            remember_approval=bool(req.remember_approval),
        )
        status = 200 if payload.get("ok") else 400
        return JSONResponse(payload, status_code=status)
    except Exception as exc:
        _write_api_error_log(area="agent_studio_execute_runtime_tool", exc=exc, context={"tool_id": req.tool_id})
        return JSONResponse({"ok": False, "status": "failed", "error": {"type": exc.__class__.__name__, "message": str(exc)}}, status_code=500)

@app.get("/api/agent-studio/state")
async def agent_studio_state():
    return JSONResponse(studio_service.snapshot())


@app.post("/api/agent-studio/message")
async def agent_studio_message(req: AgentStudioRequest):
    try:
        active_session_id = session_store.start_or_get_session(req.session_id, metadata={"surface": "agent_studio"})
        payload = await studio_service.handle_message(req.message, provided_inputs=req.provided_inputs, uploaded_artifacts=req.uploaded_artifacts, session_id=active_session_id)
        if isinstance(payload, dict):
            payload.setdefault("session_id", active_session_id)
            final_answer = str(payload.get("final_answer") or payload.get("message") or payload.get("status") or "")
            if final_answer.strip():
                session_store.append_turn(
                    session_id=active_session_id,
                    run_id=str(payload.get("run_id") or payload.get("resumed_from_run_id") or payload.get("task_name") or "studio_run"),
                    user_input=req.message,
                    final_answer=final_answer,
                    stage_results={"agent_studio_payload": payload},
                    metadata={"action": str(payload.get("action") or "")},
                )
                payload["session_boundary"] = session_store.boundary_status(active_session_id)
        return JSONResponse(payload)
    except Exception as exc:
        _write_api_error_log(area="agent_studio_message", exc=exc, context={"session_id": req.session_id, "message_preview": str(req.message or "")[:300]})
        return JSONResponse(
            {
                "ok": False,
                "status": "failed",
                "error": {
                    "type": exc.__class__.__name__,
                    "message": str(exc),
                },
                "diagnostic_log": "runtime/logs/api_errors.jsonl",
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




async def _apply_video_generation_setup(req: VideoGenerationSetupRequest):
    try:
        from ai_core.media.video_generation_setup_wizard import VideoGenerationSetupWizard
        payload = VideoGenerationSetupWizard().apply_inputs(req.provided_inputs or {})
        return JSONResponse(payload, status_code=200 if payload.get("ok") else 400)
    except Exception as exc:
        _write_api_error_log(area="video_generation_setup", exc=exc, context={"provided_keys": list((req.provided_inputs or {}).keys())})
        return JSONResponse({"ok": False, "status": "failed", "error": str(exc), "message": str(exc), "diagnostic_log": "runtime/logs/api_errors.jsonl"}, status_code=500)

@app.post("/api/agent-studio/video-generation/setup")
async def agent_studio_video_generation_setup(req: VideoGenerationSetupRequest):
    return await _apply_video_generation_setup(req)

@app.post("/api/agent-studio/video_generation/setup")
async def agent_studio_video_generation_setup_alias(req: VideoGenerationSetupRequest):
    return await _apply_video_generation_setup(req)

@app.post("/api/video-generation/setup")
async def video_generation_setup_alias(req: VideoGenerationSetupRequest):
    return await _apply_video_generation_setup(req)

@app.post("/api/agent-studio/client-error")
async def agent_studio_client_error(req: ClientErrorRequest):
    try:
        path = Path("runtime") / "logs" / "frontend_errors.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        event = {
            "event_type": "frontend_error",
            "area": "agent_studio",
            "url": req.url,
            "error": req.error,
            "elapsed_ms": req.elapsed_ms,
            "hint": req.hint,
            "context": req.context or {},
        }
        path.open("a", encoding="utf-8").write(json.dumps(event, ensure_ascii=False)+"\n")
    except Exception:
        pass
    return JSONResponse({"ok": True, "status": "logged"})

@app.post("/api/agent-studio/resume-run")
async def agent_studio_resume_run(req: AgentStudioResumeRunRequest):
    return JSONResponse(await studio_service.resume_run(req.run_id, provided_inputs=req.provided_inputs))


@app.get("/api/version")
async def version():
    return JSONResponse({"version": "v9.0-execution-reuse-fix1", "name": "execution-reuse-ui-runtime"})


@app.post("/api/chat")
async def chat(req: ChatRequest):
    run_id, state = await runtime.prepare(req.message, local_model=req.local_model)
    state["session_id"] = req.session_id or state.get("session_id")
    asyncio.create_task(runtime.run_prepared(state))
    return {"run_id": run_id}


@app.post("/api/conversation/feedback")
async def conversation_feedback(req: ConversationFeedbackRequest):
    from ai_core.context.session_memory_store import SessionMemoryStore
    from ai_core.context.vector_memory_store import VectorMemoryStore

    store = SessionMemoryStore()
    record = store.record_feedback(
        session_id=req.session_id,
        run_id=req.run_id,
        rating=req.rating,
        note=req.note or "",
    )
    promoted = False
    if str(req.rating or "").strip().lower() in {"good", "great", "excellent", "useful", "優良", "高品質", "好"}:
        window = store.load_context_window(req.session_id, limit=3)
        text = window.rolling_summary or "\n".join(
            [str(t.get("user_input", "")) + "\n" + str(t.get("final_answer", "")) for t in window.recent_turns]
        )
        VectorMemoryStore().add_text(
            text=text,
            metadata={"session_id": req.session_id, "run_id": req.run_id, "feedback_id": record.get("feedback_id")},
            memory_type="approved_conversation_pattern",
            usage_scope="retrieval_context",
        )
        promoted = True
    return JSONResponse({"ok": True, "feedback": record, "promoted_to_local_memory": promoted})


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
