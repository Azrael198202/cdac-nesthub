from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


STATE_STATUSES = {
    "created",
    "queued",
    "waiting_input",
    "planning",
    "generating",
    "validating",
    "running",
    "verifying",
    "repairing",
    "completed",
    "failed",
    "cancelled",
    "paused",
    "skipped",
}

VISIBILITY_LEVELS = {"user", "developer", "advanced", "diagnostic"}
EVENT_KINDS = {
    "lifecycle",
    "input",
    "output",
    "method",
    "tool",
    "progress",
    "api_call",
    "download",
    "install",
    "command",
    "validation",
    "verification",
    "repair",
    "log",
    "error",
}


DEFAULT_RUNTIME_FLOW = [
    {
        "flow_id": "surface.user_ui",
        "title": "User / UI",
        "description": "User request entry surface and interactive runtime feedback.",
        "owner": "apps/api",
        "expected_input": "Raw user message, uploaded artifacts, provided parameters, session metadata.",
        "expected_output": "Runtime request payload and runtime state run id.",
    },
    {
        "flow_id": "apps.api.server",
        "title": "apps/api/server.py",
        "description": "HTTP boundary, async job submission, request envelope creation, state stream entry.",
        "owner": "apps/api",
        "expected_input": "HTTP/API payload.",
        "expected_output": "Accepted async job or synchronous runtime response.",
    },
    {
        "flow_id": "perception_brain",
        "title": "perception_brain",
        "description": "Normalize raw input, multimedia, files, and text into a common package.",
        "owner": "perception_brain",
        "expected_input": "Raw text, file descriptors, uploaded artifact references, surface context.",
        "expected_output": "Normalized text, artifact metadata, confidence, warnings.",
    },
    {
        "flow_id": "ai_core.input_parsing",
        "title": "ai_core.input_parsing",
        "description": "Create structured input without deciding how the task should execute.",
        "owner": "ai_core",
        "expected_input": "Normalized perception package.",
        "expected_output": "Structured input, explicit fields, original input reference.",
    },
    {
        "flow_id": "ai_core.intent_interaction",
        "title": "ai_core.intent_recognition / interaction",
        "description": "Recognize intent, task type, capability needs, missing information, and initial step draft.",
        "owner": "ai_core",
        "expected_input": "Structured input and clean conversation context.",
        "expected_output": "Intent frame, task category, capability needs, missing information contract.",
    },
    {
        "flow_id": "auxiliary_memory.parameters",
        "title": "auxiliary_brain.parameters + memory_brain",
        "description": "Complete parameters, bind context, and decide whether the input continues an existing runtime state.",
        "owner": "auxiliary_brain + memory_brain",
        "expected_input": "Intent frame, known parameters, session state, suspended task state.",
        "expected_output": "Completed parameter set, missing input request, or context binding result.",
    },
    {
        "flow_id": "ai_core.workflow_graph",
        "title": "ai_core.workflow / graph / orchestration",
        "description": "Generate the locked execution plan, main graph, subgraphs, Agent graph, and execution method binding.",
        "owner": "ai_core",
        "expected_input": "Completed requirements and clean context.",
        "expected_output": "Workflow plan, graph, locked execution methods, selected providers/tools policy.",
    },
    {
        "flow_id": "verification.pre_execution",
        "title": "verification_brain",
        "description": "Pre-execution validation for schema, parameters, capability availability, and approval requirements.",
        "owner": "verification_brain",
        "expected_input": "Workflow plan and runtime parameter set.",
        "expected_output": "Validation result, approval state, executable plan or blocked reason.",
    },
    {
        "flow_id": "runtime.execution",
        "title": "runtime kernel / ai_core.executors / registered tools",
        "description": "Execute only the locked plan; do not reinterpret intent or reselect capabilities.",
        "owner": "runtime kernel + ai_core.executors",
        "expected_input": "Validated execution plan and runtime inputs.",
        "expected_output": "Tool/API/SDK/shell/LLM/local runtime results.",
    },
    {
        "flow_id": "evidence.trace",
        "title": "evidence_engine + trace / provenance",
        "description": "Record evidence, execution source, provenance, and observability material.",
        "owner": "evidence_engine",
        "expected_input": "Execution events, tool outputs, source material, trace metadata.",
        "expected_output": "Evidence records, trace summary, provenance links.",
    },
    {
        "flow_id": "verification.result",
        "title": "verification_brain.result_verification",
        "description": "Verify real execution, result sufficiency, and confidence against the plan.",
        "owner": "verification_brain",
        "expected_input": "Execution result and evidence material.",
        "expected_output": "Verification decision, confidence, fallback requirement if allowed by plan.",
    },
    {
        "flow_id": "repair_brain",
        "title": "repair_brain",
        "description": "Repair schema, parameter, fallback, and failure states only according to the plan.",
        "owner": "repair_brain",
        "expected_input": "Validation or execution failure and allowed repair policy.",
        "expected_output": "Repaired payload, retry decision, or clear failure reason.",
    },
    {
        "flow_id": "presentation_brain",
        "title": "presentation_brain",
        "description": "Create final synthesis without new search, new execution, or invented facts.",
        "owner": "presentation_brain",
        "expected_input": "Verified step outputs, evidence summary, original user request.",
        "expected_output": "Final answer, artifacts, trace summary.",
    },
    {
        "flow_id": "final.delivery",
        "title": "Final Answer / Artifacts / Trace Summary",
        "description": "Return final user-facing answer, generated artifacts, and runtime trace summary.",
        "owner": "apps/api + presentation surface",
        "expected_input": "Final synthesis package.",
        "expected_output": "User-visible response and artifact links.",
    },
]

