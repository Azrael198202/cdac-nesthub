import os
from ai_core.config.loader import ConfigLoader
from ai_core.config.paths import RUNTIME_CONFIGS


class SecretStore:
    """
    Local runtime secret store.

    Development use only. In production, replace with OS keychain,
    Vault, cloud secret manager, or encrypted storage.
    """

    def __init__(self) -> None:
        self.loader = ConfigLoader()
        self.path = RUNTIME_CONFIGS / "secrets" / "secrets.json"

    def get(self, key: str) -> str | None:
        value = os.getenv(key)
        if value:
            return value
        data = self.loader.load_json(self.path)
        return data.get(key)

    def set(self, key: str, value: str) -> None:
        data = self.loader.load_json(self.path)
        data[key] = value
        self.loader.save_json(self.path, data)
