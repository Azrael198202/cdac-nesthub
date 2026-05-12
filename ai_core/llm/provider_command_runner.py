import asyncio
from ai_core.events.event_bus import event_bus
from ai_core.llm.provider_handlers.base import ProviderCommandResult


class ProviderCommandRunner:
    async def run(self, run_id: str, title: str, command: str, timeout_seconds: int = 3600) -> ProviderCommandResult:
        result = ProviderCommandResult(returncode=-1, command=command)

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
                text = line.decode(errors="replace").rstrip()
                if name == "stdout":
                    result.stdout_lines.append(text)
                else:
                    result.stderr_lines.append(text)
                await event_bus.emit(run_id, {
                    "type": "PROVIDER_COMMAND_OUTPUT",
                    "title": "Provider command output",
                    "message": text,
                    "stream": name,
                })

        task = asyncio.gather(pump(process.stdout, "stdout"), pump(process.stderr, "stderr"))

        try:
            await asyncio.wait_for(process.wait(), timeout=timeout_seconds)
        except asyncio.TimeoutError:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            result.returncode = 124
            await event_bus.emit(run_id, {
                "type": "PROVIDER_COMMAND_TIMEOUT",
                "title": "Provider command timeout",
                "message": command,
            })
            return result

        await task
        result.returncode = int(process.returncode or 0)
        await event_bus.emit(run_id, {
            "type": "PROVIDER_COMMAND_FINISHED",
            "title": "Provider command finished",
            "message": f"returncode={result.returncode}",
            "returncode": result.returncode,
        })
        return result
