
const messages = document.getElementById("messages");
const events = document.getElementById("events");
const form = document.getElementById("form");
const input = document.getElementById("message");
const sendButton = document.getElementById("sendButton");
const stickyInteraction = document.getElementById("stickyInteraction");

let currentRunId = null;
let source = null;
let workflowBusy = false;

let runCard = null;
let runProgress = null;

const nodeCards = new Map();
const activeNodeKeys = new Map();
const nodeAttemptCounts = new Map();
const pausedNodeKeys = new Set();
const completedNodeKeys = new Set();
const retryNodeIds = new Set();

let workflowPaused = false;
let activeInteraction = null;
let bufferedEvents = [];

const NODE_EVENTS = new Set([
  "NODE_STARTED","NODE_EXECUTING","NODE_RESULT","NODE_RETRY_STARTED","REJECTED_RETRY",
  "EXECUTION_PLANNER_STARTED","EXECUTION_STEP_ANALYZING","EXECUTION_PLANNER_RESULT","APPROVAL_MEMORY_APPLIED","APPROVAL_RECORDED_API","APPROVAL_RECORDED","TOOL_BLUEPRINT_GENERATED","MODULE_BLUEPRINT_GENERATED",
  "LLM_EXECUTOR_READY","LLM_PROMPT_RENDERED","LLM_ROUTE_START",
  "LLM_PROVIDER_START","LLM_HEALTH_CHECK","LLM_HEALTH_OK",
  "LLM_MODEL_READY","LLM_MODEL_MISSING","LLM_MODEL_FALLBACK",
  "LLM_MODEL_PULL_FAILED","LLM_ENDPOINT_FALLBACK",
  "LLM_REQUEST_SENT","LLM_RESPONSE_RECEIVED","LLM_PROVIDER_DONE",
  "LLM_PROVIDER_ERROR","LLM_JSON_VALIDATING","LLM_JSON_VALIDATED",
  "LLM_JSON_VALIDATION_FAILED","RESULT_AUTO_REPAIRED","SCHEMA_AUTO_REPAIRED",
  "CORRECTION_MEMORY_APPLIED",
  "RUNTIME_TEMPLATE_EVOLVED","VALIDATION_RECOVERY_REQUIRED",
  "HUMAN_REVIEW","CAPABILITY_READY","CAPABILITY_ROUTE",
  "PROVIDER_BINARY_READY","PROVIDER_BINARY_MISSING",
  "PROVIDER_INSTALL_STARTED","PROVIDER_INSTALL_DONE","PROVIDER_INSTALL_FAILED",
  "PROVIDER_COMMAND_STARTED","PROVIDER_COMMAND_OUTPUT","PROVIDER_COMMAND_FINISHED",
  "PROVIDER_DAEMON_STARTED",
  "MODULE_GENERATION_STARTED","MODULE_REGISTERED","MODULE_EXECUTION_STARTED","MODULE_EXECUTED","MODULE_GENERATION_FAILED"
]);

function esc(s){
  return String(s ?? "").replace(/[&<>"']/g, c => ({
    "&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"
  }[c]));
}

function scrollMessages(){
  messages.scrollTop = messages.scrollHeight;
}

function setBusy(isBusy, label = ""){
  workflowBusy = isBusy;
  input.disabled = isBusy;
  sendButton.disabled = isBusy;
  sendButton.textContent = isBusy ? (label || "Running...") : "Send";
  input.placeholder = isBusy ? "Workflow is running. Please wait..." : "Message AI Core...";
}

function bubble(text, cls="system"){
  const div = document.createElement("div");
  div.className = "bubble " + cls;
  div.textContent = text;
  messages.appendChild(div);
  scrollMessages();
  return div;
}

function htmlBubble(html, cls="system"){
  const div = document.createElement("div");
  div.className = "bubble " + cls;
  div.innerHTML = html;
  messages.appendChild(div);
  scrollMessages();
  return div;
}

function addEventMini(ev){
  const div = document.createElement("div");
  div.className = "event-mini";
  div.innerHTML = `<div class="type">${esc(ev.type || "")}</div><b>${esc(ev.title || "")}</b><div>${esc(ev.message || "")}</div>`;
  events.prepend(div);
}

