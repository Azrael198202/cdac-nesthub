const messages = document.getElementById('messages');
const trace = document.getElementById('trace');
const form = document.getElementById('chatForm');
const input = document.getElementById('messageInput');
const statusBox = document.getElementById('status');
const dialog = document.getElementById('settingsDialog');

let activeRunId = null;
let waitingForApproval = false;
let liveStreamMessage = null;
let liveStreamNodeId = null;

document.getElementById('settingsBtn').onclick = () => dialog.showModal();
document.getElementById('clearTrace').onclick = () => trace.innerHTML = '';

document.getElementById('saveSettings').onclick = async (e) => {
  e.preventDefault();
  const payload = {
    provider: document.getElementById('provider').value,
    openai_api_key: document.getElementById('openaiKey').value || null,
    openai_model: document.getElementById('openaiModel').value || null,
    hf_token: document.getElementById('hfToken').value || null,
    hf_model: document.getElementById('hfModel').value || null,
    ollama_model: document.getElementById('ollamaModel').value || null,
    ollama_base_url: document.getElementById('ollamaBase').value || null,
  };
  const res = await fetch('/api/settings', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload)});
  const data = await res.json();
  addTrace({title:'Settings saved', message:data.message, status:'completed', data});
  addMessage('assistant', 'Settings saved. You can run the workflow again.');
  dialog.close();
  loadStatus();
};

function addMessage(role, content, options = {}) {
  const el = document.createElement('div');
  el.className = `msg ${role}`;
  if (typeof content === 'string') {
    el.textContent = content;
  } else {
    el.appendChild(content);
  }
  if (options.dataset) {
    Object.entries(options.dataset).forEach(([k, v]) => el.dataset[k] = v);
  }
  messages.appendChild(el);
  messages.scrollTop = messages.scrollHeight;
  return el;
}

function formatEventForChat(ev) {
  const icon = ev.status === 'completed' ? '✓' : ev.status === 'waiting' ? '⏸' : ev.status === 'blocked' ? '!' : '…';
  let text = `${icon} ${ev.title}\n${ev.message || ''}`;
  if (ev.type === 'model_result' && ev.data && ev.data.content) {
    text += `\n\nResult preview:\n${clip(ev.data.content, 1200)}`;
  }
  if (ev.type === 'knowledge' && ev.data && ev.data.hits) {
    text += `\n\nKnowledge hits: ${ev.data.hits.length}`;
  }
  if (ev.type === 'execution' && ev.data) {
    text += `\n\n${clip(JSON.stringify(ev.data, null, 2), 1200)}`;
  }
  return text;
}

function clip(text, max) {
  text = String(text || '');
  return text.length > max ? text.slice(0, max) + '...' : text;
}

function addApprovalMessage(ev) {
  waitingForApproval = true;
  activeRunId = ev.data && ev.data.run_id;

  const box = document.createElement('div');
  const intro = document.createElement('div');
  intro.textContent = `${ev.title}\n${ev.message}`;
  box.appendChild(intro);

  const detail = document.createElement('pre');
  detail.className = 'inlineData';
  detail.textContent = clip(JSON.stringify(ev.data || {}, null, 2), 1800);
  box.appendChild(detail);

  const comment = document.createElement('textarea');
  comment.className = 'approvalComment';
  comment.rows = 2;
  comment.placeholder = 'Optional comment / correction direction';
  box.appendChild(comment);

  const actions = document.createElement('div');
  actions.className = 'approvalActions';
  const approve = document.createElement('button');
  approve.type = 'button';
  approve.textContent = 'Approve and continue';
  const reject = document.createElement('button');
  reject.type = 'button';
  reject.textContent = 'Reject / stop';
  reject.className = 'danger';
  actions.appendChild(approve);
  actions.appendChild(reject);
  box.appendChild(actions);

  approve.onclick = () => resumeWorkflow(true, comment.value, approve, reject);
  reject.onclick = () => resumeWorkflow(false, comment.value, approve, reject);

  addMessage('assistant approval', box);
}

