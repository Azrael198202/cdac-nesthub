from pathlib import Path

root = Path(__file__).resolve().parents[1]
html = (root / 'apps' / 'web' / 'agent_studio.html').read_text(encoding='utf-8')
assert 'Ready for runtime instruction' not in html, 'static ready phrase must not be present'
assert 'No active execution' in html, 'idle state should be neutral and dynamic'
assert 'Progress, current stage, selected brain, and model decision will appear after a request starts.' in html
assert 'header{min-height:96px;height:auto' in html, 'header should allow vertical expansion'
assert 'overflow:visible' in html, 'header/model controls should not be clipped'
assert 'Model mode' in html and 'View mode' in html, 'model and view controls must remain visible'
print('verify_v22_3_header_dynamic_progress_ui: OK')
