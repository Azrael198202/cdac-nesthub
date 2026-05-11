from __future__ import annotations
from pathlib import Path
from typing import Any
import yaml, json

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_CONFIG = ROOT / "runtime" / "configs"
SCHEMA_DIR = ROOT / "schema"

class ConfigLoader:
    def load_yaml(self, relative_path: str) -> dict[str, Any]:
        path = RUNTIME_CONFIG / relative_path
        if not path.exists():
            raise FileNotFoundError(f"Config not found: {path}")
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    def load_json(self, path: Path) -> dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))
