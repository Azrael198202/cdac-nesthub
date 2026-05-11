import os
import platform
import shutil
from typing import Dict, Any, Tuple, List
import httpx
from ai_core.config.paths import RUNTIME_CONFIGS
from ai_core.config.loader import ConfigLoader
from ai_core.events.event_bus import event_bus
from ai_core.environment.command_runner import CommandRunner


class ProviderManager:
    def __init__(self) -> None:
        self.loader = ConfigLoader()
        self.config_path = RUNTIME_CONFIGS / "environment" / "providers.yaml"
        self.routes_path = RUNTIME_CONFIGS / "models" / "model_routes.yaml"
        self.runner = CommandRunner()

    def load_provider_config(self) -> Dict[str, Any]:
        return self.loader.load_yaml(self.config_path)

    def load_routes(self) -> Dict[str, Any]:
        return self.loader.load_yaml(self.routes_path)

    def route_for_task(self, task_type: str) -> List[str]:
        routes = self.load_routes()
        return routes.get("task_routes", {}).get(task_type, routes.get("default_route", []))

    async def ensure_any_provider_ready(self, run_id: str, task_type: str) -> Tuple[bool, Dict[str, Any]]:
        for provider_name in self.route_for_task(task_type):
            ok, result = await self.ensure_provider_ready(run_id, provider_name)
            if ok:
                return True, result
            if result.get("approval_required"):
                return False, result
            await event_bus.emit(run_id, {
                "type": "PROVIDER_SKIPPED",
                "title": "Provider skipped",
                "message": result.get("message", provider_name),
                "provider": provider_name
            })
        return False, {
            "reason": "no_provider_available",
            "message": "No provider is available. Configure a local model or external API key.",
            "approval_required": False
        }

    async def ensure_provider_ready(self, run_id: str, provider_name: str) -> Tuple[bool, Dict[str, Any]]:
        providers = self.load_provider_config().get("providers", {})
        cfg = providers.get(provider_name, {})
        if not cfg or not cfg.get("enabled", False):
            return False, {"reason": "provider_disabled", "provider": provider_name, "message": f"{provider_name} disabled"}

        await event_bus.emit(run_id, {
            "type": "MODEL_ROUTE",
            "title": "Trying provider",
            "message": provider_name,
            "provider": provider_name
        })

        if cfg.get("requires_key"):
            key_name = cfg.get("env_key", "")
            if not os.getenv(key_name):
                return False, {
                    "reason": "missing_api_key",
                    "provider": provider_name,
                    "message": f"Missing environment variable: {key_name}",
                    "approval_required": False
                }
            return True, {"provider": provider_name, "model": cfg.get("default_model"), "ready": True}

        if cfg.get("type") == "model_hub":
            return False, {
                "reason": "hub_not_implemented",
                "provider": provider_name,
                "message": "HuggingFace route exists, but runtime-generated model selection is not configured yet.",
                "approval_required": False
            }

        binary = cfg.get("binary")
        await event_bus.emit(run_id, {
            "type": "PROVIDER_CHECK",
            "title": "Checking provider binary",
            "message": str(binary),
            "provider": provider_name
        })

        if binary and not shutil.which(binary):
            system = platform.system().lower()
            commands = cfg.get("install", {}).get(system, [])
            return False, {
                "reason": "provider_not_installed",
                "provider": provider_name,
                "commands": commands,
                "approval_required": cfg.get("requires_approval", True),
                "message": f"Install provider '{provider_name}'?"
            }

        health_url = cfg.get("health_url")
        if health_url:
            try:
                async with httpx.AsyncClient(timeout=2.5) as client:
                    r = await client.get(health_url)
                    if r.status_code < 400:
                        return True, {"provider": provider_name, "model": cfg.get("default_model"), "ready": True}
            except Exception:
                system = platform.system().lower()
                commands = cfg.get("start", {}).get(system, [])
                return False, {
                    "reason": "provider_not_running",
                    "provider": provider_name,
                    "commands": commands,
                    "approval_required": cfg.get("requires_approval", True),
                    "message": f"Start provider '{provider_name}'?"
                }

        return True, {"provider": provider_name, "model": cfg.get("default_model"), "ready": True}

    async def run_provider_fix(self, run_id: str, provider_name: str, commands: list[str]) -> bool:
        if not commands:
            await event_bus.emit(run_id, {
                "type": "PROVIDER_FIX_FAILED",
                "title": "Provider fix failed",
                "message": f"No commands configured for {provider_name}."
            })
            return False

        code = await self.runner.run_streaming(
            run_id=run_id,
            title=f"Fix provider {provider_name}",
            commands=commands
        )
        if code == 0:
            await event_bus.emit(run_id, {
                "type": "PROVIDER_FIX_DONE",
                "title": "Provider fix completed",
                "message": provider_name,
                "progress": 100
            })
            return True

        await event_bus.emit(run_id, {
            "type": "PROVIDER_FIX_FAILED",
            "title": "Provider fix failed",
            "message": provider_name
        })
        return False