function appendModelStream(ev) {
  const nodeId = ev.data && ev.data.node_id;
  const chunk = ev.data && ev.data.chunk ? ev.data.chunk : ev.message || '';
  if (!liveStreamMessage || liveStreamNodeId !== nodeId) {
    liveStreamNodeId = nodeId;
    liveStreamMessage = addMessage('assistant step stream', `… ${ev.title}\n`);
  }
  liveStreamMessage.textContent += chunk;
  messages.scrollTop = messages.scrollHeight;
}

function addTrace(ev) {
  const el = document.createElement('div');
  el.className = `event ${ev.status || 'running'}`;
  const title = document.createElement('div');
  title.className = 'eventTitle';
  title.textContent = ev.title || ev.type || 'Event';
  const msg = document.createElement('div');
  msg.className = 'eventMsg';
  msg.textContent = ev.message || '';
  el.appendChild(title);
  el.appendChild(msg);
  if (ev.data !== undefined && ev.data !== null) {
    const pre = document.createElement('pre');
    pre.className = 'eventData';
    pre.textContent = typeof ev.data === 'string' ? ev.data : JSON.stringify(ev.data, null, 2);
    el.appendChild(pre);
  }
  trace.appendChild(el);
  trace.scrollTop = trace.scrollHeight;
}

async function loadStatus() {
  const res = await fetch('/api/status');
  const data = await res.json();
  statusBox.textContent = `${data.message}; provider=${data.provider}; ready=${data.provider_ready}`;
}

async function consumeEventStream(response) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  while (true) {
    const {done, value} = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, {stream:true});
    const chunks = buffer.split('\n\n');
    buffer = chunks.pop();
    for (const chunk of chunks) {
      const line = chunk.split('\n').find(x => x.startsWith('data: '));
      if (!line) continue;
      const ev = JSON.parse(line.slice(6));
      if (ev.data && ev.data.run_id) activeRunId = ev.data.run_id;
      addTrace(ev);

      if (ev.type === 'model_stream') {
        appendModelStream(ev);
      }
      if (['bootstrap', 'workflow', 'node_start', 'knowledge', 'model_call', 'model_result', 'execution', 'learning', 'output', 'model_error', 'human_action', 'human_approved', 'human_rejected'].includes(ev.type)) {
        if (ev.type === 'model_result') { liveStreamMessage = null; liveStreamNodeId = null; }
        addMessage('assistant step', formatEventForChat(ev));
      }
      if (ev.status === 'waiting' && ev.type === 'review') {
        addApprovalMessage(ev);
        return;
      }
      if (ev.status === 'blocked') {
        waitingForApproval = false;
        return;
      }
    }
  }
  waitingForApproval = false;
}

async function resumeWorkflow(approved, comment, approveBtn, rejectBtn) {
  if (!activeRunId) {
    addMessage('assistant', 'No active run_id found. Please start again.');
    return;
  }
  approveBtn.disabled = true;
  rejectBtn.disabled = true;
  addMessage('user', approved ? 'Approved. Continue.' : `Rejected. ${comment || ''}`);
  const res = await fetch('/api/resume', {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({run_id: activeRunId, approved, comment: comment || null})
  });
  await consumeEventStream(res);
}

form.addEventListener('submit', async (e) => {
  e.preventDefault();
  const text = input.value.trim();
  if (!text) return;
  if (waitingForApproval) {
    addMessage('assistant', 'A workflow is waiting for approval. Please approve or reject the current checkpoint first.');
    return;
  }
  addMessage('user', text);
  input.value = '';
  addMessage('assistant step', 'Starting workflow. Each important step will appear here and may ask for approval.');
  const res = await fetch('/api/chat', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({message:text})});
  await consumeEventStream(res);
});

input.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
    form.requestSubmit();
  }
});

loadStatus();
