from pathlib import Path
import ast

root = Path(__file__).resolve().parents[1]
service = root / 'auxiliary_brain' / 'studio' / 'service.py'
source = service.read_text()
ast.parse(source)
assert 'def create_task_graph(self, instruction:' in source
block = source[source.index('def create_task_graph'):source.index('artifact_refs = self._resolve_uploaded_artifacts_for_instruction')]
assert 'instruction=instruction' in block
assert 'instruction=message' not in block
print('verify_v19_message_nameerror_fix: passed')
