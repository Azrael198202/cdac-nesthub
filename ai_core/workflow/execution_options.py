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
    ExecutionOption("llm_generate", "content_generation", "prompt_contract", False, False, "runtime", "Executor LLM generates final content only when this action is explicitly selected. Planner LLM calls are stage operations, not final actions."),
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


ACTION_ALIASES: dict[str, str] = {
    # canonical aliases from planner prompts / LLM wording
    "llm": "llm_generate",
    "llm_generation": "llm_generate",
    "model_generation": "llm_generate",
    "content_generation": "llm_generate",
    "generate_content": "llm_generate",
    "simple_code": "generate_code",
    "code_generation": "generate_code",
    "write_code": "generate_code",
    "simple_shell": "generate_shell",
    "shell_generation": "generate_shell",
    "write_shell": "generate_shell",
    "api_no_key": "call_api_no_key",
    "api_without_key": "call_api_no_key",
    "call_api_without_key": "call_api_no_key",
    "no_key_api": "call_api_no_key",
    "api_with_key": "call_api_with_key",
    "key_required_api": "call_api_with_key",
    "call_api": "call_api_no_key",
    "api_call": "call_api_no_key",
    "web": "web_query",
    "web_search": "web_query",
    "websearch": "web_query",
    "web_query": "web_query",
    "search_web": "web_query",
    "local_knowledge": "use_local_knowledge",
    "local_rag": "use_local_knowledge",
    "rag": "use_local_knowledge",
    "knowledge_base": "use_local_knowledge",
    "existing_tool": "use_existing_tool",
    "tool_call": "use_existing_tool",
    "external_skill": "use_external_skill",
    "skill_call": "use_external_skill",
    "complex_tool": "generate_complex_tool",
    "sdk": "generate_complex_tool",
    "sdk_generation": "generate_complex_tool",
    "static_response": "compose_static_response",
    "human_interaction": "ask_user",
    "ask_human": "ask_user",
}

SELECTION_RULES: tuple[str, ...] = (
    "Choose from fixed action_type values only.",
    "Rank all plausible options before selecting one.",
    "Prefer no-credential options before credential-required options when both can satisfy the request.",
    "Prefer free/runtime options before paid options when both can satisfy the request.",
    "Prefer already-prepared local or registered resources before generating new code or using external access.",
    "Do not use web/API/external access unless the intent requires current, external, or evidence-backed information.",
    "Do not choose execution methods inside execution; agent_action_planning is the only owner of final action selection. Workflow planning may call planner LLM, but that is not final task execution.",
)


AGENT_ACTION_PROMPT_CONTRACT: dict[str, Any] = {
    "content": "Use upstream input, intent, completed requirements, clean context, and the agent objective only.",
    "target": "Choose the next execution action and substeps. Do not execute the user task in this planning step.",
    "actions": [item.action_type for item in FIXED_EXECUTION_OPTIONS],
    "rules": list(SELECTION_RULES),
    "required_output": {
        "execution_decision": {
            "selected_action_type": "one fixed action_type",
            "ranked_options": "array ranked by suitability and rules",
            "reason": "short domain-neutral reason"
        },
        "planned_steps": "array of executable substeps using selected fixed action_type"
    }
}


def fixed_options_for_prompt() -> list[dict[str, Any]]:
    return [asdict(item) for item in FIXED_EXECUTION_OPTIONS]


def method_for_action(action_type: str, default: str = "content_generation") -> str:
    return ACTION_TO_METHOD.get(str(action_type or ""), default)


def is_fixed_action(action_type: str) -> bool:
    return str(action_type or "") in ACTION_TO_METHOD


def normalize_action_type(value: Any, default: str = "") -> str:
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if text in ACTION_TO_METHOD:
        return text
    return ACTION_ALIASES.get(text, default)
