from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
AI_CORE_DIR = PROJECT_ROOT / "ai_core"
RUNTIME_DIR = PROJECT_ROOT / "runtime"
CONFIGS_DIR = PROJECT_ROOT / "configs"
SCHEMA_DIR = PROJECT_ROOT / "schema"
APPS_DIR = PROJECT_ROOT / "apps"


def ensure_runtime_dirs() -> None:
    for sub in [
        "configs/workflows",
        "configs/prompts",
        "configs/models",
        "configs/intents",
        "configs/capabilities",
        "configs/tools",
        "configs/security",
        "configs/memory",
        "generated/tools",
        "generated/agents",
        "generated/schemas",
        "knowledge/cases",
        "knowledge/methods",
        "datasets",
        "traces",
        "logs",
        "secrets",
    ]:
        (RUNTIME_DIR / sub).mkdir(parents=True, exist_ok=True)