function ensureRunCard(runId){
  if(runCard) return runCard;

  runCard = document.createElement("div");
  runCard.className = "run-card";
  runCard.innerHTML = `
    <div class="run-header">
      <b>Run</b> <span id="runIdText">${esc(runId || "")}</span>
      <div class="progress"><div id="runProgress" class="progress-bar"></div></div>
    </div>
    <div id="runBody"></div>
  `;
  messages.appendChild(runCard);
  runProgress = runCard.querySelector("#runProgress");
  scrollMessages();
  return runCard;
}

function setProgress(p){
  if(!runProgress) return;
  const n = Math.max(0, Math.min(100, Number(p || 0)));
  runProgress.style.width = n + "%";
}

function nodeIdFromEvent(ev){
  if(ev.node_id) return ev.node_id;
  if(ev.title && /^[a-zA-Z0-9_]+$/.test(ev.title)) return ev.title;
  if(ev.message){
    const m = String(ev.message).match(/node=([a-zA-Z0-9_]+)/);
    if(m) return m[1];
  }
  return "runtime";
}

function statusForEvent(ev){
  if(ev.type === "NODE_RESULT" || ev.type === "LLM_PROVIDER_DONE" || ev.type === "LLM_JSON_VALIDATED" || ev.type === "MODULE_EXECUTED") return "done";
  if(ev.type === "RESULT_AUTO_REPAIRED" || ev.type === "SCHEMA_AUTO_REPAIRED") return "running";
  if(ev.type === "RUN_FAILED" || ev.type === "LLM_PROVIDER_ERROR" || ev.type === "LLM_JSON_VALIDATION_FAILED" || ev.type === "MODULE_GENERATION_FAILED") return "error";
  if(ev.type === "HUMAN_REVIEW" || ev.type === "VALIDATION_RECOVERY_REQUIRED" || ev.type === "SECRET_REQUIRED") return "waiting";
  if(ev.type === "NODE_RETRY_STARTED" || ev.type === "REJECTED_RETRY") return "running";
  return "running";
}

function visualKeyForNode(nodeId, ev={}){
  const explicitAttempt = Number(ev.attempt_number || ev.attempt || 0);
  if(explicitAttempt > 0){
    const key = `${nodeId}#${explicitAttempt}`;
    nodeAttemptCounts.set(nodeId, explicitAttempt);
    activeNodeKeys.set(nodeId, key);
    return key;
  }

  if(ev.type === "NODE_RETRY_STARTED"){
    const nextAttempt = (nodeAttemptCounts.get(nodeId) || 1) + 1;
    nodeAttemptCounts.set(nodeId, nextAttempt);
    const key = `${nodeId}#${nextAttempt}`;
    activeNodeKeys.set(nodeId, key);
    return key;
  }

  if(ev.type === "NODE_STARTED"){
    const currentKey = activeNodeKeys.get(nodeId);
    if(!currentKey){
      const nextAttempt = (nodeAttemptCounts.get(nodeId) || 0) + 1;
      nodeAttemptCounts.set(nodeId, nextAttempt);
      const key = `${nodeId}#${nextAttempt}`;
      activeNodeKeys.set(nodeId, key);
      return key;
    }
    return currentKey;
  }

  if(!activeNodeKeys.has(nodeId)){
    const nextAttempt = (nodeAttemptCounts.get(nodeId) || 0) + 1;
    nodeAttemptCounts.set(nodeId, nextAttempt);
    activeNodeKeys.set(nodeId, `${nodeId}#${nextAttempt}`);
  }

  return activeNodeKeys.get(nodeId);
}

