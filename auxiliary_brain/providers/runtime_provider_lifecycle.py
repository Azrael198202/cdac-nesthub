from __future__ import annotations

from typing import Any

from auxiliary_brain.models.model_downloader import RuntimeModelDownloader
from auxiliary_brain.providers.runtime_provider_registry import RuntimeProviderRegistry


class RuntimeProviderLifecycle:
    """Prepare, register, and return executable provider artifacts."""

    def __init__(self) -> None:
        self.registry = RuntimeProviderRegistry()
        self.downloader = RuntimeModelDownloader()

    def prepare_and_register(self, artifact: dict[str, Any], *, approved: bool = False) -> dict[str, Any]:
        provider_type = str(artifact.get("provider_type") or "")
        prepare = artifact.get("prepare") if isinstance(artifact.get("prepare"), dict) else {}
        if provider_type == "huggingface_snapshot" or prepare.get("download"):
            candidate = dict(prepare.get("candidate") or {})
            candidate.setdefault("model_id", artifact.get("model_id") or artifact.get("provider_id"))
            candidate.setdefault("runtime", "huggingface_snapshot")
            download = self.downloader.download(candidate, approved=approved)
            if not download.get("ready_for_benchmark") and download.get("requires_human_review"):
                return {"status": "approval_required", "provider_id": artifact.get("provider_id"), "download": download}
            artifact.setdefault("source", {})["download"] = download
            if download.get("local_path"):
                artifact.setdefault("runtime", {})["local_path"] = download.get("local_path")
        return self.registry.register(artifact)
