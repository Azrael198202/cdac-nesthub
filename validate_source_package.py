#!/usr/bin/env python3
from __future__ import annotations

import importlib
import json
import pathlib
import sys

root = pathlib.Path(__file__).resolve().parent
errors: list[str] = []

server = root / 'apps' / 'api' / 'server.py'
text = server.read_text(encoding='utf-8')
if 'from ai_core.context.session_memory_store import SessionMemoryStore' not in text:
    errors.append('apps/api/server.py is missing SessionMemoryStore import')
if 'session_store = SessionMemoryStore()' not in text:
    errors.append('apps/api/server.py does not instantiate SessionMemoryStore')
if not (root / 'scripts' / 'reset_runtime_data.py').exists():
    errors.append('scripts/reset_runtime_data.py is missing')

pycache = [str(p.relative_to(root)) for p in root.rglob('__pycache__')]
pyc = [str(p.relative_to(root)) for p in root.rglob('*.pyc')]
if pycache or pyc:
    errors.append('package contains Python cache files')

mds = [p.relative_to(root).as_posix() for p in root.rglob('*.md')]
allowed_mds = ['README.md', 'docs/RUNTIME_GENERATED_COGNITIVE_OS_PLAN.md']
if mds != allowed_mds:
    errors.append(f'expected markdown files {allowed_mds}, got {mds}')

sys.path.insert(0, str(root))
try:
    module = importlib.import_module('apps.api.server')
    if not hasattr(module, 'app'):
        errors.append('apps.api.server imported but app is missing')
    if type(module.session_store).__name__ != 'SessionMemoryStore':
        errors.append('session_store is not SessionMemoryStore')
except Exception as exc:
    errors.append(f'app import failed: {exc!r}')

result = {'ok': not errors, 'errors': errors, 'markdown_files': mds}
print(json.dumps(result, ensure_ascii=False, indent=2))
raise SystemExit(0 if result['ok'] else 1)