function ensureNodeCard(nodeId, ev={}){
  ensureRunCard(currentRunId);

  const key = visualKeyForNode(nodeId, ev);
  if(nodeCards.has(key)) return nodeCards.get(key);

  const body = runCard.querySelector("#runBody");
  const attempt = key.split("#")[1] || "1";
  const card = document.createElement("div");
  card.className = "workflow-card";
  card.dataset.nodeId = nodeId;
  card.dataset.visualKey = key;
  card.innerHTML = `
    <div class="workflow-header">
      <div class="chevron">›</div>
      <div class="node-title">
        <div class="id">${esc(nodeId)}</div>
        <div class="sub">${esc(ev.message || "Waiting...")}</div>
      </div>
      <div class="attempt-tag">attempt ${esc(attempt)}</div>
      <div class="status-pill running">running</div>
    </div>
    <div class="workflow-body"></div>
  `;

  card.querySelector(".workflow-header").onclick = () => {
    card.classList.toggle("collapsed");
  };

  body.appendChild(card);
  nodeCards.set(key, card);
  scrollMessages();
  return card;
}

function addStep(ev, opts={}){
  const nodeId = opts.nodeId || nodeIdFromEvent(ev);
  const card = ensureNodeCard(nodeId, ev);
  const key = card.dataset.visualKey;
  const body = card.querySelector(".workflow-body");

  const status = statusForEvent(ev);
  if(ev.type === "NODE_RESULT") completedNodeKeys.add(key);
  const step = document.createElement("div");
  step.className = "step " + status + (ev.type && ev.type.includes("MEMORY") ? " memory" : "");

  let detail = "";
  const data = ev.result || ev.evolution || ev.spec || null;
  if(data){
    detail = `<details open><summary>JSON / Details</summary><div class="step-json">${esc(JSON.stringify(data, null, 2))}</div></details>`;
  }

  if(ev.validation_error){
    detail += `<details open><summary>Validation Error</summary><div class="step-json">${esc(ev.validation_error)}</div></details>`;
  }

  step.innerHTML = `
    <div class="step-title">
      <span class="step-type">${esc(ev.type || "event")}</span>
      <span>${esc(ev.title || nodeId)}</span>
    </div>
    <div class="step-msg">${esc(ev.message || "")}</div>
    ${detail}
  `;

  body.appendChild(step);

  const sub = card.querySelector(".sub");
  sub.textContent = ev.message || ev.title || "";

  const pill = card.querySelector(".status-pill");
  card.classList.remove("paused");

  if(ev.type === "HUMAN_REVIEW" || ev.type === "VALIDATION_RECOVERY_REQUIRED" || ev.type === "SECRET_REQUIRED"){
    pausedNodeKeys.add(key);
    card.classList.add("paused");
    pill.className = "status-pill paused";
    pill.textContent = "waiting";
  }else if(completedNodeKeys.has(key) && status === "running"){
    pill.className = "status-pill done";
    pill.textContent = "done";
  }else{
    pill.className = "status-pill " + status;
    pill.textContent = status;
  }

  if(ev.progress !== undefined) setProgress(ev.progress);
  scrollMessages();
}

function markCurrentInteractionResolved(decisionText){
  if(!activeInteraction) return;

  const {nodeId, key, event} = activeInteraction;

  const card = nodeCards.get(key);
  if(card){
    card.classList.remove("paused");
    card.classList.add("resolved-human");
    pausedNodeKeys.delete(key);

    const pill = card.querySelector(".status-pill");
    pill.className = "status-pill resolved";
    pill.textContent = "resolved";

    const body = card.querySelector(".workflow-body");
    const step = document.createElement("div");
    step.className = "step done";

    const compact = event && event.result ? JSON.stringify(event.result, null, 2) : "";
    step.innerHTML = `
      <div class="step-title">
        <span class="step-type">HUMAN_INTERACTION_RESOLVED</span>
        <span>Interaction resolved</span>
      </div>
      <details class="interaction-history">
        <summary>${esc(decisionText)}</summary>
        ${compact ? `<div class="step-json">${esc(compact)}</div>` : ""}
      </details>
    `;
    body.appendChild(step);
  }

  stickyInteraction.classList.remove("active");
  stickyInteraction.innerHTML = "";
  document.body.classList.remove("has-sticky-interaction");

  workflowPaused = false;
  activeInteraction = null;

  // Important:
  // Do NOT setBusy(false) here. The workflow is still running after resume.
  setBusy(true, "Thinking...");

  scrollMessages();
  flushBufferedEvents();
}


