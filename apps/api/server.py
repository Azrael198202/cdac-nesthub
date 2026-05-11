import asyncio
from typing import Any
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel
from ai_core.orchestration.workflow_runtime import WorkflowRuntime
from ai_core.events.event_bus import event_bus
app=FastAPI(); runtime=WorkflowRuntime()
class ChatRequest(BaseModel): message: str
class ResumeRequest(BaseModel):
    run_id: str; decision: str='approve'; modified_result: dict[str,Any]|None=None; feedback: str|None=None
@app.get('/')
async def home(): return HTMLResponse(open('apps/web/index.html','r',encoding='utf-8').read())
@app.post('/api/chat')
async def chat(req: ChatRequest): return {'run_id': await runtime.start(req.message)}
@app.post('/api/resume')
async def resume(req: ResumeRequest): asyncio.create_task(runtime.resume(req.run_id,req.decision,req.modified_result,req.feedback)); return {'ok':True,'run_id':req.run_id}
@app.get('/api/events/{run_id}')
async def events(run_id: str): return StreamingResponse(event_bus.stream(run_id), media_type='text/event-stream')
