from __future__ import annotations

import shutil
from dataclasses import asdict, dataclass
from typing import Any
from ai_core.utils.safe_subprocess import run_text


@dataclass
class DockerPrecheckResult:
    status: str
    docker_available: bool
    daemon_available: bool
    image: str | None
    image_available: bool
    can_run_container: bool
    details: dict[str, Any]
    reason: str


class DockerPrecheck:
    """Generic Docker precheck check used before isolated runtime execution.

    This class does not know any business domain. It checks whether Docker is
    installed, whether the daemon is reachable, and optionally whether an image
    can be pulled or inspected before generated artifacts are tested.
    """

    def check(self, *, image: str | None = None, pull_if_missing: bool = False, timeout_seconds: int = 120) -> dict[str, Any]:
        docker = shutil.which("docker")
        if not docker:
            return asdict(DockerPrecheckResult(
                status="unavailable",
                docker_available=False,
                daemon_available=False,
                image=image,
                image_available=False,
                can_run_container=False,
                details={},
                reason="docker command is not available.",
            ))

        version = self._run([docker, "version", "--format", "{{json .}}"], timeout_seconds=20)
        daemon_ok = version.get("returncode") == 0
        image_ok = False
        image_details: dict[str, Any] = {}
        if image and daemon_ok:
            inspect = self._run([docker, "image", "inspect", image], timeout_seconds=20)
            if inspect.get("returncode") == 0:
                image_ok = True
                image_details["inspect"] = "available"
            elif pull_if_missing:
                pull = self._run([docker, "pull", image], timeout_seconds=timeout_seconds)
                image_ok = pull.get("returncode") == 0
                image_details["pull"] = pull
            else:
                image_details["inspect"] = inspect
        elif not image:
            image_ok = True

        can_run = bool(daemon_ok and image_ok)
        return asdict(DockerPrecheckResult(
            status="passed" if can_run else "failed",
            docker_available=True,
            daemon_available=daemon_ok,
            image=image,
            image_available=image_ok,
            can_run_container=can_run,
            details={"version": version, "image": image_details},
            reason="Docker precheck passed." if can_run else "Docker precheck failed or image is unavailable.",
        ))

    def _run(self, cmd: list[str], *, timeout_seconds: int) -> dict[str, Any]:
        try:
            proc = run_text(cmd, text=True, capture_output=True, timeout=timeout_seconds)
            return {
                "cmd": cmd,
                "returncode": proc.returncode,
                "stdout": proc.stdout[-4000:],
                "stderr": proc.stderr[-4000:],
            }
        except Exception as exc:
            return {"cmd": cmd, "returncode": -1, "error": str(exc)}
