import asyncio
import platform
from typing import List, Optional
from ai_core.events.event_bus import event_bus
from ai_core.environment.auto_answer_engine import AutoAnswerEngine
from ai_core.environment.command_profile import CommandProfileResolver
from ai_core.environment.command_recovery import CommandRecovery
from ai_core.environment.pty_runner import PtyRunner


class CommandRunner:
    def __init__(self) -> None:
        self.auto_answer = AutoAnswerEngine()
        self.profile_resolver = CommandProfileResolver()
        self.recovery = CommandRecovery()
        self.pty_runner = PtyRunner()

    async def run_streaming(
        self,
        run_id: str,
        title: str,
        commands: List[str],
        cwd: Optional[str] = None
    ) -> int:
        total = max(len(commands), 1)
        final_code = 0

        for index, raw_command in enumerate(commands, start=1):
            profile = self.profile_resolver.resolve(raw_command)
            command = self.profile_resolver.normalize_command(raw_command, profile)
            percent_start = int(((index - 1) / total) * 100)

            await event_bus.emit(run_id, {
                "type": "COMMAND_PROFILE",
                "title": "Command profile detected",
                "message": profile.name,
                "command": command,
                "use_pty": profile.use_pty,
                "timeout_seconds": profile.timeout_seconds,
                "retries": profile.retries,
                "progress": percent_start,
            })

            attempt = 0
            while True:
                attempt += 1
                code = await self._run_one(
                    run_id=run_id,
                    title=title,
                    command=command,
                    cwd=cwd,
                    progress=percent_start,
                    profile=profile,
                )
                final_code = code

                if code == 0:
                    break

                if code == 124:
                    await self.recovery.emit_timeout(run_id, command)

                for recovery_cmd in profile.recovery_commands:
                    await self.recovery.emit_recovery(run_id, recovery_cmd)
                    await self._run_one(
                        run_id=run_id,
                        title="Recovery",
                        command=recovery_cmd,
                        cwd=cwd,
                        progress=percent_start,
                        profile=profile,
                        force_no_pty=True,
                    )

                retry = await self.recovery.should_retry(
                    run_id=run_id,
                    command=command,
                    returncode=code,
                    attempt=attempt,
                    max_retries=max(1, profile.retries),
                )
                if not retry:
                    return code

            percent_done = int((index / total) * 100)
            await event_bus.emit(run_id, {
                "type": "COMMAND_STEP_DONE",
                "title": "Command step completed",
                "message": f"{index}/{total}",
                "progress": percent_done
            })

        return final_code

    async def _run_one(self, run_id, title, command, cwd, progress, profile, force_no_pty=False) -> int:
        await event_bus.emit(run_id, {
            "type": "COMMAND_STARTED",
            "title": title,
            "command": command,
            "progress": progress,
            "message": "Running command"
        })

        use_pty = bool(profile.use_pty and not force_no_pty)
        if use_pty and platform.system().lower() != "windows":
            code = await self.pty_runner.run(
                run_id=run_id,
                command=command,
                timeout_seconds=profile.timeout_seconds,
                auto_answer=profile.auto_answer,
            )
            if code != 9998:
                await event_bus.emit(run_id, {
                    "type": "COMMAND_FINISHED",
                    "command": command,
                    "returncode": code,
                    "progress": 100 if code == 0 else progress,
                    "message": f"Command finished with code {code}"
                })
                return code

        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.PIPE,
            cwd=cwd
        )

        async def pump(stream, stream_name: str):
            line_count = 0
            while True:
                line = await stream.readline()
                if not line:
                    break
                line_count += 1
                decoded = line.decode(errors="replace").rstrip()
                approx = min(95, progress + 5 + line_count)
                await event_bus.emit(run_id, {
                    "type": "COMMAND_OUTPUT",
                    "stream": stream_name,
                    "line": decoded,
                    "progress": approx
                })
                if profile.auto_answer:
                    answer = self.auto_answer.find_answer(decoded)
                    if answer is not None and process.stdin:
                        try:
                            process.stdin.write((answer + "\n").encode())
                            await process.stdin.drain()
                            await event_bus.emit(run_id, {
                                "type": "AUTO_ANSWER",
                                "title": "Auto answered CLI prompt",
                                "message": f"{decoded.strip()} -> {answer}",
                                "progress": approx
                            })
                        except (BrokenPipeError, ConnectionResetError):
                            pass

        pump_task = asyncio.gather(
            pump(process.stdout, "stdout"),
            pump(process.stderr, "stderr")
        )

        try:
            await asyncio.wait_for(process.wait(), timeout=profile.timeout_seconds)
        except asyncio.TimeoutError:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            await pump_task
            await event_bus.emit(run_id, {
                "type": "COMMAND_FINISHED",
                "command": command,
                "returncode": 124,
                "progress": progress,
                "message": "Command timed out"
            })
            return 124

        await pump_task
        code = int(process.returncode or 0)
        await event_bus.emit(run_id, {
            "type": "COMMAND_FINISHED",
            "command": command,
            "returncode": code,
            "progress": 100 if code == 0 else progress,
            "message": f"Command finished with code {code}"
        })
        return code
