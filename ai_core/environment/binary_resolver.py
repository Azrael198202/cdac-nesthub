import os
import platform
import shutil
from pathlib import Path


class BinaryResolver:
    def system_key(self) -> str:
        name = platform.system().lower()
        if name == "darwin":
            return "macos"
        if name.startswith("win"):
            return "windows"
        if name == "linux":
            return "linux"
        return name

    def resolve(self, binary_name: str, executable_hints: dict | None = None) -> str | None:
        found = shutil.which(binary_name)
        if found:
            return found

        system = self.system_key()
        for raw in (executable_hints or {}).get(system, []):
            expanded = os.path.expandvars(raw)
            path = Path(expanded)
            if path.exists():
                return str(path)
        return None

    def quote(self, value: str) -> str:
        if not value:
            return value
        if value.startswith('"') and value.endswith('"'):
            return value
        return f'"{value}"' if " " in value else value
