import os
import platform
import shutil
import yaml
import httpx
from typing import Dict, Any, Tuple
from ai_core.config.paths import RUNTIME_CONFIGS
from ai_core.events.event_bus import event_bus
from ai_core.environment.command_runner import CommandRunner


class ProviderManager:
    def __init__(self) -> None:
        self.config_path = RUNTIME_CONFIGS / "environment" / "providers.yaml"
        self.runner = CommandRunner()

    def load_config(self) -> Dict[str, Any]:
        return yaml.safe_load(self.config_path.read_text(encoding="utf-8"))

    async def ensure_provider_ready(self, run_id: str, provider_name: str) -> Tuple[bool, Dict[str, Any]]:
        cfg = self.load_config()["providers"][provider_name]
        await event_bus.emit(run_id, {
            "type": "MODEL_ROUTE",
            "title": "Trying provider",
            "message": provider_name,
            "provider": provider_name,
        })

        if cfg.get("requires_key"):
            key = os.getenv(cfg.get("env_key", ""))
            if not key:
                return False, {
                    "reason": "missing_api_key",
                    "provider": provider_name,
                    "message": f"Missing environment variable: {cfg.get('env_key')}",
                    "approval_required": False,
                }
            return True, {"provider": provider_name, "ready": True}

        binary = cfg.get("binary")
        await event_bus.emit(run_id, {
            "type": "PROVIDER_CHECK",
            "title": "Checking provider binary",
            "message": binary,
        })

        if binary and not shutil.which(binary):
            system = platform.system().lower()
            commands = cfg.get("install", {}).get(system, [])
            return False, {
                "reason": "provider_not_installed",
                "provider": provider_name,
                "commands": commands,
                "approval_required": cfg.get("requires_approval", True),
                "message": f"Install provider '{provider_name}'?",
            }

        health_url = cfg.get("health_url")
        if health_url:
            try:
                async with httpx.AsyncClient(timeout=2.5) as client:
                    r = await client.get(health_url)
                    if r.status_code < 400:
                        return True, {"provider": provider_name, "ready": True}
            except Exception as exc:
                system = platform.system().lower()
                commands = cfg.get("start", {}).get(system, [])
                return False, {
                    "reason": "provider_not_running",
                    "provider": provider_name,
                    "commands": commands,
                    "approval_required": cfg.get("requires_approval", True),
                    "message": f"Start provider '{provider_name}'?",
                }

        return True, {"provider": provider_name, "ready": True}

    async def run_provider_fix(self, run_id: str, provider_name: str, commands: list[str]) -> bool:
        code = await self.runner.run_streaming(
            run_id=run_id,
            title=f"Fix provider {provider_name}",
            commands=commands,
        )
        if code == 0:
            await event_bus.emit(run_id, {
                "type": "PROVIDER_FIX_DONE",
                "title": "Provider fix completed",
                "message": provider_name,
            })
            return True

        await event_bus.emit(run_id, {
            "type": "PROVIDER_FIX_FAILED",
            "title": "Provider fix failed",
            "message": provider_name,
        })
        return False
