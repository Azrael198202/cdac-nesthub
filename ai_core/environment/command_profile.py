import shlex
from dataclasses import dataclass, field
from ai_core.config.loader import ConfigLoader
from ai_core.config.paths import RUNTIME_CONFIGS


@dataclass
class CommandProfile:
    name: str = "default"
    timeout_seconds: int = 1200
    retries: int = 1
    use_pty: bool = False
    auto_answer: bool = True
    append_args: list[str] = field(default_factory=list)
    prepend_env: dict[str, str] = field(default_factory=dict)
    recovery_commands: list[str] = field(default_factory=list)


class CommandProfileResolver:
    def __init__(self) -> None:
        self.loader = ConfigLoader()

    def resolve(self, command: str) -> CommandProfile:
        data = self.loader.load_yaml(RUNTIME_CONFIGS / "environment" / "command_profiles.yaml")
        default = data.get("default", {})
        profile = CommandProfile(
            name="default",
            timeout_seconds=int(default.get("timeout_seconds", 1200)),
            retries=int(default.get("retries", 1)),
            use_pty=bool(default.get("use_pty", False)),
            auto_answer=bool(default.get("auto_answer", True)),
        )

        cmd_lower = command.strip().lower()
        first = cmd_lower.split()[0] if cmd_lower.split() else ""

        for item in data.get("profiles", []):
            prefix = str(item.get("match_prefix", "")).lower()
            contains = str(item.get("match_contains", "")).lower()
            matched = False
            if prefix and first == prefix:
                matched = True
            if contains and contains in cmd_lower:
                matched = True
            if matched:
                profile.name = item.get("name", profile.name)
                profile.timeout_seconds = int(item.get("timeout_seconds", profile.timeout_seconds))
                profile.retries = int(item.get("retries", profile.retries))
                profile.use_pty = bool(item.get("use_pty", profile.use_pty))
                profile.auto_answer = bool(item.get("auto_answer", profile.auto_answer))
                profile.append_args = list(item.get("append_args", []))
                profile.prepend_env = dict(item.get("prepend_env", {}))
                profile.recovery_commands = list(item.get("recovery_commands", []))
                break

        return profile

    def normalize_command(self, command: str, profile: CommandProfile) -> str:
        normalized = command

        for arg in profile.append_args:
            if arg not in normalized:
                normalized = f"{normalized} {arg}"

        if profile.prepend_env:
            env_part = " ".join(f"{k}={shlex.quote(str(v))}" for k, v in profile.prepend_env.items())
            normalized = f"{env_part} {normalized}"

        return normalized
