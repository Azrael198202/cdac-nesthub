import asyncio
import os
from typing import List, Optional
from ai_core.events.event_bus import event_bus


class CommandRunner:
    async def run_streaming(
        self,
        run_id: str,
        title: str,
        commands: List[str],
        cwd: Optional[str] = None,
    ) -> int:
        for command in commands:
            await event_bus.emit(run_id, {
                "type": "COMMAND_STARTED",
                "title": title,
                "command": command,
                "message": f"Running command: {command}",
            })

            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )

            async def pump(stream, stream_name: str):
                while True:
                    line = await stream.readline()
                    if not line:
                        break
                    await event_bus.emit(run_id, {
                        "type": "COMMAND_OUTPUT",
                        "stream": stream_name,
                        "line": line.decode(errors="replace").rstrip(),
                    })

            await asyncio.gather(
                pump(process.stdout, "stdout"),
                pump(process.stderr, "stderr"),
            )

            code = await process.wait()
            await event_bus.emit(run_id, {
                "type": "COMMAND_FINISHED",
                "command": command,
                "returncode": code,
                "message": f"Command finished with code {code}",
            })

            if code != 0:
                return code
        return 0