STEP_FLOW_ALIASES = {

    "intent_recognition.capability_acquisition": "ai_core.intent_interaction",
    "intent_recognition.capability_contract": "ai_core.intent_interaction",
    "input_parsing.capability_identity": "ai_core.input_parsing",
    "workflow.capability_template_resolution": "ai_core.workflow_graph",
    "workflow.capability_blueprint_planning": "ai_core.workflow_graph",
    "workflow.capability_blueprint_materialization": "ai_core.workflow_graph",
    "pre_execution.capability_classification": "verification.pre_execution",
    "pre_execution.acquisition_gate": "verification.pre_execution",
    "pre_execution.registration_gate": "verification.pre_execution",
    "evidence.capability_material": "evidence.trace",
    "dependency.resolution": "runtime.execution",
    "dependency.artifact_resolution": "runtime.execution",
    "execution.artifact_generation": "runtime.execution",
    "execution.registry_write": "runtime.execution",
    "validation.sandbox": "verification.pre_execution",
    "verification.capability_match_contract": "verification.result",
    "result.verify.capability_execution": "verification.result",
    "final.capability_verification": "final.delivery",
    "repair.capability_acquisition": "repair_brain",
    "runtime": "surface.user_ui",
    "async_job": "apps.api.server",
    "input.normalize": "perception_brain",
    "input_parsing": "ai_core.input_parsing",
    "intent_recognition": "ai_core.intent_interaction",
    "interaction": "ai_core.intent_interaction",
    "parameters": "auxiliary_memory.parameters",
    "pre_execution.parameters": "auxiliary_memory.parameters",
    "context_awareness": "auxiliary_memory.parameters",
    "memory": "auxiliary_memory.parameters",
    "workflow": "ai_core.workflow_graph",
    "workflow_planning": "ai_core.workflow_graph",
    "graph": "ai_core.workflow_graph",
    "orchestration": "ai_core.workflow_graph",
    "task.load": "ai_core.workflow_graph",
    "task.rebuild": "ai_core.workflow_graph",
    "verification": "verification.pre_execution",
    "pre_execution_validation": "verification.pre_execution",
    "pre_execution": "verification.pre_execution",
    "operation.dispatch": "runtime.execution",
    "execution": "runtime.execution",
    "execution.graph": "runtime.execution",
    "tool": "runtime.execution",
    "command": "runtime.execution",
    "dependency": "runtime.execution",
    "evidence": "evidence.trace",
    "trace": "evidence.trace",
    "provenance": "evidence.trace",
    "result.verify": "verification.result",
    "result_verification": "verification.result",
    "repair": "repair_brain",
    "feedback_repair": "repair_brain",
    "final.synthesis": "presentation_brain",
    "presentation": "presentation_brain",
    "final": "final.delivery",
}

