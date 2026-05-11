from __future__ import annotations

import json
from pathlib import Path
from typing import Any

try:
    import yaml
except Exception:  # pragma: no cover
    yaml = None


class ConfigLoader:
    def __init__(self, root: str | Path = "configs"):
        self.root = Path(root)

    def load(self, relative_path: str) -> dict[str, Any]:
        path = self.root / relative_path
        return self.load_path(path)

    @staticmethod
    def load_path(path: str | Path) -> dict[str, Any]:
        config_path = Path(path)
        content = config_path.read_text(encoding="utf-8")
        suffix = config_path.suffix.lower()

        if suffix == ".json":
            return json.loads(content)

        if suffix in {".yaml", ".yml"}:
            if yaml is None:
                raise RuntimeError("PyYAML is required to parse YAML configuration files")
            data = yaml.safe_load(content)
            return data or {}

        raise ValueError(f"Unsupported config format: {config_path}")
