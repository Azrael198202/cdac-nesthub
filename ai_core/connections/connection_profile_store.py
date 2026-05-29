from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ai_core.config.paths import RUNTIME_DIR
from ai_core.secrets.secret_store import SecretStore


class ConnectionProfileStore:
    """Generic runtime connection profile persistence.

    ai_core does not know what the connection fields mean. Runtime-generated
    capabilities declare connection_schema and secret_schema. This store only
    persists non-secret profile values and maps declared secret fields to secret
    references. Secret values are delegated to SecretStore and never written
    into profile JSON.
    """

    def __init__(self, *, root: Path | None = None, secret_store: SecretStore | None = None) -> None:
        self.root = root or (RUNTIME_DIR / "connections")
        self.secret_store = secret_store or SecretStore()

    def upsert_profile(
        self,
        *,
        tool_id: str,
        profile_id: str,
        config: dict[str, Any] | None = None,
        secrets: dict[str, Any] | None = None,
        secret_schema: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        safe_tool = self._safe_id(tool_id, "tool")
        safe_profile = self._safe_id(profile_id, "default")
        config_payload = config if isinstance(config, dict) else {}
        secrets_payload = secrets if isinstance(secrets, dict) else {}
        secret_refs: dict[str, str] = {}
        for field in self._schema_fields(secret_schema):
            ref = self._secret_ref(safe_tool, safe_profile, field)
            secret_refs[field] = ref
            if field in secrets_payload and str(secrets_payload.get(field) or ""):
                self.secret_store.set(ref, str(secrets_payload[field]))
        # Also persist explicitly provided secret fields even when schema is absent.
        for field, value in secrets_payload.items():
            if not str(field).strip() or not str(value or ""):
                continue
            ref = self._secret_ref(safe_tool, safe_profile, str(field))
            secret_refs[str(field)] = ref
            self.secret_store.set(ref, str(value))
        payload = {
            "tool_id": safe_tool,
            "profile_id": safe_profile,
            "config": config_payload,
            "secret_refs": secret_refs,
            "metadata": metadata if isinstance(metadata, dict) else {},
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        path = self._profile_path(safe_tool, safe_profile)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return self.public_profile(payload)

    def get_profile(self, *, tool_id: str, profile_id: str = "default", include_secrets: bool = False) -> dict[str, Any] | None:
        path = self._profile_path(self._safe_id(tool_id, "tool"), self._safe_id(profile_id, "default"))
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8") or "{}")
        except Exception:
            return None
        if not isinstance(payload, dict):
            return None
        if include_secrets:
            data = dict(payload)
            refs = data.get("secret_refs") if isinstance(data.get("secret_refs"), dict) else {}
            data["secrets"] = {field: self.secret_store.get(ref, "") for field, ref in refs.items()}
            return data
        return self.public_profile(payload)

    def list_profiles(self, tool_id: str | None = None) -> list[dict[str, Any]]:
        roots: list[Path]
        if tool_id:
            roots = [self.root / self._safe_id(tool_id, "tool")]
        else:
            roots = [p for p in self.root.iterdir()] if self.root.exists() else []
        items: list[dict[str, Any]] = []
        for root in roots:
            if not root.exists():
                continue
            for path in root.glob("*.json"):
                try:
                    payload = json.loads(path.read_text(encoding="utf-8") or "{}")
                except Exception:
                    continue
                if isinstance(payload, dict):
                    items.append(self.public_profile(payload))
        items.sort(key=lambda item: (str(item.get("tool_id") or ""), str(item.get("profile_id") or "")))
        return items

    def missing_requirements(self, *, tool_spec: dict[str, Any], profile_id: str = "default") -> dict[str, Any]:
        tool_id = str(tool_spec.get("tool_id") or tool_spec.get("name") or "")
        connection_schema = tool_spec.get("connection_schema") if isinstance(tool_spec.get("connection_schema"), dict) else {}
        secret_schema = tool_spec.get("secret_schema") if isinstance(tool_spec.get("secret_schema"), dict) else {}
        connection_required = bool(connection_schema.get("required")) or bool(self._schema_fields(connection_schema))
        secret_fields = self._schema_fields(secret_schema)
        profile = self.get_profile(tool_id=tool_id, profile_id=profile_id, include_secrets=False)
        missing_config: list[str] = []
        if connection_required:
            if not profile:
                missing_config = self._schema_required_fields(connection_schema) or self._schema_fields(connection_schema)
            else:
                config = profile.get("config") if isinstance(profile.get("config"), dict) else {}
                for field in self._schema_required_fields(connection_schema):
                    if field not in config or config.get(field) in {None, ""}:
                        missing_config.append(field)
        missing_secrets: list[str] = []
        if secret_fields:
            full = self.get_profile(tool_id=tool_id, profile_id=profile_id, include_secrets=True)
            refs = full.get("secret_refs") if isinstance(full, dict) and isinstance(full.get("secret_refs"), dict) else {}
            for field in secret_fields:
                ref = refs.get(field) or self._secret_ref(self._safe_id(tool_id, "tool"), self._safe_id(profile_id, "default"), field)
                if not self.secret_store.has(ref):
                    missing_secrets.append(field)
        return {
            "profile_id": profile_id,
            "connection_required": connection_required,
            "secret_required": bool(secret_fields),
            "missing_config_fields": missing_config,
            "missing_secret_fields": missing_secrets,
            "configured": not missing_config and not missing_secrets,
        }

    def runtime_context_for(self, *, tool_spec: dict[str, Any], profile_id: str = "default") -> dict[str, Any]:
        tool_id = str(tool_spec.get("tool_id") or tool_spec.get("name") or "")
        profile = self.get_profile(tool_id=tool_id, profile_id=profile_id, include_secrets=True) or {}
        return {
            "profile_id": profile_id,
            "connection": profile.get("config") if isinstance(profile.get("config"), dict) else {},
            "secrets": profile.get("secrets") if isinstance(profile.get("secrets"), dict) else {},
            "secret_refs": profile.get("secret_refs") if isinstance(profile.get("secret_refs"), dict) else {},
        }

    def public_profile(self, payload: dict[str, Any]) -> dict[str, Any]:
        refs = payload.get("secret_refs") if isinstance(payload.get("secret_refs"), dict) else {}
        return {
            "tool_id": payload.get("tool_id"),
            "profile_id": payload.get("profile_id"),
            "config": payload.get("config") if isinstance(payload.get("config"), dict) else {},
            "secret_refs": refs,
            "secret_configured": {field: self.secret_store.has(str(ref)) for field, ref in refs.items()},
            "metadata": payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {},
            "updated_at": payload.get("updated_at"),
        }

    def _profile_path(self, tool_id: str, profile_id: str) -> Path:
        return self.root / self._safe_id(tool_id, "tool") / f"{self._safe_id(profile_id, 'default')}.json"

    def _secret_ref(self, tool_id: str, profile_id: str, field: str) -> str:
        return f"RUNTIME_SECRET__{self._safe_id(tool_id, 'tool').upper()}__{self._safe_id(profile_id, 'default').upper()}__{self._safe_id(field, 'FIELD').upper()}"

    def _schema_fields(self, schema: dict[str, Any] | None) -> list[str]:
        if not isinstance(schema, dict):
            return []
        props = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
        return [str(k) for k in props.keys()]

    def _schema_required_fields(self, schema: dict[str, Any] | None) -> list[str]:
        if not isinstance(schema, dict):
            return []
        required = schema.get("required") if isinstance(schema.get("required"), list) else []
        return [str(x) for x in required if str(x).strip()]

    def _safe_id(self, value: str | None, fallback: str) -> str:
        raw = str(value or "").strip() or fallback
        return "".join(c if c.isalnum() or c in {"_", "-"} else "_" for c in raw).strip("_") or fallback
