from pathlib import Path

root = Path(__file__).resolve().parents[1]
html = (root / 'apps/web/agent_studio.html').read_text()
param = (root / 'auxiliary_brain/parameters/agent_parameter_contract.py').read_text()
primary = (root / 'ai_core/agent_delegation/primary_brain_client.py').read_text()

assert 'const canStart = await ensureSelectedModelCredential();' in html
send_pos = html.index('async function sendMessage()')
try_pos = html.index('  try{', send_pos)
ensure_pos = html.index('const canStart = await ensureSelectedModelCredential();', send_pos)
assert try_pos < ensure_pos, 'model credential check must be inside sendMessage try block'
assert 'Model settings could not be saved before this request' in html
assert 'await refreshSessions();' in html[send_pos:html.index('function addMissingInputs', send_pos)]

assert 'return False' in param[param.index('def _looks_like_self_contained_runtime_observation'):param.index('def _looks_like_open_capability')]
assert 'return None' in primary[primary.index('def _try_self_contained_runtime_observation'):primary.index('def _build', primary.index('def _try_self_contained_runtime_observation'))]
assert 'The current time is' not in primary
print('v22.3 UI send and no fixed runtime-observation shortcut checks passed')
