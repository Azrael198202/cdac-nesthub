from auxiliary_brain.capability_acquisition.code_generator import RuntimeBlueprintArtifactGenerator


def test_generated_artifact_contract_guard_rejects_optional_truthiness_gate():
    source = '''
def run(payload):
    input_data = payload['input'] if isinstance(payload, dict) else payload
    first = input_data.get('first', '')
    second = input_data.get('second', [])
    if not all([first, second]):
        return {'status': 'error'}
    return {'status': 'success'}
'''
    artifact = {'files': [{'path': 'tool.py', 'content': source}, {'path': 'test_tool.py', 'content': 'from tool import run\nassert run({})\n'}]}
    schema = {
        'type': 'object',
        'properties': {'first': {'type': 'string'}, 'second': {'type': 'array'}},
        'required': [],
    }
    guard = RuntimeBlueprintArtifactGenerator()
    violations = guard._generated_artifact_contract_violations(
        artifact,
        input_schema=schema,
        connection_schema={'type': 'object', 'properties': {}, 'required': []},
        secret_schema={'type': 'object', 'properties': {}, 'required': []},
    )
    assert any('input.first' in item for item in violations)
    assert any('input.second' in item for item in violations)


def test_generated_artifact_contract_guard_allows_schema_required_truthiness_gate():
    source = '''
def run(payload):
    input_data = payload['input'] if isinstance(payload, dict) else payload
    first = input_data.get('first', '')
    second = input_data.get('second', [])
    if not all([first, second]):
        return {'status': 'error'}
    return {'status': 'success'}
'''
    artifact = {'files': [{'path': 'tool.py', 'content': source}, {'path': 'test_tool.py', 'content': 'from tool import run\nassert run({})\n'}]}
    schema = {
        'type': 'object',
        'properties': {'first': {'type': 'string'}, 'second': {'type': 'array'}},
        'required': ['first', 'second'],
    }
    guard = RuntimeBlueprintArtifactGenerator()
    violations = guard._generated_artifact_contract_violations(
        artifact,
        input_schema=schema,
        connection_schema={'type': 'object', 'properties': {}, 'required': []},
        secret_schema={'type': 'object', 'properties': {}, 'required': []},
    )
    assert violations == []


def test_provided_blueprint_files_with_optional_truthiness_are_not_accepted():
    source = '''
def run(payload):
    input_data = payload.get('input', {}) if isinstance(payload, dict) else {}
    optional_body = input_data.get('optional_body', '')
    if not optional_body:
        return {'status': 'error', 'message': 'Missing required fields'}
    return {'status': 'success', 'data': {'sent': True}}
'''
    blueprint = {
        'capability_id': 'generic_optional_contract_example',
        'input_schema': {
            'type': 'object',
            'properties': {'optional_body': {'type': 'string'}},
            'required': [],
            'additionalProperties': False,
        },
        'output_schema': {
            'type': 'object',
            'properties': {'status': {'type': 'string'}, 'data': {'type': 'object'}, 'message': {'type': 'string'}},
            'required': ['status'],
        },
        'files': [{'path': 'tool.py', 'content': source}, {'path': 'test_tool.py', 'content': 'from tool import run\nassert run({})\n'}],
        'acquisition_policy': {'allow_llm_code_generation': False},
    }
    artifact = RuntimeBlueprintArtifactGenerator().materialize(blueprint)
    assert artifact['artifact_kind'] != 'real_runtime_implementation'
    assert artifact['code_generation']['status'] == 'provided_blueprint_files_rejected_by_schema_contract'
