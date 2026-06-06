from pathlib import Path
root = Path(__file__).resolve().parents[1]
studio = (root / 'apps/web/agent_studio.html').read_text(encoding='utf-8')
settings = (root / 'apps/web/settings.html').read_text(encoding='utf-8')
assert 'No active execution' in studio
assert 'Start a request to see live progress' in studio
assert 'function renderLocalExecutionDashboard' in studio
assert 'setLocalExecutionStage' in studio
assert 'consoleActions' in studio
assert 'hiddenModelControls' in studio
assert 'Model settings loading' in studio
assert 'href="/settings"' in studio
assert 'Model orchestration' in settings
assert 'settingsModelMode' in settings
assert 'settingsInitialModel' in settings
assert 'saveModelSettings' in settings
assert '/api/agent-studio/model-selection' in settings
assert 'Local / API / Hybrid' in settings
print('verify_v22_3_runtime_execution_center_ui_settings_fix: ok')
