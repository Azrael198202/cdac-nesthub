import os
from typing import ClassVar
from ai_core.config.loader import ConfigLoader
from ai_core.config.paths import RUNTIME_CONFIGS


class SecretStore:
    _memory_cache: ClassVar[dict[str, str]] = {}
    """
    Local runtime secret store.

    Development use only. In production, replace with OS keychain,
    Vault, cloud secret manager, or encrypted storage.
    """

    def __init__(self) -> None:
        self.loader = ConfigLoader()
        self.path = RUNTIME_CONFIGS / "secrets" / "secrets.json"

    def get(self, key: str) -> str | None:
        key = str(key or "").strip()
        if not key:
            return None
        value = os.getenv(key)
        if value:
            self._memory_cache[key] = value
            return value
        if key in self._memory_cache and self._memory_cache[key]:
            return self._memory_cache[key]
        data = self.loader.load_json(self.path)
        value = data.get(key)
        if value:
            self._memory_cache[key] = str(value)
            os.environ.setdefault(key, str(value))
            return str(value)
        return None

    def set(self, key: str, value: str) -> None:
        key = str(key or "").strip()
        value = str(value or "")
        if not key or not value:
            return
        data = self.loader.load_json(self.path)
        data[key] = value
        self.loader.save_json(self.path, data)
        self._memory_cache[key] = value
        os.environ[key] = value

    def has(self, key: str) -> bool:
        return bool(self.get(key))
