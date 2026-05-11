import asyncio
from typing import List, Optional
from ai_core.events.event_bus import event_bus


class CommandRunner:
    async def run_streaming(
        self,
        run_id: str,
        title: str,
        commands: List[str],
        cwd: Optional[str] = None
    ) -> int:
        total = max(len(commands), 1)
        for index, command in enumerate(commands, start=1):
            percent_start = int(((index - 1) / total) * 100)
            await event_bus.emit(run_id, {
                "type": "COMMAND_STARTED",
                "title": title,
                "command": command,
                "progress": percent_start,
                "message": f"Running command {index}/{total}"
            })

            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd
            )

            async def pump(stream, stream_name: str):
                line_count = 0
                while True:
                    line = await stream.readline()
                    if not line:
                        break
                    line_count += 1
                    # Long shell commands normally cannot expose true progress.
                    # We show safe approximate progress while still streaming real output.
                    approx = min(95, percent_start + 5 + line_count)
                    await event_bus.emit(run_id, {
                        "type": "COMMAND_OUTPUT",
                        "stream": stream_name,
                        "line": line.decode(errors="replace").rstrip(),
                        "progress": approx
                    })

            await asyncio.gather(
                pump(process.stdout, "stdout"),
                pump(process.stderr, "stderr")
            )

            code = await process.wait()
            percent_done = int((index / total) * 100)
            await event_bus.emit(run_id, {
                "type": "COMMAND_FINISHED",
                "command": command,
                "returncode": code,
                "progress": percent_done,
                "message": f"Command finished with code {code}"
            })

            if code != 0:
                return code
        return 0
