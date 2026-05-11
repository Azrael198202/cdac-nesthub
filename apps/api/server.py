from __future__ import annotations

import os
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from ai_core.orchestration.workflow_engine import WorkflowEngine
from ai_core.runtime.paths import PROJECT_ROOT, RUNTIME_DIR
from ai_core.runtime.bootstrap import RuntimeBootstrapper
from ai_core.runtime.file_store import FileStore
from apps.api.schemas import ChatRequest, SettingsRequest

app = FastAPI(title="Pure Runtime AI Core")
web_dir = PROJECT_ROOT / "apps" / "web"
app.mount("/static", StaticFiles(directory=str(web_dir)), name="static")


@app.get("/")
def index():
    return FileResponse(web_dir / "index.html")


@app.get("/api/status")
def status():
    s = RuntimeBootstrapper().bootstrap()
    return s.__dict__


@app.post("/api/settings")
def save_settings(req: SettingsRequest):
    RuntimeBootstrapper().bootstrap()
    store = FileStore()
    routes_path = RUNTIME_DIR / "configs/models/model_routes.yaml"
    routes = store.read_yaml(routes_path, {})
    if req.provider:
        if req.provider == "openai":
            routes["selection_order"] = ["openai", "ollama", "local_rules"]
        elif req.provider == "ollama":
            routes["selection_order"] = ["ollama", "openai", "local_rules"]
        else:
            routes["selection_order"] = ["local_rules", "ollama", "openai"]
    if req.openai_model:
        routes.setdefault("providers", {}).setdefault("openai", {})["model"] = req.openai_model
    if req.ollama_model:
        routes.setdefault("providers", {}).setdefault("ollama", {})["model"] = req.ollama_model
    if req.ollama_base_url:
        routes.setdefault("providers", {}).setdefault("ollama", {})["base_url"] = req.ollama_base_url
    store.write_yaml(routes_path, routes)
    if req.openai_api_key:
        env_path = RUNTIME_DIR / "secrets/local.env"
        env_path.parent.mkdir(parents=True, exist_ok=True)
        env_path.write_text(f"OPENAI_API_KEY={req.openai_api_key}\n", encoding="utf-8")
        os.environ["OPENAI_API_KEY"] = req.openai_api_key
    return {"ok": True, "message": "settings saved to runtime"}


@app.post("/api/chat")
async def chat(req: ChatRequest):
    engine = WorkflowEngine()

    async def event_stream():
        async for event in engine.run(req.message):
            yield event.to_sse()

    return StreamingResponse(event_stream(), media_type="text/event-stream")


def run():
    # load local env if present
    env_path = RUNTIME_DIR / "secrets/local.env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
    uvicorn.run("apps.api.server:app", host="127.0.0.1", port=8000, reload=False)
