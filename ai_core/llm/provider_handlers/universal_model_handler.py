from __future__ import annotations

import time
from typing import Any

import httpx

from ai_core.context.token_estimator import TokenEstimator
from ai_core.events.event_bus import event_bus
from ai_core.llm.model_response_cache import ModelResponseCache
from ai_core.llm.provider_handlers.base import ProviderUnavailableError
from ai_core.llm.provider_handlers.utils import build_system_prompt, parse_json_content
from ai_core.llm.token_usage_logger import TokenUsageLogger
from ai_core.secrets.secret_store import SecretStore


class UniversalModelProviderHandler:
    """Protocol-driven model provider handler.

    ai_core does not contain one adapter per vendor/model. Runtime config declares
    provider protocol, endpoint, auth, timeout, cache, and token budget. This
    handler executes that contract generically.
    """

    provider_type = "universal_model"

    LEGACY_TYPE_PROTOCOLS = {
        "openai": "openai_compatible",
        "openai_compatible": "openai_compatible",
        "ollama": "ollama_chat",
    }

    def __init__(self) -> None:
        self.secret_store = SecretStore()
        self.cache = ModelResponseCache()
        self.token_logger = TokenUsageLogger()
        self.estimator = TokenEstimator()

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
        protocol = provider.get("protocol") or self.LEGACY_TYPE_PROTOCOLS.get(provider.get("type"), provider.get("type"))
        if protocol in {"openai_compatible", "chat_completions"}:
            return await self._call_chat_completions(
                run_id, node_id, provider_name, provider, prompt, rendered_user_prompt, schema
            )
        if protocol in {"ollama_chat", "ollama_generate"}:
            return await self._call_ollama(
                run_id, node_id, provider_name, provider, prompt, rendered_user_prompt, schema, protocol
            )
        raise ProviderUnavailableError(
            f"Unsupported model protocol: {protocol}. Add a runtime-generated adapter or configure protocol."
        )


    def _fit_payload_to_budget(self, provider: dict[str, Any], payload: dict[str, Any], *, user_message_index: int | None = None) -> tuple[dict[str, Any], int, bool]:
        budget = int(provider.get("max_request_tokens") or provider.get("max_prompt_tokens") or provider.get("prompt_budget_tokens") or 12000)
        safety = int(provider.get("prompt_budget_safety_tokens") or 800)
        effective_budget = max(1000, budget - safety)
        estimated = self.estimator.estimate_obj(payload)
        if estimated <= effective_budget or user_message_index is None:
            return payload, estimated, False
        messages = payload.get("messages") if isinstance(payload.get("messages"), list) else []
        if user_message_index >= len(messages) or not isinstance(messages[user_message_index], dict):
            return payload, estimated, False
        content = str(messages[user_message_index].get("content") or "")
        # Estimate non-user-message overhead and shrink the user payload to the remaining budget.
        clone = dict(payload)
        clone_messages = [dict(m) if isinstance(m, dict) else m for m in messages]
        clone_messages[user_message_index] = {**clone_messages[user_message_index], "content": ""}
        clone["messages"] = clone_messages
        overhead = self.estimator.estimate_obj(clone)
        available = max(1000, effective_budget - overhead)
        max_chars = max(1000, int(available * self.estimator.CHARS_PER_TOKEN))
        messages[user_message_index]["content"] = content[:max_chars] + "\n...[truncated by total payload budget]"
        payload["messages"] = messages
        return payload, self.estimator.estimate_obj(payload), True

    async def _call_chat_completions(self, run_id, node_id, provider_name, provider, prompt, rendered_user_prompt, schema):
        base_url = (provider.get("base_url") or "").rstrip("/")
        endpoint = provider.get("endpoint", "/v1/chat/completions")
        url = provider.get("url") or (base_url + endpoint)
        if not url:
            raise ProviderUnavailableError(f"{provider_name}: url or base_url is required for chat completions protocol")

        model = provider.get("model")
        timeout = float(provider.get("timeout_seconds", 60))
        temperature = float(provider.get("temperature", 0.2))
        system_prompt = build_system_prompt(prompt, schema, max_schema_chars=int(provider.get("max_schema_chars", 12000)))
        payload: dict[str, Any] = {
            "model": model,
            "temperature": temperature,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": rendered_user_prompt},
            ],
        }
        if provider.get("response_format_json", True):
            payload["response_format"] = {"type": "json_object"}

        headers = {"Content-Type": "application/json"}
        self._apply_auth(headers, provider)

        payload, prompt_tokens_est, total_budget_truncated = self._fit_payload_to_budget(provider, payload, user_message_index=1)
        if total_budget_truncated:
            await event_bus.emit(run_id, {
                "type": "LLM_TOTAL_PROMPT_BUDGET_APPLIED",
                "title": "Total prompt budget applied",
                "message": f"Reduced complete provider payload to estimated_prompt_tokens={prompt_tokens_est}",
                "node_id": node_id,
                "provider": provider_name,
                "model": model,
                "estimated_prompt_tokens": prompt_tokens_est,
            })
        cache_key = self.cache.build_key(provider_name=provider_name, provider=provider, payload=payload)
        if provider.get("cache_enabled", True):
            cached = self.cache.get(cache_key)
            if cached is not None:
                await event_bus.emit(run_id, {
                    "type": "MODEL_CACHE_HIT",
                    "title": "Model cache hit",
                    "message": f"provider={provider_name}, model={model}",
                    "node_id": node_id,
                    "provider": provider_name,
                    "model": model,
                })
                return parse_json_content(cached.get("content", "{}"))

        await event_bus.emit(run_id, {
            "type": "LLM_REQUEST_SENT",
            "title": "LLM request sent",
            "message": f"{provider_name}: waiting for model response... timeout={timeout}s, estimated_prompt_tokens={prompt_tokens_est}",
            "node_id": node_id,
            "provider": provider_name,
            "model": model,
            "estimated_prompt_tokens": prompt_tokens_est,
            "timeout_seconds": timeout,
        })

        started = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(timeout)) as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
        except httpx.TimeoutException as exc:
            raise ProviderUnavailableError(
                f"Model request timed out. provider={provider_name}, model={model}, timeout_seconds={timeout}"
            ) from exc
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:1000] if exc.response is not None else ""
            raise ProviderUnavailableError(
                f"Model request failed. provider={provider_name}, status={exc.response.status_code}, detail={detail}"
            ) from exc

        elapsed = round(time.monotonic() - started, 3)
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        usage = data.get("usage") or {}
        prompt_tokens = int(usage.get("prompt_tokens") or prompt_tokens_est)
        completion_tokens = int(usage.get("completion_tokens") or self.estimator.estimate_text(content))
        total_tokens = int(usage.get("total_tokens") or (prompt_tokens + completion_tokens))
        self._log_usage(provider_name, provider, node_id, prompt_tokens, completion_tokens, total_tokens, elapsed, cache_hit=False)
        if provider.get("cache_enabled", True):
            self.cache.set(cache_key, {"content": content, "usage": usage, "latency_seconds": elapsed})
        return parse_json_content(content)

    async def _call_ollama(self, run_id, node_id, provider_name, provider, prompt, rendered_user_prompt, schema, protocol):
        base_url = provider.get("base_url", "http://127.0.0.1:11434").rstrip("/")
        model = provider.get("model")
        timeout = float(provider.get("timeout_seconds", 90))
        system_prompt = build_system_prompt(prompt, schema, max_schema_chars=int(provider.get("max_schema_chars", 10000)))
        if protocol == "ollama_generate":
            endpoint = provider.get("generate_endpoint", "/api/generate")
            payload = {
                "model": model,
                "stream": False,
                "format": "json",
                "prompt": system_prompt + "\n\nUser prompt:\n" + rendered_user_prompt,
            }
        else:
            endpoint = provider.get("chat_endpoint", "/api/chat")
            payload = {
                "model": model,
                "stream": False,
                "format": "json",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": rendered_user_prompt},
                ],
            }
        url = base_url + endpoint
        if isinstance(payload.get("messages"), list):
            payload, prompt_tokens_est, total_budget_truncated = self._fit_payload_to_budget(provider, payload, user_message_index=1)
        else:
            prompt_tokens_est = self.estimator.estimate_obj(payload)
            total_budget_truncated = False
        if total_budget_truncated:
            await event_bus.emit(run_id, {
                "type": "LLM_TOTAL_PROMPT_BUDGET_APPLIED",
                "title": "Total prompt budget applied",
                "message": f"Reduced complete provider payload to estimated_prompt_tokens={prompt_tokens_est}",
                "node_id": node_id,
                "provider": provider_name,
                "model": model,
                "estimated_prompt_tokens": prompt_tokens_est,
            })
        cache_key = self.cache.build_key(provider_name=provider_name, provider=provider, payload=payload)
        if provider.get("cache_enabled", True):
            cached = self.cache.get(cache_key)
            if cached is not None:
                await event_bus.emit(run_id, {
                    "type": "MODEL_CACHE_HIT",
                    "title": "Model cache hit",
                    "message": f"provider={provider_name}, model={model}",
                    "node_id": node_id,
                    "provider": provider_name,
                    "model": model,
                })
                return parse_json_content(cached.get("content", "{}"))

        await event_bus.emit(run_id, {
            "type": "LLM_REQUEST_SENT",
            "title": "LLM request sent",
            "message": f"{provider_name}: POST {endpoint}, waiting for model response... timeout={timeout}s, estimated_prompt_tokens={prompt_tokens_est}",
            "node_id": node_id,
            "provider": provider_name,
            "model": model,
            "estimated_prompt_tokens": prompt_tokens_est,
            "timeout_seconds": timeout,
        })
        started = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(timeout)) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                data = response.json()
        except httpx.TimeoutException as exc:
            raise ProviderUnavailableError(
                f"Model request timed out. provider={provider_name}, model={model}, timeout_seconds={timeout}"
            ) from exc
        except httpx.HTTPStatusError as exc:
            if protocol == "ollama_chat" and exc.response.status_code == 404 and provider.get("endpoint_strategy", "auto") == "auto":
                fallback_provider = dict(provider)
                fallback_provider["protocol"] = "ollama_generate"
                return await self._call_ollama(run_id, node_id, provider_name, fallback_provider, prompt, rendered_user_prompt, schema, "ollama_generate")
            raise
        elapsed = round(time.monotonic() - started, 3)
        content = data.get("message", {}).get("content", "") if protocol == "ollama_chat" else data.get("response", "")
        prompt_tokens = prompt_tokens_est
        completion_tokens = self.estimator.estimate_text(content)
        total_tokens = prompt_tokens + completion_tokens
        self._log_usage(provider_name, provider, node_id, prompt_tokens, completion_tokens, total_tokens, elapsed, cache_hit=False)
        if provider.get("cache_enabled", True):
            self.cache.set(cache_key, {"content": content, "latency_seconds": elapsed})
        return parse_json_content(content)

    def _apply_auth(self, headers: dict[str, str], provider: dict[str, Any]) -> None:
        auth_type = provider.get("auth_type") or ("bearer_env" if provider.get("api_key_env") else "none")
        if auth_type == "none":
            return
        key_name = provider.get("auth_env") or provider.get("api_key_env")
        key = self.secret_store.get(key_name) if key_name else ""
        if not key:
            raise ProviderUnavailableError(f"MISSING_SECRET:{key_name}")
        if auth_type == "bearer_env":
            headers["Authorization"] = f"Bearer {key}"
        elif auth_type == "api_key_header":
            header_name = provider.get("auth_header", "X-API-Key")
            headers[header_name] = key
        else:
            raise ProviderUnavailableError(f"Unsupported auth_type: {auth_type}")

    def _log_usage(self, provider_name, provider, node_id, prompt_tokens, completion_tokens, total_tokens, elapsed, cache_hit):
        self.token_logger.log({
            "provider": provider_name,
            "provider_type": provider.get("type"),
            "protocol": provider.get("protocol") or provider.get("type"),
            "model": provider.get("model"),
            "node_id": node_id,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "latency_seconds": elapsed,
            "cache_hit": cache_hit,
        })
