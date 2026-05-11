import os
import platform
import shutil
from pathlib import Path
from typing import Tuple
import httpx
from ai_core.events.event_bus import event_bus
from ai_core.environment.command_runner import CommandRunner


class CapabilityVerifier:
    def __init__(self) -> None:
        self.runner = CommandRunner()

    def _os_key(self) -> str:
        s = platform.system().lower()
        return "windows" if s == "windows" else "darwin" if s == "darwin" else "linux"

    def _expand_path(self, path: str) -> Path:
        return Path(os.path.expandvars(os.path.expanduser(path)))

    def _commands_for_os(self, command_map: dict | list | None) -> list[str]:
        if not command_map:
            return []
        if isinstance(command_map, list):
            return command_map
        key = self._os_key()
        return list(command_map.get(key, [])) + list(command_map.get("all", []))

    async def is_satisfied(self, run_id: str, spec: dict) -> Tuple[bool, str]:
        detect = spec.get("detect", {})
        verify = spec.get("verify", {})
        for env_key in detect.get("env_keys", []) + verify.get("env_keys", []):
            if not os.getenv(env_key):
                return False, f"Missing env key: {env_key}"
        for binary in detect.get("binary", []):
            await event_bus.emit(run_id, {"type": "CAPABILITY_CHECK", "title": "Checking binary", "message": binary})
            if not shutil.which(binary):
                return False, f"Binary not found: {binary}"
        for path in (detect.get("paths", {}).get(self._os_key(), []) + detect.get("paths", {}).get("all", []) + verify.get("paths", {}).get(self._os_key(), []) + verify.get("paths", {}).get("all", [])):
            if not self._expand_path(path).exists():
                return False, f"Path not found: {path}"
        for url in verify.get("health_urls", []):
            await event_bus.emit(run_id, {"type": "CAPABILITY_CHECK", "title": "Checking health url", "message": url})
            try:
                async with httpx.AsyncClient(timeout=2.5) as client:
                    r = await client.get(url)
                    if r.status_code >= 400:
                        return False, f"Health check failed: {url}"
            except Exception as exc:
                return False, f"Health check failed: {url} ({exc})"
        for cmd in self._commands_for_os(verify.get("commands")):
            code = await self.runner.run_streaming(run_id, f"Verify {spec.get('capability_id')}", [cmd])
            if code != 0:
                return False, f"Verify command failed: {cmd}"
        return True, "satisfied"
