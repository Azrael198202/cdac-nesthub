from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
AI_CORE_DIR = ROOT_DIR / "ai_core"
CONFIGS_DIR = ROOT_DIR / "configs"
SCHEMA_DIR = ROOT_DIR / "schema"
RUNTIME_DIR = ROOT_DIR / "runtime"
RUNTIME_CONFIGS_DIR = RUNTIME_DIR / "configs"
RUNTIME_LOGS_DIR = RUNTIME_DIR / "logs"
RUNTIME_TRACES_DIR = RUNTIME_DIR / "traces"
RUNTIME_KNOWLEDGE_DIR = RUNTIME_DIR / "knowledge"
RUNTIME_DATASETS_DIR = RUNTIME_DIR / "datasets"
RUNTIME_GENERATED_DIR = RUNTIME_DIR / "generated"


def ensure_runtime_dirs() -> None:
    for path in [
        RUNTIME_CONFIGS_DIR / "environment",
        RUNTIME_CONFIGS_DIR / "models",
        RUNTIME_CONFIGS_DIR / "workflows",
        RUNTIME_CONFIGS_DIR / "prompts",
        RUNTIME_CONFIGS_DIR / "intents",
        RUNTIME_CONFIGS_DIR / "tools",
        RUNTIME_LOGS_DIR,
        RUNTIME_TRACES_DIR,
        RUNTIME_KNOWLEDGE_DIR,
        RUNTIME_DATASETS_DIR,
        RUNTIME_GENERATED_DIR,
    ]:
        path.mkdir(parents=True, exist_ok=True)
