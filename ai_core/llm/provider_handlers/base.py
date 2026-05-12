from dataclasses import dataclass, field
from typing import Any, Protocol


class ProviderUnavailableError(RuntimeError):
    pass


@dataclass
class ProviderCommandResult:
    returncode: int
    stdout_lines: list[str] = field(default_factory=list)
    stderr_lines: list[str] = field(default_factory=list)
    command: str = ""

    @property
    def stdout_text(self) -> str:
        return "\n".join(self.stdout_lines)

    @property
    def stderr_text(self) -> str:
        return "\n".join(self.stderr_lines)

    def summary(self) -> str:
        return (
            f"command={self.command}\n"
            f"returncode={self.returncode}\n"
            f"STDOUT:\n{self.stdout_text}\n\n"
            f"STDERR:\n{self.stderr_text}"
        )


class ProviderHandler(Protocol):
    provider_type: str

    async def generate_json(
        self,
        *,
        run_id: str,
        node_id: str,
        provider_name: str,
        provider: dict[str, Any],
        prompt: dict[str, Any],
        rendered_user_prompt: str,
        schema: dict[str, Any],
    ) -> dict[str, Any]:
        ...
