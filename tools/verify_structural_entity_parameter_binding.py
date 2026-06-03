from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ai_core.input_parsing.structured_entity_extractor import StructuredEntityExtractor
from ai_core.runtime.capability.registered_tool_parameter_bridge import RegisteredToolParameterBridge
from ai_core.executors.generic_input_parsing_executor import GenericInputParsingExecutor


def main() -> None:
    text = 'Ask SendGmail Agent to send an email to soarwiththewind6@gmail.com with subject "test" and body "hello"'
    extractor = StructuredEntityExtractor()
    extracted = extractor.extract(text)
    assert extracted["values_by_type"]["electronic_address"] == ["soarwiththewind6@gmail.com"], extracted

    bridge = RegisteredToolParameterBridge()
    schema = {
        "type": "object",
        "properties": {
            "to": {"type": "array", "items": {"type": "string", "format": "email"}},
            "subject": {"type": "string"},
            "body": {"type": "string"},
        },
        "required": ["to", "subject", "body"],
    }
    participant = {
        "participant_id": "agent_1",
        "name": "runtime participant",
        "objective": text,
        "runtime_parameters": {"to": ["soarwiththewind"], "subject": "test", "body": "hello"},
        "capability_profile": {"tool_summary": {"input_schema": schema}},
    }
    result = bridge.build_invocation(participant=participant, provided_values=participant["runtime_parameters"])
    assert result["ok"], result
    assert result["input_data"]["to"] == ["soarwiththewind6@gmail.com"], result

    scalar_schema = {
        "type": "object",
        "properties": {"recipient": {"type": "string", "description": "electronic address"}},
        "required": ["recipient"],
    }
    participant2 = {
        "objective": text,
        "runtime_parameters": {"recipient": "soarwiththewind"},
        "capability_profile": {"tool_summary": {"input_schema": scalar_schema}},
    }
    result2 = bridge.build_invocation(participant=participant2, provided_values=participant2["runtime_parameters"])
    assert result2["input_data"]["recipient"] == "soarwiththewind6@gmail.com", result2

    parsed = GenericInputParsingExecutor()._build_parsed_entities(None, {}, text)
    assert parsed["detected_entities"]["email"] == ["soarwiththewind6@gmail.com"], parsed
    print("structural entity extraction and parameter binding verification passed")


if __name__ == "__main__":
    main()
