"""Runtime secret persistence for local development.

This module is source code and must be included in clean source packages.
It stores user-provided credentials under runtime/configs/secrets/secrets.json,
mirrors them into process memory and os.environ, and never writes generated
runtime result files into source packages.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

from ai_core.config.paths import RUNTIME_CONFIGS


class SecretStore:
    """Small file-backed secret store used by runtime credential recovery.

    The store intentionally has a minimal API used by the runtime:
    - set(key, value)
    - get(key, default="")
    - has(key)

    Values are persisted for local development so a key entered once can be
    reused by later participants and later process restarts. Production
    deployments can replace this implementation with a managed secret backend
    while keeping the same interface.
    """

    _memory_cache: dict[str, str] = {}
    _lock = threading.RLock()

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else RUNTIME_CONFIGS / "secrets" / "secrets.json"

    def set(self, key: str, value: str) -> None:
        key = self._normalize_key(key)
        value = "" if value is None else str(value)
        if not key or not value:
            return
        with self._lock:
            data = self._load_unlocked()
            data[key] = value
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self.path)
            self._memory_cache[key] = value
            os.environ[key] = value

    def get(self, key: str, default: str = "") -> str:
        key = self._normalize_key(key)
        if not key:
            return default
        env_value = os.environ.get(key)
        if env_value:
            return env_value
        with self._lock:
            if key in self._memory_cache and self._memory_cache[key]:
                return self._memory_cache[key]
            data = self._load_unlocked()
            value = data.get(key)
            if value:
                value = str(value)
                self._memory_cache[key] = value
                os.environ[key] = value
                return value
        return default

    def has(self, key: str) -> bool:
        return bool(self.get(key, ""))

    def delete(self, key: str) -> None:
        key = self._normalize_key(key)
        if not key:
            return
        with self._lock:
            data = self._load_unlocked()
            if key in data:
                data.pop(key, None)
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            self._memory_cache.pop(key, None)
            os.environ.pop(key, None)

    def list_keys(self) -> list[str]:
        with self._lock:
            keys = set(self._load_unlocked().keys()) | set(self._memory_cache.keys())
        keys.update(k for k, v in os.environ.items() if k.endswith("_API_KEY") and v)
        return sorted(str(k) for k in keys if k)

    def _load_unlocked(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    @staticmethod
    def _normalize_key(key: str | None) -> str:
        return str(key or "").strip()
