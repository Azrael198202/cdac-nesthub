from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]
source = (ROOT / 'ai_core/llm/provider_handlers/universal_model_handler.py').read_text(encoding='utf-8')

required_markers = [
    '_ollama_gguf_entry_has_configured_source',
    'prefer_gguf = bool(entry and entry.get("prefer_gguf_import"))',
    'has_gguf_source = bool(entry and self._ollama_gguf_entry_has_configured_source(entry))',
    'if provider.get("auto_import_gguf_missing_model", True) and entry and (prefer_gguf or has_gguf_source):',
    'if prefer_gguf and not provider.get("pull_after_preferred_gguf_import_failure", False):',
]
missing = [m for m in required_markers if m not in source]
if missing:
    raise SystemExit(f'missing direct GGUF precedence markers: {missing}')

first_import = source.index('if provider.get("auto_import_gguf_missing_model", True) and entry and (prefer_gguf or has_gguf_source):')
first_pull = source.index('ok = await self._pull_ollama_model', first_import)
if first_import > first_pull:
    raise SystemExit('GGUF import must be attempted before ollama pull for configured/preferred GGUF entries')

providers = yaml.safe_load((ROOT / 'runtime/configs/models/providers.yaml').read_text(encoding='utf-8'))
ollama = providers['providers']['ollama']
if ollama.get('model') != 'qwen3.5:2b':
    raise SystemExit('default Ollama model must be qwen3.5:2b')
if 'qwen3.5:2b' not in ollama.get('provider_models', {}):
    raise SystemExit('qwen3.5:2b must be available as a normal Ollama tag model')
for model, filename in {
    'qwen3.5:2b-q4_k_m': 'Qwen3.5-2B-Q4_K_M.gguf',
    'qwen3.5:4b-q4_k_m': 'Qwen3.5-4B-Q4_K_M.gguf',
}.items():
    entry = (ollama.get('gguf_models') or {}).get(model)
    if not entry:
        raise SystemExit(f'missing GGUF config for {model}')
    if not entry.get('prefer_gguf_import'):
        raise SystemExit(f'{model} must prefer GGUF import')
    if entry.get('filename') != filename:
        raise SystemExit(f'{model} must prefer {filename}')
    if not entry.get('local_path_env') or not entry.get('url_env'):
        raise SystemExit(f'{model} must support local path and URL GGUF sources')
print('verify_direct_gguf_import_precedence: OK')
