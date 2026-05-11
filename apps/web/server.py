from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from pydantic import BaseModel

from ai_core.runtime.bootstrap import RuntimeBootstrap
from ai_core.security.approval_service import ApprovalService
from ai_core.orchestration.workflow_engine import WorkflowEngine

approval_service = ApprovalService()


class ChatRequest(BaseModel):
    message: str


class ApprovalDecision(BaseModel):
    approval_id: str
    approved: bool
    comment: str = ""


def create_app() -> FastAPI:
    RuntimeBootstrap().ensure()
    app = FastAPI(title="Self-Bootstrapping AI Core")

    @app.get("/", response_class=HTMLResponse)
    async def index():
        return HTMLResponse(INDEX_HTML)

    @app.post("/api/chat/stream")
    async def chat_stream(req: ChatRequest):
        engine = WorkflowEngine(approval_service)

        async def events():
            async for ev in engine.run(req.message):
                yield ev.to_sse()

        return StreamingResponse(events(), media_type="text/event-stream")

    @app.post("/api/approval")
    async def decide(decision: ApprovalDecision):
        return JSONResponse(approval_service.decide(decision.approval_id, decision.approved, decision.comment))

    return app


INDEX_HTML = r'''
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Self-Bootstrapping AI Core</title>
  <style>
    * { box-sizing: border-box; }
    body { margin:0; font-family: Arial, sans-serif; background:#0b1020; color:#e5e7eb; }
    .layout { display:grid; grid-template-columns: 1fr 360px; height:100vh; }
    .chat { position:relative; min-width:0; display:flex; flex-direction:column; border-right:1px solid #26324a; }
    .messages { flex:1; overflow-y:auto; padding:24px 24px 110px; }
    .composer { position:absolute; left:50%; transform:translateX(-50%); bottom:18px; width:min(760px, calc(100% - 48px)); display:flex; gap:10px; background:#111827; border:1px solid #334155; border-radius:18px; padding:12px; box-shadow:0 10px 35px rgba(0,0,0,.35); }
    .composer input { flex:1; background:transparent; border:0; outline:0; color:white; font-size:15px; }
    .composer button, .approval button { background:#2563eb; color:white; border:0; padding:10px 14px; border-radius:12px; cursor:pointer; }
    .composer button:disabled { opacity:.5; cursor:not-allowed; }
    .bubble { max-width:860px; margin:12px auto; padding:14px 16px; border-radius:16px; line-height:1.5; white-space:pre-wrap; }
    .user { background:#1d4ed8; color:white; }
    .assistant { background:#111827; border:1px solid #26324a; }
    .system { background:#0f172a; border:1px dashed #475569; color:#cbd5e1; }
    .approval { background:#3b2f13; border:1px solid #b45309; }
    .approval .reject { background:#7f1d1d; }
    .workflow { display:flex; flex-direction:column; min-height:0; }
    .workflow header { padding:18px; border-bottom:1px solid #26324a; font-weight:700; }
    .cards { overflow-y:auto; padding:14px; }
    .card { background:#111827; border:1px solid #26324a; border-radius:14px; padding:12px; margin-bottom:10px; }
    .card .type { color:#93c5fd; font-size:12px; text-transform:uppercase; }
    .card .title { font-weight:700; margin:4px 0 6px; }
    .card .msg { color:#cbd5e1; font-size:13px; white-space:pre-wrap; }
  </style>
</head>
<body>
  <div class="layout">
    <main class="chat">
      <div id="messages" class="messages"></div>
      <div class="composer">
        <input id="input" placeholder="Message AI Core..." />
        <button id="send">Send</button>
      </div>
    </main>
    <aside class="workflow">
      <header>Execution Workflow</header>
      <div id="cards" class="cards"></div>
    </aside>
  </div>
<script>
const messages = document.getElementById('messages');
const cards = document.getElementById('cards');
const input = document.getElementById('input');
const send = document.getElementById('send');

function addBubble(cls, text, data=null) {
  const div = document.createElement('div');
  div.className = 'bubble ' + cls;
  div.textContent = text;
  if (data && data.approval_id) {
    div.className = 'bubble approval';
    const ok = document.createElement('button'); ok.textContent = 'Approve';
    const no = document.createElement('button'); no.textContent = 'Reject'; no.className='reject';
    ok.onclick = () => decide(data.approval_id, true);
    no.onclick = () => decide(data.approval_id, false);
    div.appendChild(document.createElement('br'));
    div.appendChild(ok); div.appendChild(document.createTextNode(' ')); div.appendChild(no);
  }
  messages.appendChild(div);
  messages.scrollTop = messages.scrollHeight;
}

function addCard(ev) {
  const div = document.createElement('div');
  div.className = 'card';
  div.innerHTML = `<div class="type">${ev.type}</div><div class="title">${ev.title}</div><div class="msg">${ev.message || ''}</div>`;
  cards.appendChild(div);
  cards.scrollTop = cards.scrollHeight;
}

async function decide(id, approved) {
  await fetch('/api/approval', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({approval_id:id, approved})});
  addBubble('system', approved ? 'Approved. Please send/continue again to rerun from current design.' : 'Rejected. Add modification instructions and send again.');
}

async function run() {
  const text = input.value.trim();
  if (!text) return;
  input.value = '';
  send.disabled = true;
  addBubble('user', text);
  const resp = await fetch('/api/chat/stream', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({message:text})});
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  while (true) {
    const {value, done} = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, {stream:true});
    const parts = buffer.split('\n\n');
    buffer = parts.pop();
    for (const part of parts) {
      const line = part.trim();
      if (!line.startsWith('data:')) continue;
      const ev = JSON.parse(line.slice(5));
      addCard(ev);
      if (['node_started','model_route','provider_check','model_check','command','model_output','error','human_review','final'].includes(ev.type)) {
        addBubble(ev.type === 'human_review' ? 'approval' : (ev.type === 'error' ? 'system' : 'assistant'), `[${ev.title}]\n${ev.message || ''}`, ev.data);
      }
    }
  }
  send.disabled = false;
}

send.onclick = run;
input.addEventListener('keydown', e => { if (e.key === 'Enter') run(); });
addBubble('system', 'Runtime starts with generic configs only. Provider/model installation requires approval.');
</script>
</body>
</html>
'''
