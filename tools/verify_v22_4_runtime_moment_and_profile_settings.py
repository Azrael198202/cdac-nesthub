from auxiliary_brain.capability_acquisition.acquisition_router import RuntimeCapabilityGapImplementer
from auxiliary_brain.capability_acquisition.code_generator import RuntimeBlueprintArtifactGenerator
from ai_core.runtime.modeling.user_model_selection import UserModelSelectionStore
from pathlib import Path
import tempfile

request = '''Acquire runtime capability:
Current value provider.
Use Python standard library only.
Prefer datetime and zoneinfo.
The capability must return the current runtime time at execution moment.
Input parameters:
- timezone: optional string, IANA timezone name, default UTC
- format: optional string, default iso8601
Output fields:
- current_time
- timezone
- utc_offset
- timestamp_iso
- execution_time_utc
'''
imp = RuntimeCapabilityGapImplementer()
blueprint = imp._augment_blueprint_from_user_request({
    'template_id':'runtime_moment_provider',
    'entrypoint': {'module':'tool.py','function':'run'},
    'description': 'Neutral runtime-generated capability blueprint.'
}, user_input=request)
assert set(blueprint['input_schema']['properties']) >= {'timezone','format'}
assert 'operation' not in blueprint['input_schema'].get('required', [])
artifact = RuntimeBlueprintArtifactGenerator().materialize(blueprint, identity_contract={'requested_capability_id':'runtime_moment_provider'})
assert set(artifact['input_schema']['properties']) >= {'timezone','format'}
assert 'operation' not in artifact['input_schema'].get('required', [])
ns = {}
exec(artifact['files'][0]['content'], ns)
result = ns['run']({'input': {'timezone': 'Asia/Tokyo', 'format': 'iso8601'}})
assert result['status'] == 'completed'
assert result['data']['timezone'] == 'Asia/Tokyo'
assert result['data']['timestamp_iso']
assert '2024-01-15' not in str(result)
with tempfile.TemporaryDirectory() as tmp:
    store = UserModelSelectionStore()
    store.path = Path(tmp) / 'model_selection.json'
    updated = store.update({'mode':'local_only','selected_local_model_id':'qwen3.5:2b','presentation_profile':'diagnostic'})
    assert updated['selection']['presentation_profile'] == 'diagnostic'
print('verify_v22_4_runtime_moment_and_profile_settings: passed')
