import asyncio
import os
import platform
import shlex
from ai_core.events.event_bus import event_bus
from ai_core.environment.auto_answer_engine import AutoAnswerEngine


class PtyRunner:
    def __init__(self) -> None:
        self.auto_answer = AutoAnswerEngine()

    async def run(self, run_id: str, command: str, timeout_seconds: int, auto_answer: bool = True) -> int:
        if platform.system().lower() == "windows":
            # Windows ConPTY support is intentionally avoided here.
            # Fallback to normal subprocess runner in CommandRunner.
            return 9998

        import pty

        master_fd, slave_fd = pty.openpty()
        process = await asyncio.create_subprocess_shell(
            command,
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            close_fds=True,
        )
        os.close(slave_fd)

        async def read_loop():
            buffer = b""
            while True:
                try:
                    chunk = await asyncio.to_thread(os.read, master_fd, 1024)
                except OSError:
                    break
                if not chunk:
                    break
                buffer += chunk
                text = chunk.decode(errors="replace")
                for line in text.splitlines():
                    await event_bus.emit(run_id, {
                        "type": "COMMAND_OUTPUT",
                        "stream": "pty",
                        "line": line,
                        "progress": 50
                    })
                    if auto_answer:
                        answer = self.auto_answer.find_answer(line)
                        if answer is not None:
                            os.write(master_fd, (answer + "\n").encode())
                            await event_bus.emit(run_id, {
                                "type": "AUTO_ANSWER",
                                "title": "Auto answered CLI prompt",
                                "message": f"{line.strip()} -> {answer}",
                                "progress": 50
                            })

        reader = asyncio.create_task(read_loop())
        try:
            await asyncio.wait_for(process.wait(), timeout=timeout_seconds)
        except asyncio.TimeoutError:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            reader.cancel()
            try:
                os.close(master_fd)
            except OSError:
                pass
            return 124

        await reader
        try:
            os.close(master_fd)
        except OSError:
            pass
        return int(process.returncode or 0)
