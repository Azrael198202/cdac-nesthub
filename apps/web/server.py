from __future__ import annotations
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel
from ai_core.orchestration.workflow_engine import WorkflowEngine

app = FastAPI(title="Runtime Visible AI Core")

class ChatRequest(BaseModel):
    message: str

@app.get("/", response_class=HTMLResponse)
def index():
    return HTMLResponse((__import__('pathlib').Path(__file__).parent / "index.html").read_text(encoding="utf-8"))

@app.post("/chat/stream")
async def chat_stream(req: ChatRequest):
    engine = WorkflowEngine()
    async def gen():
        async for event in engine.run_stream(req.message):
            yield event.to_sse()
    return StreamingResponse(gen(), media_type="text/event-stream")
