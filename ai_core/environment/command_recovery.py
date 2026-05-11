from ai_core.events.event_bus import event_bus


class CommandRecovery:
    async def should_retry(self, run_id: str, command: str, returncode: int, attempt: int, max_retries: int) -> bool:
        if attempt >= max_retries:
            return False
        await event_bus.emit(run_id, {
            "type": "COMMAND_RETRY",
            "title": "Command retry scheduled",
            "message": f"Command failed with code {returncode}. Retrying {attempt + 1}/{max_retries}.",
            "command": command
        })
        return True

    async def emit_timeout(self, run_id: str, command: str) -> None:
        await event_bus.emit(run_id, {
            "type": "COMMAND_TIMEOUT",
            "title": "Command timeout",
            "message": command,
            "command": command
        })

    async def emit_recovery(self, run_id: str, command: str) -> None:
        await event_bus.emit(run_id, {
            "type": "COMMAND_RECOVERY",
            "title": "Running recovery command",
            "message": command,
            "command": command
        })
