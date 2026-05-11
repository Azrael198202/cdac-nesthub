from __future__ import annotations

from pathlib import Path
from typing import Any
import json
import yaml


class ConfigLoader:
    def read(self, path: Path, default: Any = None) -> Any:
        if not path.exists():
            return default
        if path.suffix.lower() in {".yaml", ".yml"}:
            return yaml.safe_load(path.read_text(encoding="utf-8")) or default
        if path.suffix.lower() == ".json":
            return json.loads(path.read_text(encoding="utf-8"))
        return path.read_text(encoding="utf-8")

    def write(self, path: Path, data: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.suffix.lower() in {".yaml", ".yml"}:
            path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
        elif path.suffix.lower() == ".json":
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        else:
            path.write_text(str(data), encoding="utf-8")