function markCurrentInteractionRejectedAndRetrying(decisionText){
  if(!activeInteraction) return;
  const {nodeId, key, event} = activeInteraction;
  const card = nodeCards.get(key);
  if(card){
    card.classList.remove("paused");
    pausedNodeKeys.delete(key);
    const pill = card.querySelector(".status-pill");
    pill.className = "status-pill error";
    pill.textContent = "rejected";
    const body = card.querySelector(".workflow-body");
    const step = document.createElement("div");
    step.className = "step error";
    const compact = event && event.result ? JSON.stringify(event.result, null, 2) : "";
    step.innerHTML = `
      <div class="step-title">
        <span class="step-type">HUMAN_INTERACTION_REJECTED</span>
        <span>Rejected. Retrying with feedback...</span>
      </div>
      <details class="interaction-history" open>
        <summary>${esc(decisionText)}</summary>
        ${compact ? `<div class="step-json">${esc(compact)}</div>` : ""}
      </details>
    `;
    body.appendChild(step);
  }
  stickyInteraction.classList.remove("active");
  stickyInteraction.innerHTML = "";
  document.body.classList.remove("has-sticky-interaction");
  workflowPaused = false;
  activeInteraction = null;
  setBusy(true, "Retrying...");
  scrollMessages();
  flushBufferedEvents();
}

function showStickyHumanReview(ev){
  const nodeId = nodeIdFromEvent(ev);
  const card = ensureNodeCard(nodeId, ev);
  const key = card.dataset.visualKey;

  pausedNodeKeys.add(key);
  card.classList.add("paused");
  const pill = card.querySelector(".status-pill");
  pill.className = "status-pill paused";
  pill.textContent = "waiting";

  const body = card.querySelector(".workflow-body");
  const placeholder = document.createElement("div");
  placeholder.className = "step waiting";
  placeholder.innerHTML = `
    <div class="step-title">
      <span class="step-type">HUMAN_INTERACTION</span>
      <span>Waiting for user input</span>
    </div>
    <div class="interaction-placeholder">
      Human Review is pinned at the bottom. Please approve, reject, or modify there.
    </div>
  `;
  body.appendChild(placeholder);

  workflowPaused = true;
  activeInteraction = {type:"human_review", nodeId, key, event:ev};
  document.body.classList.add("has-sticky-interaction");

  const json = JSON.stringify(ev.result || {}, null, 2);
  stickyInteraction.innerHTML = `
    <div class="sticky-title">
      <div><span class="spinner"></span>Human Review Required</div>
      <div class="badge">${esc(nodeId)}</div>
    </div>
    <div class="sticky-body">
      <div>${esc(ev.message || "")}</div>
      ${ev.validation_error ? `<div class="sticky-json">${esc(ev.validation_error)}</div>` : ""}
      <div id="stickyJson" class="sticky-json" contenteditable="false">${esc(json)}</div>
      <textarea id="stickyFeedback" placeholder="Reject reason or modification note..."></textarea>
      <div class="sticky-actions">
        <button id="stickyApprove" class="approve" type="button">Approve</button>
        <button id="stickyReject" class="reject" type="button">Reject & Retry</button>
        <button id="stickyModify" class="modify" type="button">Modify JSON & Continue</button>
        <button id="stickyEdit" class="edit-json" type="button">Edit JSON</button>
      </div>
    </div>
  `;
  stickyInteraction.classList.add("active");

  const feedback = document.getElementById("stickyFeedback");
  const jsonBox = document.getElementById("stickyJson");

  document.getElementById("stickyEdit").onclick = () => {
    jsonBox.contentEditable = "true";
    jsonBox.focus();
  };

  document.getElementById("stickyApprove").onclick = async () => {
    stickyInteraction.querySelectorAll("button").forEach(b => b.disabled = true);
    markCurrentInteractionResolved("Approved. Continuing workflow...");
    await resume("approve", null, feedback.value);
  };

  document.getElementById("stickyReject").onclick = async () => {
    stickyInteraction.querySelectorAll("button").forEach(b => b.disabled = true);
    markCurrentInteractionRejectedAndRetrying("Rejected. Retrying with feedback...");
    await resume("reject", null, feedback.value || "Rejected by human.");
  };

  document.getElementById("stickyModify").onclick = async () => {
    try{
      const parsed = JSON.parse(jsonBox.textContent);
      stickyInteraction.querySelectorAll("button").forEach(b => b.disabled = true);
      markCurrentInteractionResolved("Modified JSON accepted. Continuing workflow...");
      await resume("modify", parsed, feedback.value || "Modified by human.");
    }catch(err){
      alert("Invalid JSON: " + err.message);
    }
  };

  stickyInteraction.scrollIntoView({block:"end", behavior:"smooth"});
}


