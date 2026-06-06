from pathlib import Path
html = Path('apps/web/agent_studio.html').read_text(encoding='utf-8')
start = html.index('async function sendMessage()')
end = html.index('function addMissingInputs', start)
body = html[start:end]
assert "addMessage(text,'item user')" in body, 'send should append user message'
assert 'postStudioMessage({' in body, 'send should submit runtime request through postStudioMessage'
assert "fetch('/api/agent-studio/message'" in html, 'postStudioMessage must call backend message API'
assert 'ensureSelectedModelCredential' not in body, 'sendMessage must not be blocked by frontend model credential guard'
assert "addProgressMessage('submitting request to runtime')" in body, 'UI should show that backend submit was triggered'
assert 'await refreshSessions()' in body and 'await refreshState()' in body, 'send should refresh sessions and runtime state after response'
print('v22.3 send event trigger verification passed')
