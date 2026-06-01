from pathlib import Path
import ast
import yaml

ROOT = Path(__file__).resolve().parents[1]
handler = ROOT / 'ai_core/llm/provider_handlers/universal_model_handler.py'
source = handler.read_text(encoding='utf-8')
ast.parse(source)
required = [
    '_import_ollama_model_from_gguf',
    '_resolve_ollama_gguf_path',
    '_render_ollama_modelfile',
    'auto_import_gguf_missing_model',
    'ollama create',
    'FROM {gguf_path.as_posix()}',
]
missing = [x for x in required if x not in source]
if missing:
    raise SystemExit(f'Missing GGUF import support markers: {missing}')

providers = yaml.safe_load((ROOT / 'runtime/configs/models/providers.yaml').read_text(encoding='utf-8'))
ollama = providers['providers']['ollama']
if not ollama.get('auto_import_gguf_missing_model'):
    raise SystemExit('ollama.auto_import_gguf_missing_model is not enabled')
models = ollama.get('gguf_models') or {}
for key in ['qwen3.5:2b-instruct', 'qwen3.5:4b-instruct']:
    if key not in models:
        raise SystemExit(f'Missing GGUF model config for {key}')
    entry = models[key]
    if not (entry.get('local_path_env') and entry.get('url_env')):
        raise SystemExit(f'Missing local_path_env/url_env for {key}')

md = ROOT / 'ai_core/models/model_downloader.py'
mds = md.read_text(encoding='utf-8')
ast.parse(mds)
for marker in ['ollama_gguf', '_prepare_ollama_gguf', '_resolve_or_download_gguf']:
    if marker not in mds:
        raise SystemExit(f'Model downloader missing {marker}')
print('verify_ollama_gguf_import_support: OK')
