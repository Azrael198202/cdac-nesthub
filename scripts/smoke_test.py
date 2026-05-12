import compileall
from pathlib import Path

assert compileall.compile_dir('.', quiet=1)

# The generic node runner must remain free of runtime node semantics.
text = Path('ai_core/nodes/node_runner.py').read_text(encoding='utf-8')
for forbidden in ['input_parsing', 'intent_recognition']:
    assert forbidden not in text, f'Forbidden token in node_runner.py: {forbidden}'

print('smoke ok')
