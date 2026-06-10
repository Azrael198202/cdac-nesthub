from __future__ import annotations

from pathlib import Path
from typing import Any
import os
import re

from ai_core.config.loader import ConfigLoader
from ai_core.config.paths import CONFIGS_DIR, RUNTIME_CONFIGS, RUNTIME_DIR
from ai_core.secrets.secret_store import SecretStore


class VideoGenerationSetupWizard:
    """Runtime setup wizard for video_generation providers.

    The wizard persists runtime-provided provider configuration under
    runtime/configs/media instead of requiring shell exports.  It is generic:
    it stores workflow sources, endpoints, and secrets; it does not encode a
    concrete animation model or business workflow.
    """

    capability_type = "video_generation"

    def __init__(self) -> None:
        self.loader = ConfigLoader()
        self.media_dir = RUNTIME_CONFIGS / "media"
        self.video_config_path = self.media_dir / "video_generation.yaml"
        self.setup_config_path = self.media_dir / "video_provider_setup.yaml"

    def ensure_runtime_config(self) -> None:
        self.media_dir.mkdir(parents=True, exist_ok=True)
        seed = CONFIGS_DIR / "video_generation.seed.yaml"
        if seed.exists() and not self.video_config_path.exists():
            self.video_config_path.write_text(seed.read_text(encoding="utf-8"), encoding="utf-8")

    def interaction_request(self, *, setup_actions: list[dict[str, Any]], attempted: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
        fields: list[dict[str, Any]] = []
        seen: set[str] = set()
        reasons = {str(x.get("reason") or "") for x in (attempted or []) if isinstance(x, dict)}

        def add(field: dict[str, Any]) -> None:
            key = str(field.get("field") or field.get("name") or "")
            if not key or key in seen:
                return
            seen.add(key)
            fields.append(field)

        for action in setup_actions or []:
            if not isinstance(action, dict):
                continue
            kind = str(action.get("kind") or "")
            provider = str(action.get("provider") or "")
            reason = str(action.get("reason") or "")
            if kind == "prepare_local_video_runtime" or reason.startswith("workflow_template") or "workflow" in reason:
                add({
                    "kind": "video_generation_setup",
                    "field": "video_workflow_source",
                    "label": "ComfyUI video workflow source",
                    "message": "Enter a ComfyUI video workflow JSON local path, direct JSON URL, or Git repository URL. The runtime will save it, bootstrap it, and retry the same animation request.",
                    "placeholder": "runtime/configs/media/video_workflows/text_to_video.json or https://.../workflow.json or https://github.com/.../video-workflows.git",
                    "input_type": "text",
                    "required": True,
                    "provider": provider or "local_video_generation",
                    "aliases": ["AI_CORE_VIDEO_WORKFLOW_TEMPLATE", "AI_CORE_VIDEO_WORKFLOW_TEMPLATE_URL", "AI_CORE_VIDEO_WORKFLOW_TEMPLATE_REPOSITORY"],
                })
                add({
                    "kind": "video_generation_setup",
                    "field": "video_workflow_repository_file",
                    "label": "Workflow file inside repository",
                    "message": "Optional. If the source is a Git repository, enter the workflow JSON file path inside that repository.",
                    "placeholder": "text_to_video.json or workflows/text_to_video.json",
                    "input_type": "text",
                    "required": False,
                    "provider": provider or "local_video_generation",
                    "aliases": ["AI_CORE_VIDEO_WORKFLOW_TEMPLATE_REPOSITORY_FILE"],
                })
            if kind == "set_endpoint" or reason == "missing_endpoint" or "missing_endpoint" in reasons:
                add({
                    "kind": "video_generation_setup",
                    "field": "VIDEO_GENERATION_ENDPOINT",
                    "label": "External video endpoint",
                    "message": "Enter the external video generation endpoint. The runtime will save it in runtime provider config and retry the same request.",
                    "placeholder": "https://api.example.com/v1/video/generate",
                    "input_type": "text",
                    "required": True,
                    "provider": provider or "external_video_generation",
                })
            if kind == "set_secret":
                env_name = str(action.get("env") or "VIDEO_GENERATION_API_KEY")
                add({
                    "kind": "secret_input",
                    "field": env_name,
                    "label": env_name,
                    "message": f"Enter {env_name} for the external video provider.",
                    "placeholder": env_name,
                    "input_type": "password",
                    "required": True,
                    "provider": provider or "external_video_generation",
                })

        if not fields:
            return None
        return {
            "type": "runtime_config_input",
            "kind": "video_generation_setup_wizard",
            "capability_type": "video_generation",
            "message": "Video generation needs runtime setup. Fill the missing provider configuration and the same request will be retried automatically.",
            "fields": fields,
            "setup_actions": setup_actions or [],
            "attempted": attempted or [],
        }

    def apply_inputs(self, provided_inputs: dict[str, Any] | None) -> dict[str, Any]:
        data = provided_inputs if isinstance(provided_inputs, dict) else {}
        if not data:
            return {"ok": True, "status": "no_setup_inputs"}
        self.ensure_runtime_config()
        changes: list[dict[str, Any]] = []
        config = self.loader.load_yaml(self.video_config_path)
        if not isinstance(config, dict):
            config = {}
        providers = config.setdefault("providers", {})
        if not isinstance(providers, dict):
            providers = {}
            config["providers"] = providers
        local = providers.setdefault("local_video_generation", {})
        external = providers.setdefault("external_video_generation", {})

        source = self._first_text(data, "video_workflow_source", "AI_CORE_VIDEO_WORKFLOW_TEMPLATE", "AI_CORE_VIDEO_WORKFLOW_TEMPLATE_URL", "AI_CORE_VIDEO_WORKFLOW_TEMPLATE_REPOSITORY")
        if source:
            self._apply_workflow_source(local, source, data, changes)

        repo_file = self._first_text(data, "video_workflow_repository_file", "AI_CORE_VIDEO_WORKFLOW_TEMPLATE_REPOSITORY_FILE")
        if repo_file:
            boot = local.setdefault("workflow_bootstrap", {})
            if isinstance(boot, dict):
                boot["repository_file"] = repo_file
                changes.append({"field": "workflow_bootstrap.repository_file", "value": repo_file})

        endpoint = self._first_text(data, "VIDEO_GENERATION_ENDPOINT", "video_generation_endpoint", "video_endpoint", "endpoint")
        if endpoint:
            external["video_generation_endpoint"] = endpoint
            changes.append({"field": "external_video_generation.video_generation_endpoint", "value": endpoint})

        secret_key = str(data.get("secret_key") or "").strip()
        secret_value = str(data.get("value") or "").strip()
        if secret_key and secret_value:
            SecretStore().set(secret_key, secret_value)
            changes.append({"field": f"secret:{secret_key}", "status": "saved"})
        for key in ("VIDEO_GENERATION_API_KEY", "api_key", "video_generation_api_key"):
            val = str(data.get(key) or "").strip()
            if val:
                SecretStore().set("VIDEO_GENERATION_API_KEY", val)
                external.setdefault("api_key_env", "VIDEO_GENERATION_API_KEY")
                changes.append({"field": "secret:VIDEO_GENERATION_API_KEY", "status": "saved"})

        self.loader.save_yaml(self.video_config_path, config)
        self._save_setup_sidecar(data=data, changes=changes)
        return {"ok": True, "status": "saved" if changes else "no_changes", "changes": changes, "path": str(self.video_config_path)}

    def _first_text(self, data: dict[str, Any], *keys: str) -> str:
        for key in keys:
            value = data.get(key)
            if isinstance(value, list):
                value = " ".join(str(x) for x in value if str(x).strip())
            text = str(value or "").strip()
            if text:
                return text
        return ""

    def _apply_workflow_source(self, local: dict[str, Any], source: str, data: dict[str, Any], changes: list[dict[str, Any]]) -> None:
        boot = local.setdefault("workflow_bootstrap", {})
        if not isinstance(boot, dict):
            boot = {}
            local["workflow_bootstrap"] = boot
        source = source.strip()
        if self._looks_like_git_repo(source):
            boot["repository"] = source
            boot["enabled"] = True
            local["workflow_template"] = ""
            changes.append({"field": "workflow_bootstrap.repository", "value": self._redact(source)})
            return
        if self._looks_like_url(source):
            boot["url"] = source
            boot["enabled"] = True
            local["workflow_template"] = ""
            changes.append({"field": "workflow_bootstrap.url", "value": self._redact(source)})
            return
        path = str(Path(os.path.expandvars(source)).expanduser())
        local["workflow_template"] = path
        boot["enabled"] = True
        changes.append({"field": "local_video_generation.workflow_template", "value": path})

    def _save_setup_sidecar(self, *, data: dict[str, Any], changes: list[dict[str, Any]]) -> None:
        safe_data: dict[str, Any] = {}
        for key, value in data.items():
            if "key" in key.lower() or "secret" in key.lower() or key == "value":
                safe_data[key] = "<redacted>"
            else:
                safe_data[key] = value
        self.loader.save_yaml(self.setup_config_path, {"capability_type": "video_generation", "last_inputs": safe_data, "last_changes": changes})

    def _looks_like_url(self, value: str) -> bool:
        return bool(re.match(r"^https?://", value.strip(), flags=re.IGNORECASE))

    def _looks_like_git_repo(self, value: str) -> bool:
        text = value.strip().lower()
        return text.endswith(".git") or "github.com/" in text or "gitlab.com/" in text or text.startswith("git@")

    def _redact(self, value: str) -> str:
        return re.sub(r"([?&][^=]*(?:key|token|secret|credential)[^=]*=)[^&]+", r"\1***", str(value), flags=re.IGNORECASE)
