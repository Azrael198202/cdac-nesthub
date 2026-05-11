import compileall
from pathlib import Path
assert compileall.compile_dir('.', quiet=1)
text=Path('ai_core/nodes/node_runner.py').read_text(encoding='utf-8')
for forbidden in ['input_parsing','intent_recognition','weather','flight','booking','Tokyo']:
    assert forbidden not in text, f'Forbidden token in node_runner.py: {forbidden}'
print('smoke ok')
