from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_DIR = PROJECT_ROOT / "runtime"
RUNTIME_CONFIGS = RUNTIME_DIR / "configs"
RUNTIME_LOGS = RUNTIME_DIR / "logs"
RUNTIME_CHECKPOINTS = RUNTIME_DIR / "checkpoints"
RUNTIME_TRACES = RUNTIME_DIR / "traces"
