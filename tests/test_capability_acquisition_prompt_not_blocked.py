from __future__ import annotations

import pytest

from ai_core.interaction.conversation_core_runtime import ConversationCoreRuntime


@pytest.mark.asyncio
async def test_acquire_runtime_capability_prompt_for_connected_action_is_not_blocked_by_protocol_details():
    runtime = ConversationCoreRuntime()
    text = """Acquire runtime capability:

Send messages through an external mail service.

The runtime must:
1. Detect whether the capability already exists.
2. If missing, find implementation approaches.
3. Compare available libraries and protocols.
4. Select a solution.
5. Generate implementation.
6. Generate tests.
7. Generate connection schema.
8. Generate secret schema.
9. Execute sandbox validation.
10. Register the capability.
11. Verify capability acquisition.

The capability must support runtime input, persistent connection profile,
secret references, and approval before external execution.
"""
    parsed = {"normalized_input": text, "missing_information": []}
    result = await runtime._intent_recognition(text, parsed, "test_run")
    assert result["capability_gap_detected"] is True
    assert result["intent_type"] == "capability_gap_resolution"
    assert result["requires_external_information"] is True
    assert result.get("missing_information") == []
    assert result["user_value_collection_policy"]["after_registration"] == "collect_runtime_values_from_generated_schemas"


def test_implementation_requested_for_capability_acquisition_words():
    runtime = ConversationCoreRuntime()
    assert runtime._implementation_requested("Acquire runtime capability: Generate implementation, generate tests, register capability.") is True
