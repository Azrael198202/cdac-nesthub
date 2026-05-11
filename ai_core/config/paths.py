from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_DIR = PROJECT_ROOT / "runtime"
RUNTIME_CONFIGS = RUNTIME_DIR / "configs"
RUNTIME_CHECKPOINTS = RUNTIME_DIR / "checkpoints"
RUNTIME_TRACES = RUNTIME_DIR / "traces"
RUNTIME_KNOWLEDGE = RUNTIME_DIR / "knowledge"
RUNTIME_DATASETS = RUNTIME_DIR / "datasets"
RUNTIME_GENERATED = RUNTIME_DIR / "generated"
RUNTIME_REGISTRY = RUNTIME_DIR / "registry"
