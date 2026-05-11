import os
import platform
import shutil
from pathlib import Path


class BinaryResolver:
    """
    Generic executable resolver for runtime commands.
    """

    def resolve(self, binary_name: str) -> str | None:
        found = shutil.which(binary_name)
        if found:
            return found

        if platform.system().lower() == "windows":
            return self._resolve_windows(binary_name)

        return None

    def _resolve_windows(self, binary_name: str) -> str | None:
        candidates = []
        local = os.getenv("LOCALAPPDATA")
        pf = os.getenv("ProgramFiles")
        pfx86 = os.getenv("ProgramFiles(x86)")

        if binary_name.lower() == "ollama":
            if local:
                candidates.append(Path(local) / "Programs" / "Ollama" / "ollama.exe")
            if pf:
                candidates.append(Path(pf) / "Ollama" / "ollama.exe")
            if pfx86:
                candidates.append(Path(pfx86) / "Ollama" / "ollama.exe")

        for item in candidates:
            if item.exists():
                return str(item)

        return None

    def rewrite_command(self, command: str) -> str:
        parts = command.strip().split()
        if not parts:
            return command

        binary = parts[0]
        resolved = self.resolve(binary)
        if not resolved:
            return command

        rest = parts[1:]
        if " " in resolved:
            resolved = f'"{resolved}"'
        return " ".join([resolved] + rest)
