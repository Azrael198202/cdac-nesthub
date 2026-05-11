from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ai_core.runtime.bootstrap import RuntimeBootstrap
from ai_core.config.paths import RUNTIME_CONFIGS_DIR

RuntimeBootstrap().ensure()
assert (RUNTIME_CONFIGS_DIR / "environment" / "providers.yaml").exists()
assert (RUNTIME_CONFIGS_DIR / "models" / "routes.yaml").exists()
assert (RUNTIME_CONFIGS_DIR / "workflows" / "base_orchestration.yaml").exists()
print("smoke_test: ok")
