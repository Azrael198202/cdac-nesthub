from __future__ import annotations

from ai_core.config.paths import (
    RUNTIME_CAPABILITIES_DIR,
    RUNTIME_CONFIGS_DIR,
    RUNTIME_DATASETS_DIR,
    RUNTIME_INTENTS_DIR,
    RUNTIME_KNOWLEDGE_DIR,
    RUNTIME_LOGS_DIR,
    RUNTIME_MEMORY_DIR,
    RUNTIME_MODELS_DIR,
    RUNTIME_PROMPTS_DIR,
    RUNTIME_SECRETS_DIR,
    RUNTIME_TOOLS_DIR,
    RUNTIME_TRACES_DIR,
    RUNTIME_WORKFLOWS_DIR,
)
from ai_core.config.io import read_json, write_json


class RuntimeBootstrap:
    """Create only base runtime folders. No intent/workflow/prompt is preloaded."""

    def ensure_runtime_base(self) -> None:
        for path in [
            RUNTIME_CONFIGS_DIR,
            RUNTIME_PROMPTS_DIR,
            RUNTIME_WORKFLOWS_DIR,
            RUNTIME_INTENTS_DIR,
            RUNTIME_MODELS_DIR,
            RUNTIME_TOOLS_DIR,
            RUNTIME_CAPABILITIES_DIR,
            RUNTIME_KNOWLEDGE_DIR / "success_cases",
            RUNTIME_KNOWLEDGE_DIR / "methods",
            RUNTIME_MEMORY_DIR,
            RUNTIME_TRACES_DIR,
            RUNTIME_DATASETS_DIR,
            RUNTIME_SECRETS_DIR,
            RUNTIME_LOGS_DIR,
        ]:
            path.mkdir(parents=True, exist_ok=True)
        secrets = RUNTIME_SECRETS_DIR / "local_secrets.json"
        if not secrets.exists():
            write_json(secrets, {"providers": {}})

    def has_api_key(self, provider: str) -> bool:
        data = read_json(RUNTIME_SECRETS_DIR / "local_secrets.json", {"providers": {}})
        return bool(data.get("providers", {}).get(provider, {}).get("api_key"))
