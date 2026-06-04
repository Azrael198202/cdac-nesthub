from __future__ import annotations

import json
import tempfile
from pathlib import Path

from ai_core.runtime.capability.registered_tool_parameter_bridge import RegisteredToolParameterBridge
from auxiliary_brain.storage.json_store import JsonStore
from auxiliary_brain.studio.service import AgentStudioService
from ai_core.tools.runtime_registered_tool_service import RuntimeRegisteredToolService


def test_structural_source_context_repairs_truncated_structural_value() -> None:
    participant = {
        'capability_profile': {'tool_summary': {'input_schema': {
            'type': 'object',
            'required': ['to', 'subject', 'body'],
            'properties': {
                'to': {'type': 'array', 'items': {'type': 'string', 'format': 'email'}},
                'cc': {'type': 'array', 'items': {'type': 'string', 'format': 'email'}},
                'bcc': {'type': 'array', 'items': {'type': 'string', 'format': 'email'}},
                'subject': {'type': 'string'},
                'body': {'type': 'string'},
            },
        }}},
        'runtime_parameters': {},
    }
    participant['runtime_parameters'] = {
        'to': 'localpart',
        'subject': 's',
        'body': 'b',
        '_source_text': 'please use localpart@example.com as the electronic address',
    }
    result = RegisteredToolParameterBridge().build_invocation(participant=participant, provided_values=participant['runtime_parameters'])
    assert result['ok'] is True, result
    assert result['input_data']['to'] == ['localpart@example.com'], result
    assert 'cc' not in result['input_data'], result
    assert 'bcc' not in result['input_data'], result


def test_json_store_delete() -> None:
    with tempfile.TemporaryDirectory() as td:
        store = JsonStore(td)
        store.write_json('generated/tasks/sample.json', {'x': 1})
        out = store.delete_json('generated/tasks/sample.json')
        assert out['ok'] is True, out
        out2 = store.delete_json('generated/tasks/sample.json')
        assert out2['status'] == 'not_found', out2


if __name__ == '__main__':
    test_structural_source_context_repairs_truncated_structural_value()
    test_json_store_delete()
    print('phase2 repair and deletion verification passed')
