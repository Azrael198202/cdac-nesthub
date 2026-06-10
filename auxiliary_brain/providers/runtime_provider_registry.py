from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from ai_core.config.loader import ConfigLoader
from ai_core.config.paths import CONFIGS_DIR, RUNTIME_GENERATED, RUNTIME_REGISTRY, SCHEMA_DIR


@dataclass
class RuntimeProviderRegistrationResult:
    status: str
    provider_id: str
    provider_type: str
    registry_path: str
    artifact_path: str | None
    reason: str


class RuntimeProviderRegistry:
    """Register runtime provider usage methods.

    A provider is a generic execution contract. It may point to Ollama, an API,
    a HuggingFace snapshot bound to a local runtime, a command, or a generated
    Python module. The registry does not contain business-domain decisions.
    """

    def __init__(self) -> None:
        self.loader = ConfigLoader()
        self.registry_path = RUNTIME_REGISTRY / "runtime_provider_registry.json"
        self.generated_root = RUNTIME_GENERATED / "providers"
        self.schema_path = SCHEMA_DIR / "runtime_provider.schema.json"
        self.templates_path = CONFIGS_DIR / "provider_runtime_templates.seed.json"
        self.generated_root.mkdir(parents=True, exist_ok=True)
        RUNTIME_REGISTRY.mkdir(parents=True, exist_ok=True)
        if not self.registry_path.exists():
            self.registry_path.write_text("{}", encoding="utf-8")

    def load_templates(self) -> dict[str, Any]:
        return self._read_json(self.templates_path)

    def register(self, artifact: dict[str, Any], *, source: dict[str, Any] | None = None) -> dict[str, Any]:
        validation = self.validate(artifact)
        provider_id = str(artifact.get("provider_id") or "").strip()
        provider_type = str(artifact.get("provider_type") or "").strip()
        if not validation["valid"]:
            return asdict(RuntimeProviderRegistrationResult(
                "failed", provider_id or "unknown", provider_type or "unknown", str(self.registry_path), None,
                "; ".join(validation["errors"]),
            ))

        provider_id = self._safe_id(provider_id)
        artifact = dict(artifact)
        artifact["provider_id"] = provider_id
        artifact.setdefault("source", source or {})
        artifact["registered_at"] = datetime.now(timezone.utc).isoformat()
        artifact_path = self.generated_root / f"{provider_id}.json"
        artifact_path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8")

        registry = self._read_json(self.registry_path)
        registry[provider_id] = {
            "provider_id": provider_id,
            "provider_type": provider_type,
            "artifact_path": str(artifact_path),
            "capabilities": artifact.get("capabilities", []),
            "modalities": artifact.get("modalities", {}),
            "status": "active",
            "registered_at": artifact["registered_at"],
        }
        self.registry_path.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")
        return asdict(RuntimeProviderRegistrationResult("registered", provider_id, provider_type, str(self.registry_path), str(artifact_path), "Provider registered."))

    def get(self, provider_id: str) -> dict[str, Any] | None:
        registry = self._read_json(self.registry_path)
        record = registry.get(provider_id)
        if not isinstance(record, dict):
            return None
        artifact_path = Path(str(record.get("artifact_path") or ""))
        if not artifact_path.exists():
            return None
        artifact = self._read_json(artifact_path)
        return artifact if isinstance(artifact, dict) else None

    def validate(self, artifact: dict[str, Any]) -> dict[str, Any]:
        errors: list[str] = []
        if not isinstance(artifact, dict):
            return {"valid": False, "errors": ["artifact must be an object"]}
        schema = self._read_json(self.schema_path)
        if schema:
            validator = Draft202012Validator(schema)
            errors.extend([e.message for e in validator.iter_errors(artifact)])
        templates = self.load_templates()
        provider_types = templates.get("provider_types") if isinstance(templates.get("provider_types"), dict) else {}
        provider_type = str(artifact.get("provider_type") or "")
        if provider_type and provider_type not in provider_types:
            errors.append(f"provider_type is not declared in provider runtime templates: {provider_type}")
        method = str((artifact.get("invoke") or {}).get("method") or "")
        supported = (((templates.get("runtime_artifact_contract") or {}).get("supported_invoke_methods")) or [])
        if supported and method and method not in supported:
            errors.append(f"invoke.method is not supported: {method}")
        return {"valid": not errors, "errors": errors}

    def _read_json(self, path: Path) -> dict[str, Any]:
        try:
            return json.loads(path.read_text(encoding="utf-8") or "{}")
        except Exception:
            return {}

    def _safe_id(self, value: str) -> str:
        return "".join(c if c.isalnum() or c in {"_", "-", "."} else "_" for c in value).strip("._-")[:160] or "runtime_provider"