def default_runtime_flow() -> list[dict[str, Any]]:
    return [dict(item) for item in DEFAULT_RUNTIME_FLOW]

def resolve_flow_id(step_id: str, kind: str = "", method: str = "") -> str:
    candidates = [str(step_id or ""), str(method or ""), str(kind or "")]
    for raw in candidates:
        value = raw.strip()
        if not value:
            continue
        if value in STEP_FLOW_ALIASES:
            return STEP_FLOW_ALIASES[value]
        lowered = value.casefold().replace("-", "_")
        for key, flow_id in STEP_FLOW_ALIASES.items():
            k = key.casefold().replace("-", "_")
            if lowered == k or lowered.startswith(k + ".") or lowered.startswith(k + "_") or k in lowered:
                return flow_id
    return "runtime.execution"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_event_id() -> str:
    return f"evt_{uuid4().hex[:16]}"


@dataclass
class RuntimeStateEvent:
    run_id: str
    event_id: str = field(default_factory=new_event_id)
    task_id: str = ""
    step_id: str = "runtime"
    flow_id: str = ""
    parent_step_id: str = ""
    sequence: int = 0
    ts: str = field(default_factory=utc_now)
    level: str = "developer"
    kind: str = "lifecycle"
    status: str = "running"
    title: str = ""
    message: str = ""
    input: Any | None = None
    output: Any | None = None
    method: str = ""
    tool: str = ""
    progress: float | None = None
    started_at: str | None = None
    ended_at: str | None = None
    error: dict[str, Any] | None = None
    trace: dict[str, Any] = field(default_factory=dict)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    next_action: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["level"] = self.level if self.level in VISIBILITY_LEVELS else "developer"
        data["kind"] = self.kind if self.kind in EVENT_KINDS else "log"
        data["status"] = self.status if self.status in STATE_STATUSES else str(self.status or "running")
        if data.get("progress") is not None:
            try:
                data["progress"] = max(0.0, min(100.0, float(data["progress"])))
            except Exception:
                data["progress"] = None
        return data


@dataclass
class RuntimeStepState:
    step_id: str
    flow_id: str = ""
    name: str = ""
    status: str = "created"
    level: str = "developer"
    kind: str = "lifecycle"
    input: Any | None = None
    output: Any | None = None
    method: str = ""
    tool: str = ""
    progress: float = 0.0
    started_at: str | None = None
    ended_at: str | None = None
    error: dict[str, Any] | None = None
    trace: dict[str, Any] = field(default_factory=dict)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    next_action: str = ""
    event_count: int = 0
    last_message: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status if self.status in STATE_STATUSES else str(self.status or "created")
        data["level"] = self.level if self.level in VISIBILITY_LEVELS else "developer"
        data["kind"] = self.kind if self.kind in EVENT_KINDS else "log"
        data["progress"] = max(0.0, min(100.0, float(self.progress or 0.0)))
        return data


@dataclass
class RuntimeRunState:
    run_id: str
    task_id: str = ""
    status: str = "created"
    title: str = ""
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    started_at: str | None = None
    ended_at: str | None = None
    progress: float = 0.0
    active_step_id: str = ""
    summary: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    steps: dict[str, RuntimeStepState] = field(default_factory=dict)
    flow: list[dict[str, Any]] = field(default_factory=default_runtime_flow)
    event_count: int = 0
    last_event_id: str = ""
    last_error: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status if self.status in STATE_STATUSES else str(self.status or "created")
        data["progress"] = max(0.0, min(100.0, float(self.progress or 0.0)))
        data["steps"] = [step.to_dict() for step in self.steps.values()]
        return data
