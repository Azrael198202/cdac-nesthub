from __future__ import annotations

from pathlib import Path
from typing import Any

from ai_core.runtime.file_store import FileStore
from ai_core.runtime.paths import RUNTIME_DIR


class RuntimeConfig:
    def __init__(self) -> None:
        self.store = FileStore()

    def workflow(self, workflow_id: str = "base_orchestration") -> dict[str, Any]:
        return self.store.read_yaml(RUNTIME_DIR / f"configs/workflows/{workflow_id}.yaml", {})

    def prompt(self, prompt_name: str) -> str:
        data = self.store.read_yaml(RUNTIME_DIR / f"configs/prompts/{prompt_name}", {})
        return data.get("template", "")

    def model_routes(self) -> dict[str, Any]:
        return self.store.read_yaml(RUNTIME_DIR / "configs/models/model_routes.yaml", {})
