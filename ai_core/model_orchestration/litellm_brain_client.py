from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from typing import Any

from ai_core.model_orchestration.brain_model_router import BrainModelRoute, BrainModelRouter
from ai_core.config.paths import CONFIGS_DIR


@dataclass
class LiteLLMBrainResult:
    status: str
    content: str = ""
    route: dict[str, Any] = field(default_factory=dict)
    raw: Any = None
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class LiteLLMBrainClient:
    """LiteLLM client facade used by all separated brains.

    Each brain requests a model by role/task/complexity.  The router selects the
    model from policy; callers never hard-code concrete model names.  Both async
    and sync methods are provided because verification often runs in normal
    synchronous post-execution hooks.
    """

    def __init__(self, *, router: BrainModelRouter | None = None) -> None:
        self.router = router or BrainModelRouter()

    async def complete(
        self,
        *,
        brain: str,
        task_type: str = "default",
        complexity: str = "default",
        messages: list[dict[str, str]],
        context: dict[str, Any] | None = None,
        response_format: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> LiteLLMBrainResult:
        route = self.router.select(brain=brain, task_type=task_type, complexity=complexity, context=context or {})
        return await self.complete_with_route(route=route, messages=messages, response_format=response_format, **kwargs)

    def complete_sync(
        self,
        *,
        brain: str,
        task_type: str = "default",
        complexity: str = "default",
        messages: list[dict[str, str]],
        context: dict[str, Any] | None = None,
        response_format: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> LiteLLMBrainResult:
        route = self.router.select(brain=brain, task_type=task_type, complexity=complexity, context=context or {})
        return self.complete_with_route_sync(route=route, messages=messages, response_format=response_format, **kwargs)

    async def complete_with_route(
        self,
        *,
        route: BrainModelRoute,
        messages: list[dict[str, str]],
        response_format: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> LiteLLMBrainResult:
        try:
            from litellm import acompletion
        except Exception as exc:  # pragma: no cover - environment dependent
            return LiteLLMBrainResult(status="litellm_unavailable", route=route.to_dict(), error=str(exc))

        errors: list[dict[str, Any]] = []
        for attempt_route in self._route_attempts(route):
            prepared_route = self._prepare_attempt_route(attempt_route)
            missing_secret = self._missing_provider_secret(prepared_route)
            if missing_secret:
                errors.append({
                    "provider": prepared_route.provider,
                    "model": prepared_route.model,
                    "status": "missing_required_secret",
                    "secret_key": missing_secret,
                    "error": f"Missing required provider secret: {missing_secret}",
                })
                continue
            model = self._litellm_model(prepared_route)
            options = self._merge_options(route=prepared_route, response_format=response_format, kwargs=kwargs)
            try:
                raw = await acompletion(model=model, messages=messages, **options)
                route_payload = prepared_route.to_dict()
                if errors:
                    route_payload["previous_attempts"] = errors
                return LiteLLMBrainResult(status="completed", content=self._extract_content(raw), route=route_payload, raw=raw)
            except Exception as exc:
                errors.append({"provider": prepared_route.provider, "model": prepared_route.model, "error": str(exc)[:1000]})
        status = "missing_required_secret" if self._only_or_final_actionable_secret_error(errors) else "failed"
        return LiteLLMBrainResult(status=status, route={**route.to_dict(), **self._interaction_payload_from_errors(errors)}, error=json_dumps_compact(errors))

    def complete_with_route_sync(
        self,
        *,
        route: BrainModelRoute,
        messages: list[dict[str, str]],
        response_format: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> LiteLLMBrainResult:
        try:
            from litellm import completion
        except Exception as exc:  # pragma: no cover - environment dependent
            return LiteLLMBrainResult(status="litellm_unavailable", route=route.to_dict(), error=str(exc))

        errors: list[dict[str, Any]] = []
        for attempt_route in self._route_attempts(route):
            prepared_route = self._prepare_attempt_route(attempt_route)
            missing_secret = self._missing_provider_secret(prepared_route)
            if missing_secret:
                errors.append({
                    "provider": prepared_route.provider,
                    "model": prepared_route.model,
                    "status": "missing_required_secret",
                    "secret_key": missing_secret,
                    "error": f"Missing required provider secret: {missing_secret}",
                })
                continue
            model = self._litellm_model(prepared_route)
            options = self._merge_options(route=prepared_route, response_format=response_format, kwargs=kwargs)
            try:
                raw = completion(model=model, messages=messages, **options)
                route_payload = prepared_route.to_dict()
                if errors:
                    route_payload["previous_attempts"] = errors
                return LiteLLMBrainResult(status="completed", content=self._extract_content(raw), route=route_payload, raw=raw)
            except Exception as exc:
                errors.append({"provider": prepared_route.provider, "model": prepared_route.model, "error": str(exc)[:1000]})
        status = "missing_required_secret" if self._only_or_final_actionable_secret_error(errors) else "failed"
        return LiteLLMBrainResult(status=status, route={**route.to_dict(), **self._interaction_payload_from_errors(errors)}, error=json_dumps_compact(errors))

    def _merge_options(self, *, route: BrainModelRoute, response_format: dict[str, Any] | None, kwargs: dict[str, Any]) -> dict[str, Any]:
        options = dict(route.options or {})
        options.update(kwargs)
        if response_format:
            options["response_format"] = response_format
        return self._sanitize_provider_options(route=route, options=options)

    def _sanitize_provider_options(self, *, route: BrainModelRoute, options: dict[str, Any]) -> dict[str, Any]:
        """Apply provider-protocol compatibility without changing capability logic.

        The policy layer may request deterministic generation using parameters
        that are not accepted by every hosted model family.  This adapter keeps
        those details outside capability generation: unsupported options are
        either normalized or left for LiteLLM's drop_params safety valve.
        """
        cleaned = dict(options or {})
        cleaned.setdefault("drop_params", True)
        provider = str(route.provider or "").lower()
        model = str(route.model or "").lower()
        if provider == "openai" and (model.startswith("gpt-5") or "/gpt-5" in model):
            if "temperature" in cleaned and cleaned.get("temperature") != 1:
                cleaned["temperature"] = 1
        return cleaned

    def _prepare_attempt_route(self, route: BrainModelRoute) -> BrainModelRoute:
        provider = str(route.provider or "").strip().lower()
        if provider != "ollama":
            return route
        resolved = self._ensure_ollama_model(route.model)
        if not resolved or resolved == route.model:
            return route
        payload = route.to_dict()
        payload["model"] = resolved
        payload["source"] = str(payload.get("source") or "brain_model_policy") + ":model_prepared"
        payload["decision_reason"] = str(payload.get("decision_reason") or "") + ";ollama_model_resolved"
        return BrainModelRoute(**payload)

    def _ensure_ollama_model(self, model: str) -> str:
        requested = str(model or "").strip()
        if not requested:
            return requested
        if os.environ.get("AI_CORE_DISABLE_OLLAMA_MODEL_PREPARE", "").lower() in {"1", "true", "yes"}:
            return requested
        binary = self._ollama_binary()
        tags = self._ollama_list(binary)
        if self._ollama_model_exists(tags, requested):
            return requested
        for candidate in self._ollama_candidate_models(requested):
            tags = self._ollama_list(binary)
            if self._ollama_model_exists(tags, candidate):
                return candidate
            if self._ollama_pull(binary, candidate):
                tags = self._ollama_list(binary)
                if self._ollama_model_exists(tags, candidate):
                    return candidate
        installed = self._select_installed_ollama_model(tags, requested)
        return installed or requested

    def _ollama_binary(self) -> str:
        explicit = os.environ.get("AI_CORE_OLLAMA_BINARY")
        if explicit and Path(explicit).exists():
            return explicit
        return shutil.which("ollama") or ""

    def _ollama_list(self, binary: str) -> list[str]:
        names: list[str] = []
        if binary:
            try:
                proc = subprocess.run([binary, "list"], text=True, capture_output=True, timeout=20)
            except Exception:
                proc = None
            if proc is not None and proc.returncode == 0:
                for line in (proc.stdout or "").splitlines()[1:]:
                    parts = line.split()
                    if parts:
                        names.append(parts[0])
        if names:
            return names
        return self._ollama_list_http()

    def _ollama_list_http(self) -> list[str]:
        try:
            base = self._ollama_base_url().rstrip("/")
            with urllib.request.urlopen(base + "/api/tags", timeout=20) as response:
                payload = json.loads(response.read().decode("utf-8"))
            models = payload.get("models") if isinstance(payload, dict) else []
            return [str(item.get("name") or "").strip() for item in models if isinstance(item, dict) and str(item.get("name") or "").strip()]
        except Exception:
            return []

    def _ollama_base_url(self) -> str:
        host = os.environ.get("OLLAMA_HOST") or os.environ.get("AI_CORE_OLLAMA_BASE_URL") or "http://127.0.0.1:11434"
        host = str(host).strip()
        if host.startswith(":"):
            host = "http://127.0.0.1" + host
        if not host.startswith(("http://", "https://")):
            host = "http://" + host
        return host

    def _ollama_model_exists(self, names: list[str], model: str) -> bool:
        wanted = str(model or "").strip()
        if not wanted:
            return False
        return wanted in set(names or [])

    def _ollama_candidate_models(self, requested: str) -> list[str]:
        candidates: list[str] = []
        env_candidates = os.environ.get("AI_CORE_OLLAMA_MODEL_CANDIDATES", "")
        candidates.extend([item.strip() for item in env_candidates.split(",") if item.strip()])
        config = self._load_model_resolution_config()
        aliases = config.get("aliases") if isinstance(config.get("aliases"), dict) else {}
        for item in aliases.get(requested, []) if isinstance(aliases.get(requested), list) else []:
            if str(item).strip():
                candidates.append(str(item).strip())
        fallbacks = config.get("fallback_models") if isinstance(config.get("fallback_models"), list) else []
        candidates.extend(str(item).strip() for item in fallbacks if str(item).strip())
        candidates.insert(0, requested)
        out: list[str] = []
        seen: set[str] = set()
        for item in candidates:
            if item and item not in seen:
                seen.add(item)
                out.append(item)
        return out

    def _load_model_resolution_config(self) -> dict[str, Any]:
        paths = [
            CONFIGS_DIR / "model_resolution.yaml",
            CONFIGS_DIR / "brain_model_policy.yaml",
        ]
        for path in paths:
            if not path.exists():
                continue
            try:
                import yaml
                data = yaml.safe_load(path.read_text(encoding="utf-8"))
            except Exception:
                data = None
            if isinstance(data, dict):
                section = data.get("model_resolution") if isinstance(data.get("model_resolution"), dict) else data
                if isinstance(section, dict):
                    return section
        return {}

    def _ollama_pull(self, binary: str, model: str) -> bool:
        if os.environ.get("AI_CORE_DISABLE_OLLAMA_MODEL_PULL", "").lower() in {"1", "true", "yes"}:
            return False
        timeout = int(os.environ.get("AI_CORE_OLLAMA_PULL_TIMEOUT_SECONDS", "3600") or "3600")
        if binary:
            try:
                proc = subprocess.run([binary, "pull", model], text=True, capture_output=True, timeout=timeout)
                if proc.returncode == 0:
                    return True
            except Exception:
                pass
        return self._ollama_pull_http(model=model, timeout=timeout)

    def _ollama_pull_http(self, *, model: str, timeout: int) -> bool:
        try:
            base = self._ollama_base_url().rstrip("/")
            body = json.dumps({"name": model, "stream": False}).encode("utf-8")
            request = urllib.request.Request(base + "/api/pull", data=body, headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(request, timeout=timeout) as response:
                response.read()
            return self._ollama_model_exists(self._ollama_list_http(), model)
        except Exception:
            return False

    def _select_installed_ollama_model(self, names: list[str], requested: str) -> str:
        if not names:
            return ""
        requested_root = requested.split(":", 1)[0]
        for name in names:
            if name.split(":", 1)[0] == requested_root:
                return name
        return names[0]

    def _missing_provider_secret(self, route: BrainModelRoute) -> str:
        provider = str(route.provider or "").strip().lower()
        required = self._provider_secret_env(provider)
        if required and not os.environ.get(required):
            return required
        return ""

    def _provider_secret_env(self, provider: str) -> str:
        provider = str(provider or "").strip().lower()
        if not provider:
            return ""
        cfg = self._load_provider_config(provider)
        for key in ("auth_env", "api_key_env", "secret_env"):
            value = str(cfg.get(key) or "").strip() if isinstance(cfg, dict) else ""
            if value:
                return value
        auth_type = str(cfg.get("auth_type") or "").strip().lower() if isinstance(cfg, dict) else ""
        if provider == "openai" or (provider.startswith("openai") and auth_type != "none"):
            return "OPENAI_API_KEY"
        if provider in {"claude", "anthropic"}:
            return "ANTHROPIC_API_KEY"
        return ""

    def _load_provider_config(self, provider: str) -> dict[str, Any]:
        path = CONFIGS_DIR / "models" / "providers.yaml"
        if not path.exists():
            return {}
        try:
            import yaml
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        providers = data.get("providers") if isinstance(data, dict) and isinstance(data.get("providers"), dict) else {}
        cfg = providers.get(provider) if isinstance(providers.get(provider), dict) else {}
        return cfg if isinstance(cfg, dict) else {}

    def _only_or_final_actionable_secret_error(self, errors: list[dict[str, Any]]) -> bool:
        if not errors:
            return False
        return any(str(item.get("status") or "") == "missing_required_secret" for item in errors)

    def _interaction_payload_from_errors(self, errors: list[dict[str, Any]]) -> dict[str, Any]:
        secret_names: list[str] = []
        for item in errors or []:
            if str(item.get("status") or "") == "missing_required_secret":
                name = str(item.get("secret_key") or "").strip()
                if name and name not in secret_names:
                    secret_names.append(name)
        if not secret_names:
            return {"previous_attempts": errors}
        fields = [{
            "kind": "provider_secret",
            "scope": "environment",
            "parameter_name": name,
            "name": name,
            "input_type": "password",
            "required": True,
            "secret": True,
        } for name in secret_names]
        return {
            "previous_attempts": errors,
            "interaction_request": {
                "type": "provider_secret_configuration",
                "kind": "provider_secret_configuration",
                "message": "Provide missing provider secret values, or switch to an available local model.",
                "fields": fields,
            },
        }

    def _extract_content(self, raw: Any) -> str:
        content = ""
        choices = getattr(raw, "choices", None) or []
        if choices:
            message = getattr(choices[0], "message", None)
            content = getattr(message, "content", "") if message is not None else ""
            if isinstance(message, dict):
                content = str(message.get("content") or content)
        if not content and isinstance(raw, dict):
            try:
                content = str(raw["choices"][0]["message"].get("content") or "")
            except Exception:
                content = ""
        return content

    def _litellm_model(self, route: BrainModelRoute) -> str:
        provider = str(route.provider or "").strip()
        model = str(route.model or "").strip()
        if not provider:
            return model
        if model.startswith(provider + "/"):
            return model
        return f"{provider}/{model}" if model else provider

    def _route_attempts(self, route: BrainModelRoute) -> list[BrainModelRoute]:
        attempts = [route]
        for item in route.fallback or []:
            if isinstance(item, dict):
                attempts.append(self._fallback_route(base=route, item=item))
        return attempts

    def _fallback_route(self, *, base: BrainModelRoute, item: dict[str, Any]) -> BrainModelRoute:
        return BrainModelRoute(
            brain=base.brain,
            task_type=base.task_type,
            complexity=base.complexity,
            provider=str(item.get("provider") or base.provider),
            model=str(item.get("model") or base.model),
            model_alias=str(item.get("model_alias") or item.get("alias") or base.model_alias),
            source=f"{base.source}:fallback",
            options=item.get("options") if isinstance(item.get("options"), dict) else dict(base.options or {}),
            fallback=[],
            decision_reason=str(item.get("reason") or "fallback_route"),
        )


def json_dumps_compact(value: Any) -> str:
    try:
        import json

        return json.dumps(value, ensure_ascii=False, default=str)[:2000]
    except Exception:
        return str(value)[:2000]