function normalizeHumanInputFields(request){
  const rawFields = (request && Array.isArray(request.fields)) ? request.fields : [];
  return rawFields.map((raw, idx) => {
    if(typeof raw === "string"){
      return {
        field: raw,
        label: toHumanLabel(raw),
        question: `Please provide this information: ${toHumanLabel(raw)}.`,
        type: "text",
        required: true,
        step_id: ""
      };
    }

    const field = raw.field || raw.field_id || raw.name || raw.id || `field_${idx+1}`;
    const type = normalizeInputType(raw.type || raw.input_type || raw.ui_type || raw.component || "text");
    return {
      field,
      label: raw.label || raw.title || raw.display_name || toHumanLabel(field),
      question: raw.question || raw.prompt || raw.message || `Please provide this information: ${toHumanLabel(field)}.`,
      type,
      required: raw.required !== false,
      options: Array.isArray(raw.options || raw.choices || raw.enum) ? (raw.options || raw.choices || raw.enum) : [],
      placeholder: raw.placeholder || "",
      description: raw.description || raw.help_text || "",
      examples: Array.isArray(raw.examples) ? raw.examples : [],
      step_id: raw.step_id || ""
    };
  });
}

function toHumanLabel(value){
  return String(value || "required value")
    .replace(/[_-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function normalizeInputType(value){
  const type = String(value || "text").toLowerCase().trim();
  const allowed = new Set([
    "text", "textarea", "select", "number", "date", "time", "datetime-local",
    "email", "url", "tel", "password", "checkbox"
  ]);
  return allowed.has(type) ? type : "text";
}

function showStickyHumanInputRequired(ev){
  const nodeId = nodeIdFromEvent(ev) || "execution";
  const card = ensureNodeCard(nodeId, ev);
  const key = card.dataset.visualKey;
  const request = ev.request || {};
  const fields = normalizeHumanInputFields(request);

  pausedNodeKeys.add(key);
  card.classList.add("paused");
  const pill = card.querySelector(".status-pill");
  pill.className = "status-pill paused";
  pill.textContent = "waiting";

  const body = card.querySelector(".workflow-body");
  const placeholder = document.createElement("div");
  placeholder.className = "step waiting";
  placeholder.innerHTML = `
    <div class="step-title">
      <span class="step-type">HUMAN_INPUT_REQUIRED</span>
      <span>Waiting for missing information</span>
    </div>
    <div class="interaction-placeholder">
      Missing information input is pinned at the bottom. Please fill the form and continue.
    </div>
  `;
  body.appendChild(placeholder);

  workflowPaused = true;
  activeInteraction = {type:"human_input", nodeId, key, event:ev};
  document.body.classList.add("has-sticky-interaction");

  const formHtml = fields.map((field, idx) => {
    const fieldId = `humanField_${idx}`;
    const required = field.required ? "required" : "";
    const label = `${field.label || field.field}${field.required ? " *" : ""}`;
    let inputHtml = "";
    if(field.options && field.options.length){
      inputHtml = `<select id="${fieldId}" data-field="${esc(field.field)}" ${required}>
        <option value="">Select...</option>
        ${field.options.map(opt => `<option value="${esc(opt)}">${esc(opt)}</option>`).join("")}
      </select>`;
    }else if(field.type === "textarea"){
      inputHtml = `<textarea id="${fieldId}" data-field="${esc(field.field)}" placeholder="${esc(field.placeholder || "")}" ${required}></textarea>`;
    }else if(field.type === "checkbox"){
      inputHtml = `<input id="${fieldId}" data-field="${esc(field.field)}" type="checkbox" ${required} />`;
    }else{
      inputHtml = `<input id="${fieldId}" data-field="${esc(field.field)}" type="${esc(field.type || "text")}" placeholder="${esc(field.placeholder || "")}" ${required} />`;
    }
    const examples = Array.isArray(field.examples) && field.examples.length
      ? `<div class="hint">Examples: ${esc(field.examples.join(" / "))}</div>`
      : "";
    return `
      <div class="human-input-field">
        <label for="${fieldId}">${esc(label)}</label>
        ${inputHtml}
        <div class="hint">${esc(field.question || field.description || "")}</div>
        ${examples}
      </div>
    `;
  }).join("");

  stickyInteraction.innerHTML = `
    <div class="sticky-title">
      <div><span class="spinner"></span>${esc(request.title || "Additional information required")}</div>
      <div class="badge">${esc(nodeId)}</div>
    </div>
    <div class="sticky-body">
      <div>${esc(request.message || ev.message || "Please provide missing information before continuing.")}</div>
      <div class="human-input-grid">${formHtml || `<div class="interaction-placeholder">No fields were provided by the runtime interaction contract.</div>`}</div>
      <textarea id="humanInputFeedback" placeholder="Optional note..."></textarea>
      <details>
        <summary style="cursor:pointer;color:#fde68a;margin-top:8px">Request JSON</summary>
        <div class="sticky-json">${esc(JSON.stringify(request, null, 2))}</div>
      </details>
      <div class="sticky-actions">
        <button id="humanInputSubmit" class="approve" type="button">${esc(request.submit_label || "Save information & Continue")}</button>
        <button id="humanInputCancel" class="reject" type="button">${esc(request.cancel_label || "Cancel")}</button>
      </div>
    </div>
  `;
  stickyInteraction.classList.add("active");

  document.getElementById("humanInputSubmit").onclick = async () => {
    const answers = {};
    let firstInvalid = null;
    fields.forEach((field, idx) => {
      const el = document.getElementById(`humanField_${idx}`);
      let value = "";
      if(el){
        value = el.type === "checkbox" ? Boolean(el.checked) : String(el.value || "").trim();
      }
      if(field.required && (value === "" || value === false) && !firstInvalid) firstInvalid = el;
      answers[field.field] = value;
    });
    if(firstInvalid){
      firstInvalid.focus();
      alert("Please fill all required fields.");
      return;
    }
    stickyInteraction.querySelectorAll("button,input,select,textarea").forEach(b => b.disabled = true);
    const feedback = document.getElementById("humanInputFeedback").value || "Missing information provided.";
    markCurrentInteractionResolved("Missing information provided. Continuing workflow...");
    await resume("modify", {answers, field_mapping: fieldMapping, interaction_request: request}, feedback);
  };

  document.getElementById("humanInputCancel").onclick = async () => {
    stickyInteraction.querySelectorAll("button,input,select,textarea").forEach(b => b.disabled = true);
    markCurrentInteractionResolved("Missing information cancelled.");
    await resume("reject", null, "Missing information cancelled by user.");
  };

  const first = stickyInteraction.querySelector("input,select,textarea");
  if(first) setTimeout(() => first.focus(), 50);
  stickyInteraction.scrollIntoView({block:"end", behavior:"smooth"});
}

function showStickySecretRequired(ev){
  const nodeId = nodeIdFromEvent(ev) || "runtime";
  const card = ensureNodeCard(nodeId, ev);
  const key = card.dataset.visualKey;

  pausedNodeKeys.add(key);
  card.classList.add("paused");
  const pill = card.querySelector(".status-pill");
  pill.className = "status-pill paused";
  pill.textContent = "waiting";

  const body = card.querySelector(".workflow-body");
  const placeholder = document.createElement("div");
  placeholder.className = "step waiting";
  placeholder.innerHTML = `
    <div class="step-title">
      <span class="step-type">SECRET_REQUIRED</span>
      <span>Waiting for API key</span>
    </div>
    <div class="interaction-placeholder">
      API key input is pinned at the bottom.
    </div>
  `;
  body.appendChild(placeholder);

  workflowPaused = true;
  activeInteraction = {type:"secret", nodeId, key, event:ev};
  document.body.classList.add("has-sticky-interaction");

  stickyInteraction.innerHTML = `
    <div class="sticky-title">
      <div><span class="spinner"></span>API Key Required</div>
      <div class="badge">${esc(nodeId)}</div>
    </div>
    <div class="sticky-body">
      <div>${esc(ev.message || "")}</div>
      <input id="stickySecret" type="password" placeholder="${esc(ev.secret_key || "API_KEY")}" style="width:100%;background:#020617;color:#e5edff;border:1px solid #334155;border-radius:8px;margin-top:8px;padding:9px;font-family:inherit;font-size:12px" />
      <div class="sticky-actions">
        <button id="stickySaveSecret" class="approve" type="button">Save Key & Continue</button>
        <button id="stickyCancelSecret" class="reject" type="button">Cancel</button>
      </div>
    </div>
  `;
  stickyInteraction.classList.add("active");

  const inputEl = document.getElementById("stickySecret");

  document.getElementById("stickySaveSecret").onclick = async () => {
    const value = inputEl.value.trim();
    if(!value){ alert("Please input the API key."); return; }
    stickyInteraction.querySelectorAll("button").forEach(b => b.disabled = true);
    markCurrentInteractionResolved("API key saved. Continuing workflow...");
    await resume("approve", {value}, "secret provided");
  };

  document.getElementById("stickyCancelSecret").onclick = async () => {
    stickyInteraction.querySelectorAll("button").forEach(b => b.disabled = true);
    markCurrentInteractionResolved("API key input cancelled.");
    await resume("reject", null, "secret cancelled");
  };
}

async function resume(decision, modified_result=null, feedback=""){
  if(!currentRunId){
    bubble("[Resume failed]\nNo current run id.", "error");
    return;
  }
  await fetch("/api/resume", {
    method:"POST",
    headers:{"Content-Type":"application/json"},
    body:JSON.stringify({run_id:currentRunId, decision, modified_result, feedback})
  });
}

function flushBufferedEvents(){
  const items = bufferedEvents;
  bufferedEvents = [];
  for(const ev of items){
    handleEvent(ev, true);
  }
}


function markAllNodesTerminal(status="done") {
  nodeCards.forEach((card, key) => {
    const pill = card.querySelector(".status-pill");
    if (!pill) return;
    if (pill.classList.contains("error") && status !== "error") return;
    card.classList.remove("paused");
    pill.className = "status-pill " + status;
    pill.textContent = status;
    completedNodeKeys.add(key);
  });
}

function finalDisplayPayload(ev){
  const output = ev.results && ev.results.output ? ev.results.output : null;
  if(output && (output.final_answer || output.message)){
    return {
      message: output.final_answer || output.message,
      details: output
    };
  }
  return {
    message: ev.message || "Workflow completed.",
    details: ev.results || {}
  };
}

function handleEvent(ev, fromBuffer=false){
  addEventMini(ev);

  if(ev.progress !== undefined) setProgress(ev.progress);

  if(workflowPaused && !fromBuffer){
    if(ev.type === "RUN_FAILED" || ev.type === "RUN_CANCELLED" || ev.type === "RUN_COMPLETED"){
      // terminal events should still be shown
    }else if(ev.type !== "HUMAN_REVIEW" && ev.type !== "SECRET_REQUIRED" && ev.type !== "HUMAN_INPUT_REQUIRED"){
      bufferedEvents.push(ev);
      return;
    }
  }

  if(ev.type === "RUN_CREATED" || ev.type === "RUN_STARTED"){
    ensureRunCard(ev.run_id || currentRunId);
    addStep({...ev, node_id:"runtime"});
    return;
  }

  if(ev.type === "RUN_COMPLETED"){
    addStep({...ev, node_id:"runtime"});
    markAllNodesTerminal("done");
    const finalPayload = finalDisplayPayload(ev);
    htmlBubble(`<b>[Final Output]</b><div>${esc(finalPayload.message || "")}</div><div class="spec">${esc(JSON.stringify(finalPayload.details || {}, null, 2))}</div>`, "system");
    setBusy(false);
    if(source) source.close();
    return;
  }

  if(ev.type === "RUN_PAUSED"){
    addStep({...ev, node_id:nodeIdFromEvent(ev) || "runtime"});
    setBusy(false);
    if(source) source.close();
    return;
  }

  if(ev.type === "RUN_FAILED" || ev.type === "RUN_CANCELLED"){
    addStep({...ev, node_id:nodeIdFromEvent(ev)});
    markAllNodesTerminal(ev.type === "RUN_FAILED" ? "error" : "done");
    setBusy(false);
    if(source) source.close();
    return;
  }

  if(ev.type === "NODE_RETRY_STARTED"){
    addStep(ev);
    setBusy(true, "Retrying...");
    return;
  }

  if(ev.type === "SECRET_REQUIRED"){
    showStickySecretRequired(ev);
    return;
  }

  if(ev.type === "HUMAN_INPUT_REQUIRED"){
    showStickyHumanInputRequired(ev);
    return;
  }

  if(ev.type === "HUMAN_REVIEW"){
    showStickyHumanReview(ev);
    return;
  }

  if(ev.type === "VALIDATION_RECOVERY_REQUIRED"){
    addStep(ev);
    return;
  }

  if(NODE_EVENTS.has(ev.type) || ev.node_id){
    addStep(ev);
    if(ev.type === "PROVIDER_COMMAND_STARTED") setBusy(true, "Installing...");
    if(ev.type === "LLM_REQUEST_SENT" || ev.type === "LLM_PROVIDER_START") setBusy(true, "Thinking...");
    return;
  }

  // bubble(`[${ev.title || ev.type}]\n${ev.message || ""}`, "system");
}

function connect(runId){
  if(source) source.close();
  source = new EventSource(`/api/events/${runId}`);

  source.onopen = () => {
    addStep({type:"SSE_CONNECTED", title:"SSE connected", message:`run_id=${runId}`, node_id:"runtime"});
  };

  source.onmessage = (msg) => {
    try{
      const ev = JSON.parse(msg.data);
      handleEvent(ev);
    }catch(err){
      bubble("Bad SSE event: " + err.message, "error");
    }
  };

  source.onerror = () => {
    bubble("SSE stream closed or failed. Check server logs.", "error");
    setBusy(false);
    if(source) source.close();
  };
}

form.onsubmit = async (event) => {
  event.preventDefault();

  if(workflowBusy){
    bubble("[Busy]\nA workflow is already running. Please wait until it finishes or fails.", "system");
    return;
  }

  const text = input.value.trim();
  if(!text) return;

  setBusy(true, "Starting...");
  input.value = "";
  runCard = null;
  runProgress = null;
  nodeCards.clear();
  activeNodeKeys.clear();
  nodeAttemptCounts.clear();
  pausedNodeKeys.clear();
  completedNodeKeys.clear();
  retryNodeIds.clear();
  workflowPaused = false;
  activeInteraction = null;
  bufferedEvents = [];
  stickyInteraction.classList.remove("active");
  stickyInteraction.innerHTML = "";
  document.body.classList.remove("has-sticky-interaction");

  try{
    bubble("[Sending]\nPOST /api/chat", "system");
    const res = await fetch("/api/chat", {
      method:"POST",
      headers:{"Content-Type":"application/json"},
      body:JSON.stringify({message:text})
    });

    if(!res.ok){
      const body = await res.text();
      bubble(`POST /api/chat failed: HTTP ${res.status}\n${body}`, "error");
      setBusy(false);
      return;
    }

    const data = await res.json();
    currentRunId = data.run_id;
    ensureRunCard(currentRunId);
    addStep({
      type: "USER_INPUT",
      title: "User input",
      message: text,
      node_id: "runtime",
      progress: 0
    });
    addStep({
      type: "RUN_QUEUED",
      title: "Run queued",
      message: `run_id=${currentRunId}`,
      node_id: "runtime",
      progress: 0
    });
    connect(currentRunId);
  }catch(err){
    bubble("POST /api/chat error: " + err.message, "error");
    setBusy(false);
  }
};
