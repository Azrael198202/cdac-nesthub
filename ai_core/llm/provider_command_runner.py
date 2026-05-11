import asyncio
from ai_core.events.event_bus import event_bus


class ProviderCommandRunner:
    async def run(self, run_id: str, title: str, command: str, timeout_seconds: int = 3600) -> int:
        await event_bus.emit(run_id, {
            "type": "PROVIDER_COMMAND_STARTED",
            "title": title,
            "message": command,
            "command": command,
        })

        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.PIPE,
        )

        async def pump(stream, name: str):
            while True:
                line = await stream.readline()
                if not line:
                    break
                await event_bus.emit(run_id, {
                    "type": "PROVIDER_COMMAND_OUTPUT",
                    "title": "Provider command output",
                    "message": line.decode(errors="replace").rstrip(),
                    "stream": name,
                })

        task = asyncio.gather(
            pump(process.stdout, "stdout"),
            pump(process.stderr, "stderr"),
        )

        try:
            await asyncio.wait_for(process.wait(), timeout=timeout_seconds)
        except asyncio.TimeoutError:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            await event_bus.emit(run_id, {
                "type": "PROVIDER_COMMAND_TIMEOUT",
                "title": "Provider command timeout",
                "message": command,
            })
            return 124

        await task
        code = int(process.returncode or 0)

        await event_bus.emit(run_id, {
            "type": "PROVIDER_COMMAND_FINISHED",
            "title": "Provider command finished",
            "message": f"returncode={code}",
            "returncode": code,
        })
        return code
