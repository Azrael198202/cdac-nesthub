# v16.1 Hotfix Import Validation

Fix applied:
- Restored `ai_core/runtime/external_runtimes/` package.
- Restored `gguf_model_resolver.py` used by `ai_core.models.model_downloader`.

Validation commands executed:

```bash
python -m compileall -q ai_core auxiliary_brain apps/api
PYTHONPATH=. python -c "import ai_core.runtime.external_runtimes.gguf_model_resolver"
PYTHONPATH=. python -c "import ai_core.models.model_downloader"
PYTHONPATH=. python -c "import ai_core.runtime.modeling.model_runtime_preflight"
```

Result:
- Python compile validation passed.
- The missing module import path is restored.
