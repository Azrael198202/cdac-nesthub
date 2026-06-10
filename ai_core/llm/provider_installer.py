from auxiliary_brain.environment.binary_resolver import BinaryResolver
from ai_core.events.event_bus import event_bus
from ai_core.llm.provider_command_runner import ProviderCommandRunner
from ai_core.llm.provider_handlers.base import ProviderUnavailableError


class ProviderInstaller:
    def __init__(self) -> None:
        self.resolver = BinaryResolver()
        self.command_runner = ProviderCommandRunner()

    async def ensure_binary(self, run_id: str, provider_name: str, provider: dict) -> str:
        binary_name = provider.get("binary")
        if not binary_name:
            return ""

        hints = provider.get("executable_hints", {})
        resolved = self.resolver.resolve(binary_name, hints)
        if resolved:
            quoted = self.resolver.quote(resolved)
            await event_bus.emit(run_id, {
                "type": "PROVIDER_BINARY_READY",
                "title": "Provider binary ready",
                "message": f"{binary_name} -> {quoted}",
                "provider": provider_name,
            })
            return quoted

        await event_bus.emit(run_id, {
            "type": "PROVIDER_BINARY_MISSING",
            "title": "Provider binary missing",
            "message": binary_name,
            "provider": provider_name,
        })

        if not provider.get("auto_install", False):
            raise ProviderUnavailableError(f"Provider binary not found: {binary_name}")

        system = self.resolver.system_key()
        commands = provider.get("install", {}).get(system, [])
        if not commands:
            raise ProviderUnavailableError(f"No install command for provider={provider_name}, system={system}")

        for command in commands:
            await event_bus.emit(run_id, {
                "type": "PROVIDER_INSTALL_STARTED",
                "title": "Installing provider",
                "message": command,
                "provider": provider_name,
            })
            result = await self.command_runner.run(
                run_id=run_id,
                title=f"Install provider binary: {binary_name}",
                command=command,
                timeout_seconds=provider.get("install_timeout_seconds", 3600),
            )
            if result.returncode != 0:
                await event_bus.emit(run_id, {
                    "type": "PROVIDER_INSTALL_FAILED",
                    "title": "Provider install failed",
                    "message": result.summary(),
                    "provider": provider_name,
                })
                raise ProviderUnavailableError(f"Install failed for {binary_name}\n{result.summary()}")

        resolved = self.resolver.resolve(binary_name, hints)
        if not resolved:
            raise ProviderUnavailableError(f"Installed but executable still not found: {binary_name}")

        quoted = self.resolver.quote(resolved)
        await event_bus.emit(run_id, {
            "type": "PROVIDER_INSTALL_DONE",
            "title": "Provider installed",
            "message": f"{binary_name} -> {quoted}",
            "provider": provider_name,
        })
        return quoted
