import platform
from ai_core.environment.command_runner import CommandRunner
from ai_core.events.event_bus import event_bus


class CapabilityInstaller:
    def __init__(self) -> None:
        self.runner = CommandRunner()

    def _os_key(self) -> str:
        s = platform.system().lower()
        return "windows" if s == "windows" else "darwin" if s == "darwin" else "linux"

    def _commands_for_os(self, command_map: dict | list | None) -> list[str]:
        if not command_map:
            return []
        if isinstance(command_map, list):
            return command_map
        key = self._os_key()
        return list(command_map.get(key, [])) + list(command_map.get("all", []))

    async def install(self, run_id: str, spec: dict) -> bool:
        commands = self._commands_for_os(spec.get("install"))
        if not commands:
            await event_bus.emit(run_id, {"type": "CAPABILITY_INSTALL_SKIPPED", "title": "No install commands", "message": spec.get("capability_id")})
            return True
        code = await self.runner.run_streaming(run_id, f"Install capability {spec.get('capability_id')}", commands)
        return code == 0

    async def start(self, run_id: str, spec: dict) -> bool:
        start = spec.get("start", {})
        mode = start.get("mode", "none")
        commands = self._commands_for_os(start.get("commands"))
        if mode == "none" or not commands:
            return True
        await event_bus.emit(run_id, {"type": "CAPABILITY_START", "title": "Starting capability", "message": f"{spec.get('capability_id')} mode={mode}"})
        code = await self.runner.run_streaming(run_id, f"Start capability {spec.get('capability_id')}", commands)
        return code == 0 or mode == "background"
