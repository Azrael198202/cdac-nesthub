from pathlib import Path
contract = Path('auxiliary_brain/parameters/agent_parameter_contract.py').read_text()
assert 'self_contained_runtime_observation' not in contract
assert '_looks_like_self_contained_runtime_observation' not in contract
assert 'current_markers' not in contract and 'temporal_markers' not in contract
primary = Path('ai_core/agent_delegation/primary_brain_client.py').read_text()
assert 'Agent actions and substeps planned' in primary
assert 'locked fixed execution options' in primary
assert 'No participant produced verified user-facing material' in primary
assert 'agent_action_planning' in primary
print('v22.4 fake-time shortcut and planner-answer guard verified')
