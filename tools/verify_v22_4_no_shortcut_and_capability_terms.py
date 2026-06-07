from pathlib import Path
from ai_core.interaction.conversation_core_runtime import ConversationCoreRuntime

root = Path(__file__).resolve().parents[1]
primary = (root / 'ai_core/agent_delegation/primary_brain_client.py').read_text()
assert '_try_self_contained_runtime_observation' not in primary
assert 'runtime_native_observation' not in primary
assert 'self_contained_runtime_observation' not in primary

runtime = ConversationCoreRuntime()
terms = runtime._generic_capability_terms('Acquire runtime capability: sample adapter. Use a standard library if possible.')
assert isinstance(terms, list)
assert terms, 'expected generic capability terms'
query = runtime._capability_gap_query('Acquire runtime capability: sample adapter. Use a standard library if possible.')
assert isinstance(query, str) and query
print('verify_v22_4_no_shortcut_and_capability_terms: OK')
