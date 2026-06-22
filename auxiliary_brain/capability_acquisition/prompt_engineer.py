"""Prompt engineering system for runtime capability code generation.

This module provides dynamic, parameterized prompt templates that adapt based on:
- Capability type (data storage, API, scheduler, etc)
- Complexity level (basic, intermediate, advanced)
- Schema richness (simple vs complex input/output)
- Runtime requirements (external I/O, side effects, etc)

The prompt system is generalized—it does NOT hardcode specific capabilities.
Instead, it derives guidance from capability metadata and schema structure.
"""

from __future__ import annotations

import json
from typing import Any
from dataclasses import dataclass


@dataclass
class CapabilityProfile:
    """Analyze capability metadata to determine prompt guidance level."""
    
    tool_id: str
    complexity: str  # basic, intermediate, advanced
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    connection_schema: dict[str, Any]
    secret_schema: dict[str, Any]
    behavior_contract: str | dict[str, Any]
    runtime_policy: dict[str, Any] | None = None
    
    def infer_capability_category(self) -> str:
        """Infer capability category from schema and contract."""
        contract_text = (
            self.behavior_contract
            if isinstance(self.behavior_contract, str)
            else json.dumps(self.behavior_contract, default=str).lower()
        ).lower()
        
        # Pattern-based inference (extensible)
        if any(w in contract_text for w in ["create", "read", "list", "update", "delete", "store", "table", "database"]):
            return "data_storage"
        elif any(w in contract_text for w in ["schedule", "cron", "interval", "trigger", "repeat"]):
            return "scheduler"
        elif any(w in contract_text for w in ["http", "api", "request", "endpoint", "fetch"]):
            return "api_client"
        elif any(w in contract_text for w in ["process", "parse", "transform", "convert", "validate"]):
            return "data_processor"
        else:
            return "generic_tool"
    
    def schema_richness(self) -> str:
        """Assess input schema complexity."""
        input_props = self.input_schema.get("properties", {})
        if len(input_props) > 10:
            return "high"
        elif len(input_props) > 3:
            return "medium"
        else:
            return "low"
    
    def requires_external_state(self) -> bool:
        """Check if capability needs external database/storage access."""
        return bool(self.connection_schema.get("properties", {})) or "memory" in str(self.connection_schema).lower()


