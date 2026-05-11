from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from ai_core.api.schemas import ApiKeyRequest, ChatRequest, ChatResponse
from ai_core.bootstrap.runtime_bootstrap import RuntimeBootstrap
from ai_core.config.io import read_json, write_json
from ai_core.config.paths import ROOT_DIR, RUNTIME_SECRETS_DIR
from ai_core.orchestration.engine import VerifiedOrchestrationEngine


def create_app() -> FastAPI:
    RuntimeBootstrap().ensure_runtime_base()
    app = FastAPI(title="Verified Self-Evolving AI Core")
    web_dir = ROOT_DIR / "apps" / "web"
    app.mount("/static", StaticFiles(directory=str(web_dir)), name="static")

    @app.get("/", response_class=HTMLResponse)
    async def index():
        return (web_dir / "index.html").read_text(encoding="utf-8")

    @app.post("/api/chat", response_model=ChatResponse)
    async def chat(req: ChatRequest):
        engine = VerifiedOrchestrationEngine()
        state = await engine.run(req.message, interactive=req.interactive, human_feedback=req.human_feedback)
        return ChatResponse(final_answer=state.get("final_answer", ""), trace_file=state.get("trace_file"), state=state)

    @app.post("/api/keys")
    async def save_key(req: ApiKeyRequest):
        data = read_json(RUNTIME_SECRETS_DIR / "local_secrets.json", {"providers": {}})
        data.setdefault("providers", {})[req.provider] = {"api_key": req.api_key}
        write_json(RUNTIME_SECRETS_DIR / "local_secrets.json", data)
        return {"ok": True, "provider": req.provider}

    @app.get("/api/runtime/status")
    async def status():
        return {"ok": True, "runtime_initialized": True}

    return app
