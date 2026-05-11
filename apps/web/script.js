const messages = document.getElementById('messages');
const trace = document.getElementById('trace');
const form = document.getElementById('chatForm');
const input = document.getElementById('messageInput');
const statusBox = document.getElementById('status');
const dialog = document.getElementById('settingsDialog');

document.getElementById('settingsBtn').onclick = () => dialog.showModal();
document.getElementById('clearTrace').onclick = () => trace.innerHTML = '';

document.getElementById('saveSettings').onclick = async (e) => {
  e.preventDefault();
  const payload = {
    provider: document.getElementById('provider').value,
    openai_api_key: document.getElementById('openaiKey').value || null,
    openai_model: document.getElementById('openaiModel').value || null,
    ollama_model: document.getElementById('ollamaModel').value || null,
    ollama_base_url: document.getElementById('ollamaBase').value || null,
  };
  const res = await fetch('/api/settings', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload)});
  const data = await res.json();
  addTrace({title:'Settings saved', message:data.message, status:'completed', data});
  dialog.close();
  loadStatus();
};

function addMessage(role, text) {
  const el = document.createElement('div');
  el.className = `msg ${role}`;
  el.textContent = text;
  messages.appendChild(el);
  messages.scrollTop = messages.scrollHeight;
  return el;
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

form.addEventListener('submit', async (e) => {
  e.preventDefault();
  const text = input.value.trim();
  if (!text) return;
  addMessage('user', text);
  input.value = '';
  const assistant = addMessage('assistant', 'Running workflow...');
  const res = await fetch('/api/chat', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({message:text})});
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let finalParts = [];
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
      addTrace(ev);
      if (ev.type === 'output' || ev.type === 'model_error' || ev.type === 'human_action') {
        finalParts.push(`${ev.title}: ${ev.message}`);
      }
    }
  }
  assistant.textContent = finalParts.length ? finalParts.join('\n') : 'Workflow finished. See execution panel.';
});

loadStatus();