class DynamicPromptTemplate:
    """Generate context-aware system prompts for code generation."""
    
    # Base system guidance (shared across all capabilities)
    BASE_GUIDANCE = (
        "You are a runtime artifact generator for autonomous capability acquisition. "
        "Your role: materialize the supplied contract into executable Python code. "
        "Do NOT plan, research, or explain. Do NOT generate scaffolding, TODOs, or placeholders. "
        "Return ONE JSON object only. No markdown, no code blocks, no preamble."
    )
    
    # Output format guidance (required for all)
    OUTPUT_FORMAT = (
        "Output format: {\"files\": [{\"path\": \"tool.py\", \"content\": \"...\"}], "
        "\"input_schema\": {...}, \"output_schema\": {...}, \"connection_schema\": {...}, "
        "\"secret_schema\": {...}, \"dependencies\": [], \"verification_input\": {...}, "
        "\"verification_expectations\": {...}, \"capability_match_contract\": {...}}"
    )
    
    # File requirements (mandatory across all)
    FILE_REQUIREMENTS = (
        "Files MUST be non-empty array with objects: path, content. "
        "MUST include: path='tool.py' (executable entry point), path='test_tool.py' (sandbox tests only). "
        "tool.py: define run(payload: dict|None) -> dict. Accept input from payload['input'], "
        "connection from payload['connection'], secrets from payload['secrets'], runtime flags from payload['_runtime']. "
        "test_tool.py: import and dry-run tool.py locally. NO external network, NO live side effects. "
        "Never embed secrets in code, tests, logs, or schemas."
    )
    
    def __init__(self, profile: CapabilityProfile):
        self.profile = profile
    
    def generate_system_prompt(self) -> str:
        """Generate context-aware system guidance."""
        category = self.profile.infer_capability_category()
        richness = self.profile.schema_richness()
        has_state = self.profile.requires_external_state()
        
        parts = [self.BASE_GUIDANCE, self.OUTPUT_FORMAT, self.FILE_REQUIREMENTS]
        
        # Category-specific guidance (generic, not hardcoded)
        if category == "data_storage":
            parts.append(self._guidance_data_storage(richness, has_state))
        elif category == "scheduler":
            parts.append(self._guidance_scheduler())
        elif category == "api_client":
            parts.append(self._guidance_api_client(richness))
        elif category == "data_processor":
            parts.append(self._guidance_data_processor(richness))
        
        # Complexity-level specific guidance
        if self.profile.complexity in ("intermediate", "advanced"):
            parts.append(self._guidance_advanced_complexity())
        
        # Runtime policy guidance
        if self.profile.runtime_policy:
            parts.append(self._guidance_runtime_policy(self.profile.runtime_policy))
        
        # Schema handling guidance
        if richness == "high":
            parts.append(self._guidance_complex_schema())
        
        return "\n\n".join(parts)
    
    def _guidance_data_storage(self, richness: str, has_state: bool) -> str:
        """Guidance for data storage / CRUD capabilities."""
        guidance = (
            "Capability type: Data Storage. "
            "Implement CRUD operations (create, read, update, delete, list, search) for record storage. "
            "Logic: parse input['operation'] to route to appropriate handler. "
            "Each handler validates input, interacts with connection (database/file/memory), returns result dict."
        )
        if has_state:
            guidance += (
                " Use connection['memory_database_path'] or equivalent for persistent storage. "
                "Initialize/connect on first call, not on import."
            )
        if richness == "high":
            guidance += (
                " Input schema is rich—implement parameter mapping from input schema properties to backend queries. "
                "Support filters, pagination, search criteria as defined in input schema."
            )
        return guidance
    
    def _guidance_scheduler(self) -> str:
        """Guidance for time-based scheduling capabilities."""
        return (
            "Capability type: Scheduler / Time-based Execution. "
            "Implement schedule CRUD and execution management: parse operation (create, get, list, update, delete, execute). "
            "Each schedule record includes timing metadata (start_time, end_time, recurrence, etc). "
            "DO NOT hardcode cron job execution—this tool manages schedule definitions and metadata, not system-level job dispatch. "
            "Return operation results (created schedule ID, list of schedules, execution status, etc) as JSON in output dict."
        )
    
    def _guidance_api_client(self, richness: str) -> str:
        """Guidance for API client capabilities."""
        guidance = (
            "Capability type: API Client. "
            "Implement HTTP request routing: parse input['operation'] or input['method'] to build appropriate request. "
            "Use connection['api_endpoint'], ['auth_type'], etc from connection schema. "
            "Validate input per input_schema, build request headers/body, send request, parse response. "
            "Return response status and body as JSON."
        )
        if richness == "high":
            guidance += (
                " Support multiple endpoint types, request formats, response parsing strategies based on input parameters."
            )
        return guidance
    
    def _guidance_data_processor(self, richness: str) -> str:
        """Guidance for data transformation / processing capabilities."""
        guidance = (
            "Capability type: Data Processor. "
            "Implement data transformation: parse input['operation'] or input['format'] to select transformation logic. "
            "Accept input data (from input[...]), apply processing, return transformed output in output schema format."
        )
        if richness == "high":
            guidance += (
                " Support multiple transformation types, chained operations, format conversions based on input schema properties."
            )
        return guidance
    
    def _guidance_advanced_complexity(self) -> str:
        """Guidance for intermediate/advanced complexity capabilities."""
        return (
            "Complexity level: Advanced. "
            "Implement comprehensive error handling: validate all inputs, catch exceptions, return structured error dicts. "
            "Add logging/tracing if runtime supports it. Support partial success scenarios (some records processed, some failed). "
            "Implement retry logic where applicable (transient failures, connection issues)."
        )
    
    def _guidance_runtime_policy(self, policy: dict[str, Any]) -> str:
        """Guidance based on runtime execution policy."""
        parts = []
        
        side_effects = policy.get("side_effects")
        if side_effects == "read_only":
            parts.append("Runtime policy: READ ONLY. Do not write, modify, or delete external state.")
        elif side_effects == "external_write":
            parts.append("Runtime policy: EXTERNAL WRITE. Implement state modification with proper validation and rollback awareness.")
        
        classification = policy.get("classification_source")
        if classification:
            parts.append(f"Classification source: {classification}. Respect declared side effects classification.")
        
        return " ".join(parts) if parts else ""
    
    def _guidance_complex_schema(self) -> str:
        """Guidance for rich input/output schemas."""
        return (
            "Schema guidance: Input schema is complex with many properties. "
            "Implement flexible parameter handling: support optional fields, defaults, and field-level validation. "
            "Extract parameters dynamically from input schema properties rather than hardcoding field names."
        )


def build_generation_prompt_messages(
    *,
    tool_id: str,
    complexity: str,
    input_schema: dict[str, Any],
    output_schema: dict[str, Any],
    connection_schema: dict[str, Any],
    secret_schema: dict[str, Any],
    behavior_contract: str | dict[str, Any],
    runtime_policy: dict[str, Any] | None = None,
    contract_json: str | dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    """Build dynamic, context-aware code generation messages.
    
    This is a wrapper that creates CapabilityProfile and DynamicPromptTemplate,
    then returns the full messages list for LLM completion.
    
    Args:
        tool_id: Capability identifier
        complexity: Capability complexity (basic, intermediate, advanced)
        input_schema: Input schema (used for richness assessment)
        output_schema: Output schema
        connection_schema: Connection schema (used to detect external state needs)
        secret_schema: Secret schema
        behavior_contract: Natural language or structured behavior requirements
        runtime_policy: Optional runtime execution policy dict
        contract_json: Full contract to pass as user message (if None, minimal contract is built)
    
    Returns:
        Messages list: [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_content}]
    """
    # Build capability profile for inference
    profile = CapabilityProfile(
        tool_id=tool_id,
        complexity=complexity,
        input_schema=input_schema,
        output_schema=output_schema,
        connection_schema=connection_schema,
        secret_schema=secret_schema,
        behavior_contract=behavior_contract,
        runtime_policy=runtime_policy,
    )
    
    # Generate dynamic system prompt
    template = DynamicPromptTemplate(profile)
    system_prompt = template.generate_system_prompt()
    
    # User message: full contract or minimal JSON
    if isinstance(contract_json, dict):
        user_content = json.dumps(contract_json, ensure_ascii=False, separators=(",", ":"), default=str)
    elif isinstance(contract_json, str):
        user_content = contract_json
    else:
        # Minimal contract if not provided
        user_content = json.dumps({
            "tool_id": tool_id,
            "complexity": complexity,
            "behavior_contract": behavior_contract if isinstance(behavior_contract, str) else json.dumps(behavior_contract),
            "input_schema": input_schema,
            "output_schema": output_schema,
        }, ensure_ascii=False, separators=(",", ":"), default=str)
    
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]
