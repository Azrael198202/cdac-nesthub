from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any


@dataclass(frozen=True)
class ExecutionOption:
    action_type: str
    execution_method: str
    resource_kind: str
    requires_external_access: bool
    requires_credential: bool
    cost_level: str
    preparation_contract: str


FIXED_EXECUTION_OPTIONS: tuple[ExecutionOption, ...] = (
    ExecutionOption("call_llm", "content_generation", "prompt_contract", False, False, "runtime", "Generate a prompt contract and expected output contract."),
    ExecutionOption("generate_code", "runtime_generated_tool", "code_design", False, False, "runtime", "Generate design, code, tests, and sandbox contract before execution."),
    ExecutionOption("generate_shell", "shell", "shell_design", False, False, "runtime", "Generate shell design, command contract, and sandbox contract before execution."),
    ExecutionOption("call_api_no_key", "api_call", "api_contract", True, False, "free_or_unknown", "Collect endpoint candidates, request schema, response schema, and no-key policy."),
    ExecutionOption("call_api_with_key", "api_call", "api_contract", True, True, "free_or_paid", "Collect provider contract, credential fields, request schema, and response schema."),
    ExecutionOption("web_query", "web_search", "web_collection", True, False, "free_or_unknown", "Collect search targets, source policy, query contract, and evidence requirements."),
    ExecutionOption("use_external_skill", "external_skill", "skill_contract", True, False, "free_or_unknown", "Resolve external skill name, input schema, output schema, and permission policy."),
    ExecutionOption("use_existing_tool", "existing_tool", "tool_contract", False, False, "runtime", "Resolve registered tool id, input schema, output schema, and permissions."),
    ExecutionOption("use_local_knowledge", "knowledge_base", "knowledge_contract", False, False, "runtime", "Prepare retrieval query, index scope, evidence requirements, and rerank policy."),
    ExecutionOption("generate_complex_tool", "runtime_generated_tool", "tool_design", False, False, "runtime", "Generate design doc, source code, dependency manifest, and sandbox tests."),
    ExecutionOption("compose_static_response", "static_response", "response_contract", False, False, "runtime", "Use only provided input/context to compose a response without external execution."),
    ExecutionOption("ask_user", "human_interaction", "ui_request", False, False, "runtime", "Ask for missing or confirming information through UI."),
    ExecutionOption("no_op", "no_op", "none", False, False, "runtime", "Do nothing only when the request is already complete or cancelled."),
)

ACTION_TO_METHOD: dict[str, str] = {item.action_type: item.execution_method for item in FIXED_EXECUTION_OPTIONS}
ACTION_CONTRACTS: dict[str, dict[str, Any]] = {item.action_type: asdict(item) for item in FIXED_EXECUTION_OPTIONS}

SELECTION_RULES: tuple[str, ...] = (
    "Choose from fixed action_type values only.",
    "Rank all plausible options before selecting one.",
    "Prefer no-credential options before credential-required options when both can satisfy the request.",
    "Prefer free/runtime options before paid options when both can satisfy the request.",
    "Prefer already-prepared local or registered resources before generating new code or using external access.",
    "Do not use web/API/external access unless the intent requires current, external, or evidence-backed information.",
    "Do not choose execution methods inside execution; workflow_planning is the only owner of action selection.",
)


def fixed_options_for_prompt() -> list[dict[str, Any]]:
    return [asdict(item) for item in FIXED_EXECUTION_OPTIONS]


def method_for_action(action_type: str, default: str = "content_generation") -> str:
    return ACTION_TO_METHOD.get(str(action_type or ""), default)


def is_fixed_action(action_type: str) -> bool:
    return str(action_type or "") in ACTION_TO_METHOD
