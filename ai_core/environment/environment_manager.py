from __future__ import annotations
from typing import AsyncGenerator, Any
import os

from ai_core.config.paths import RUNTIME_CONFIGS_DIR
from ai_core.config.loader import ConfigLoader
from ai_core.environment.os_detect import os_key
from ai_core.environment.provider_checker import ProviderChecker
from ai_core.environment.command_runner import CommandRunner
from ai_core.security.approval_service import ApprovalService
from ai_core.utils.events import StreamEvent


class EnvironmentManager:
    """Generic provider/model environment manager.

    ai_core knows only generic concepts:
    - provider
    - binary
    - health URL
    - install command
    - model install command

    It does not know any business workflow.
    """

    def __init__(self, approval: ApprovalService):
        self.loader = ConfigLoader()
        self.checker = ProviderChecker()
        self.runner = CommandRunner()
        self.approval = approval

    def _config(self) -> dict:
        return self.loader.read(RUNTIME_CONFIGS_DIR / "environment" / "providers.yaml", default={}) or {}

    async def ensure_provider(self, provider_name: str) -> AsyncGenerator[StreamEvent, None]:
        cfg = self._config()
        defaults = cfg.get("defaults", {})
        provider = cfg.get("providers", {}).get(provider_name)
        if not provider or not provider.get("enabled", True):
            yield StreamEvent("error", "Provider unavailable", f"Provider '{provider_name}' is not configured or disabled.", {"provider": provider_name})
            return

        if provider.get("requires_key"):
            keys = provider.get("env_keys", [])
            missing = [k for k in keys if not os.getenv(k)]
            if missing:
                yield StreamEvent("provider_key_required", "API key required", f"Missing environment variable(s): {', '.join(missing)}", {"provider": provider_name, "missing": missing})
                return

        binary_result = await self.checker.check_binary(provider.get("binary"))
        yield StreamEvent("provider_check", "Checking provider binary", provider_name, binary_result)

        if not binary_result.get("available"):
            async for ev in self._install_provider(provider_name, provider, defaults):
                yield ev

        health_result = await self.checker.check_http(provider.get("health_url"))
        yield StreamEvent("provider_check", "Checking provider health", provider_name, health_result)

        if not health_result.get("available") and defaults.get("auto_start_enabled", True):
            async for ev in self._start_provider(provider_name, provider, defaults):
                yield ev
            health_result = await self.checker.check_http(provider.get("health_url"))
            yield StreamEvent("provider_check", "Rechecking provider health", provider_name, health_result)

        if not health_result.get("available"):
            yield StreamEvent("error", "Provider health check failed", provider_name, health_result)
            return

        if provider_name == "ollama":
            for model in provider.get("models", []):
                model_result = await self.checker.check_ollama_model(provider.get("base_url"), model)
                yield StreamEvent("model_check", "Checking model", model, model_result)
                if not model_result.get("available"):
                    async for ev in self._install_model(provider_name, provider, model, defaults):
                        yield ev

        yield StreamEvent("provider_ready", "Provider ready", provider_name, {"provider": provider_name})

    async def _install_provider(self, provider_name: str, provider: dict, defaults: dict) -> AsyncGenerator[StreamEvent, None]:
        commands = provider.get("install", {}).get(os_key(), [])
        if not commands:
            yield StreamEvent("error", "No install command", f"No install command for {provider_name} on this OS.")
            return
        if not defaults.get("auto_install_enabled", True):
            yield StreamEvent("error", "Auto install disabled", provider_name)
            return
        payload = {"provider": provider_name, "commands": commands}
        if defaults.get("approval_required_for_install", True) and not self.approval.is_approved("install_provider", payload):
            req = self.approval.create(
                "install_provider",
                f"Install provider '{provider_name}'? Commands: {commands}",
                payload,
            )
            yield StreamEvent("human_review", "Approval required", req.message, {"approval_id": req.approval_id, "action": req.action})
            return
        for command in commands:
            yield StreamEvent("command", "Installing provider", command)
            result = self.runner.run(command, timeout=defaults.get("command_timeout_seconds", 1800))
            yield StreamEvent("command_result", "Install command result", command, result.__dict__)

    async def _start_provider(self, provider_name: str, provider: dict, defaults: dict) -> AsyncGenerator[StreamEvent, None]:
        commands = provider.get("start", {}).get(os_key(), [])
        for command in commands:
            yield StreamEvent("command", "Starting provider", command)
            result = self.runner.run(command, timeout=15)
            yield StreamEvent("command_result", "Start command result", command, result.__dict__)

    async def _install_model(self, provider_name: str, provider: dict, model: str, defaults: dict) -> AsyncGenerator[StreamEvent, None]:
        commands = [cmd.format(model=model) for cmd in provider.get("model_install", [])]
        if not commands:
            yield StreamEvent("error", "No model install command", model)
            return
        payload = {"provider": provider_name, "model": model, "commands": commands}
        if defaults.get("approval_required_for_install", True) and not self.approval.is_approved("install_model", payload):
            req = self.approval.create(
                "install_model",
                f"Install model '{model}' for provider '{provider_name}'? Commands: {commands}",
                payload,
            )
            yield StreamEvent("human_review", "Approval required", req.message, {"approval_id": req.approval_id, "action": req.action})
            return
        for command in commands:
            yield StreamEvent("command", "Installing model", command)
            result = self.runner.run(command, timeout=defaults.get("command_timeout_seconds", 1800))
            yield StreamEvent("command_result", "Model install command result", command, result.__dict__)
