from __future__ import annotations

import importlib.util
import json
import os
import subprocess
from pathlib import Path
from typing import Any

import httpx
from jsonschema import Draft202012Validator


class RuntimeProviderInvoker:
    """Invoke a registered provider artifact with schema-checked input/output."""

    def invoke(self, provider: dict[str, Any], input_data: dict[str, Any]) -> dict[str, Any]:
        input_error = self._validate(provider.get("input_schema"), input_data)
        if input_error:
            return self._error("provider_input_schema_validation_failed", input_error, provider)
        method = str((provider.get("invoke") or {}).get("method") or "").strip()
        try:
            if method in {"ollama_chat", "ollama_generate"}:
                output = self._invoke_ollama(provider, input_data, method)
            elif method == "chat_completions":
                output = self._invoke_chat_completions(provider, input_data)
            elif method == "http_json":
                output = self._invoke_http_json(provider, input_data)
            elif method == "command":
                output = self._invoke_command(provider, input_data)
            elif method == "python_function":
                output = self._invoke_python_function(provider, input_data)
            else:
                return self._error("unsupported_provider_invoke_method", method or "missing", provider)
        except Exception as exc:
            return self._error("provider_invocation_failed", str(exc), provider)
        output = self._normalize(output, provider)
        output_error = self._validate(provider.get("output_schema"), output)
        if output_error:
            return self._error("provider_output_schema_validation_failed", output_error, provider, data=output)
        return output

    def _invoke_ollama(self, provider: dict[str, Any], input_data: dict[str, Any], method: str) -> dict[str, Any]:
        invoke = provider.get("invoke") or {}
        base = str(invoke.get("base_url") or provider.get("base_url") or "http://127.0.0.1:11434").rstrip("/")
        model = str(input_data.get("model") or invoke.get("model") or provider.get("model") or "")
        timeout = float(invoke.get("timeout_seconds") or provider.get("timeout_seconds") or 120)
        prompt = str(input_data.get("prompt") or "")
        system = str(input_data.get("system") or "")
        if method == "ollama_chat":
            path = str(invoke.get("path") or "/api/chat")
            payload = {"model": model, "stream": False, "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]}
            if input_data.get("schema"):
                payload["format"] = "json"
            with httpx.Client(timeout=timeout) as client:
                res = client.post(base + path, json=payload)
                res.raise_for_status()
                data = res.json()
            content = ((data.get("message") or {}).get("content") or "")
        else:
            path = str(invoke.get("path") or "/api/generate")
            payload = {"model": model, "stream": False, "prompt": (system + "\n\n" + prompt).strip()}
            if input_data.get("schema"):
                payload["format"] = "json"
            with httpx.Client(timeout=timeout) as client:
                res = client.post(base + path, json=payload)
                res.raise_for_status()
                data = res.json()
            content = data.get("response") or ""
        parsed = self._try_json(content)
        return {"status": "success", "data": parsed if isinstance(parsed, dict) else {"content": content}, "source": provider.get("provider_id", "runtime_provider")}

    def _invoke_chat_completions(self, provider: dict[str, Any], input_data: dict[str, Any]) -> dict[str, Any]:
        invoke = provider.get("invoke") or {}
        base = str(invoke.get("base_url") or provider.get("base_url") or "").rstrip("/")
        path = str(invoke.get("path") or "/v1/chat/completions")
        url = str(invoke.get("url") or (base + path))
        model = str(input_data.get("model") or invoke.get("model") or provider.get("model") or "")
        timeout = float(invoke.get("timeout_seconds") or provider.get("timeout_seconds") or 90)
        headers = {"Content-Type": "application/json"}
        self._apply_auth(headers, provider)
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": str(input_data.get("system") or "")},
                {"role": "user", "content": str(input_data.get("prompt") or "")},
            ],
        }
        if input_data.get("schema"):
            payload["response_format"] = {"type": "json_object"}
        with httpx.Client(timeout=timeout) as client:
            res = client.post(url, headers=headers, json=payload)
            res.raise_for_status()
            data = res.json()
        content = (((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "")
        parsed = self._try_json(content)
        return {"status": "success", "data": parsed if isinstance(parsed, dict) else {"content": content}, "source": provider.get("provider_id", "runtime_provider")}

    def _invoke_http_json(self, provider: dict[str, Any], input_data: dict[str, Any]) -> dict[str, Any]:
        invoke = provider.get("invoke") or {}
        timeout = float(invoke.get("timeout_seconds") or provider.get("timeout_seconds") or 90)
        method = str(input_data.get("method") or invoke.get("http_method") or "POST").upper()
        url = str(input_data.get("url") or invoke.get("url") or "")
        if not url:
            base = str(invoke.get("base_url") or provider.get("base_url") or "").rstrip("/")
            path = str(input_data.get("path") or invoke.get("path") or "")
            url = base + path
        headers = dict(invoke.get("headers") or {})
        headers.update(input_data.get("headers") or {})
        self._apply_auth(headers, provider)
        body = input_data.get("json") if isinstance(input_data.get("json"), dict) else input_data.get("payload", input_data)
        with httpx.Client(timeout=timeout) as client:
            res = client.request(method, url, headers=headers, json=body)
            res.raise_for_status()
            try:
                data = res.json()
            except Exception:
                data = {"content": res.text}
        return {"status": "success", "data": data if isinstance(data, dict) else {"value": data}, "source": provider.get("provider_id", "runtime_provider")}

    def _invoke_command(self, provider: dict[str, Any], input_data: dict[str, Any]) -> dict[str, Any]:
        invoke = provider.get("invoke") or {}
        command = invoke.get("command")
        if not isinstance(command, list) or not command:
            raise RuntimeError("invoke.command must be a non-empty string array")
        timeout = float(invoke.get("timeout_seconds") or provider.get("timeout_seconds") or 300)
        proc = subprocess.run(command, input=json.dumps(input_data, ensure_ascii=False), text=True, capture_output=True, timeout=timeout, encoding="utf-8", errors="replace")
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr[-2000:] or f"command failed with returncode={proc.returncode}")
        parsed = self._try_json(proc.stdout)
        return parsed if isinstance(parsed, dict) else {"status": "success", "data": {"stdout": proc.stdout}, "source": provider.get("provider_id", "runtime_provider")}

    def _invoke_python_function(self, provider: dict[str, Any], input_data: dict[str, Any]) -> dict[str, Any]:
        invoke = provider.get("invoke") or {}
        path = Path(str(invoke.get("module_path") or ""))
        if not path.is_absolute():
            path = Path.cwd() / path
        function = str(invoke.get("function") or "run")
        spec = importlib.util.spec_from_file_location(f"runtime_provider_{path.stem}_{abs(hash(str(path)))}", str(path))
        if spec is None or spec.loader is None:
            raise RuntimeError(f"unable to load module: {path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        fn = getattr(module, function, None)
        if not callable(fn):
            raise RuntimeError(f"callable not found: {function}")
        result = fn(input_data)
        return result if isinstance(result, dict) else {"status": "success", "data": {"value": result}, "source": provider.get("provider_id", "runtime_provider")}

    def _apply_auth(self, headers: dict[str, str], provider: dict[str, Any]) -> None:
        auth = provider.get("auth") if isinstance(provider.get("auth"), dict) else {}
        auth_type = auth.get("type") or provider.get("auth_type")
        if auth_type == "bearer_env":
            env_key = str(auth.get("env") or provider.get("auth_env") or "")
            token = os.environ.get(env_key) if env_key else None
            if not token:
                raise RuntimeError(f"MISSING_SECRET:{env_key or 'provider_api_key'}")
            headers["Authorization"] = "Bearer " + token
        elif auth_type == "api_key_header":
            env_key = str(auth.get("env") or provider.get("auth_env") or "")
            header = str(auth.get("header") or provider.get("auth_header") or "X-API-Key")
            token = os.environ.get(env_key) if env_key else None
            if not token:
                raise RuntimeError(f"MISSING_SECRET:{env_key or 'provider_api_key'}")
            headers[header] = token

    def _validate(self, schema: Any, value: Any) -> str | None:
        if not isinstance(schema, dict) or not schema:
            return None
        errors = [e.message for e in Draft202012Validator(schema).iter_errors(value)]
        return "; ".join(errors) if errors else None

    def _normalize(self, output: Any, provider: dict[str, Any]) -> dict[str, Any]:
        if isinstance(output, dict) and "status" in output:
            output.setdefault("source", provider.get("provider_id", "runtime_provider"))
            output.setdefault("data", {})
            return output
        return {"status": "success", "data": output if isinstance(output, dict) else {"value": output}, "source": provider.get("provider_id", "runtime_provider")}

    def _error(self, code: str, message: str, provider: dict[str, Any], data: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"status": "error", "error": {"code": code, "message": message}, "data": data or {}, "source": provider.get("provider_id", "runtime_provider"), "requires_human_confirmation": False}

    def _try_json(self, text: Any) -> Any:
        if not isinstance(text, str):
            return text
        stripped = text.strip()
        if stripped.startswith("```"):
            stripped = stripped.strip("`").strip()
            if stripped.startswith("json"):
                stripped = stripped[4:].strip()
        try:
            return json.loads(stripped)
        except Exception:
            return text
