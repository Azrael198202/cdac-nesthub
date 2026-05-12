from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

from ai_core.config.paths import RUNTIME_GENERATED, RUNTIME_REGISTRY


class RuntimeGeneratedToolInstaller:
    """
    Installs runtime-generated tool artifacts into runtime/generated/tools.

    This installer is intentionally generic. It does not know what a tool does,
    how a capability should work, or which external API should be used.

    The artifact is expected to be produced by the runtime intelligence layer
    such as an LLM/code-generation step or a human-reviewed code artifact.
    """

    def __init__(self) -> None:
        self.tools_dir = RUNTIME_GENERATED / "tools"
        self.registry_path = RUNTIME_REGISTRY / "tool_registry.json"
        self.tools_dir.mkdir(parents=True, exist_ok=True)
        RUNTIME_REGISTRY.mkdir(parents=True, exist_ok=True)
        if not self.registry_path.exists():
            self.registry_path.write_text("{}", encoding="utf-8")

    def install_from_step(
        self,
        *,
        capability: str,
        step: dict[str, Any],
        user_input: str = "",
    ) -> dict[str, Any] | None:
        artifact = self._extract_artifact(step)
        if not artifact:
            return None
        return self.install_artifact(
            artifact=artifact,
            capability=capability,
            source_step=step,
            user_input=user_input,
        )

    def install_artifact(
        self,
        *,
        artifact: dict[str, Any],
        capability: str,
        source_step: dict[str, Any] | None = None,
        user_input: str = "",
    ) -> dict[str, Any]:
        tool_id = self._safe_name(str(artifact.get("tool_id") or f"generated_{capability}"))
        target_dir = self.tools_dir / tool_id
        target_dir.mkdir(parents=True, exist_ok=True)

        files = artifact.get("files")
        if not isinstance(files, dict) or not files:
            raise ValueError("Runtime tool artifact must contain a non-empty files object.")

        written_files: dict[str, str] = {}
        for relative_name, content in files.items():
            path = self._safe_child_path(target_dir, str(relative_name))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(str(content), encoding="utf-8")
            written_files[str(relative_name)] = str(path)

        manifest = artifact.get("manifest") if isinstance(artifact.get("manifest"), dict) else {}
        manifest = dict(manifest)
        manifest.setdefault("tool_id", tool_id)
        manifest.setdefault("name", tool_id)
        manifest.setdefault("capability", capability)
        manifest.setdefault("capabilities", [capability])
        manifest.setdefault("status", "enabled")
        manifest.setdefault("created_at", datetime.utcnow().isoformat())
        manifest.setdefault("runtime_generated", True)
        manifest.setdefault("source", "runtime_generated_artifact")
        manifest.setdefault("source_user_input", user_input)
        manifest.setdefault("source_step", source_step or {})
        manifest.setdefault("input_schema", {"type": "object", "additionalProperties": True})
        manifest.setdefault("output_schema", {"type": "object", "additionalProperties": True})
        manifest.setdefault("safety", {
            "can_read_external_data": "runtime_declared",
            "can_write_external_data": False,
            "can_perform_irreversible_action": False,
            "requires_human_confirmation": bool((source_step or {}).get("requires_human_confirmation", False)),
            "generated_code_must_be_reviewed": bool(artifact.get("requires_review", False)),
        })

        implementation = manifest.setdefault("implementation", {})
        if not isinstance(implementation, dict):
            implementation = {}
            manifest["implementation"] = implementation
        implementation.setdefault("type", "python_function")
        implementation.setdefault("function", "run")
        module_path = implementation.get("module_path") or implementation.get("path") or "tool.py"
        module_file_name = Path(str(module_path)).name
        if module_file_name not in {Path(name).name for name in written_files.keys()}:
            # Fall back to the first written file if the manifest did not match.
            module_file_name = Path(next(iter(written_files.values()))).name
        implementation["module_path"] = str(target_dir / module_file_name)

        manifest_path = target_dir / "tool.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

        registry = self._load_registry()
        registry[tool_id] = {
            "tool_id": tool_id,
            "name": manifest.get("name", tool_id),
            "capability": manifest.get("capability", capability),
            "capabilities": manifest.get("capabilities", [capability]),
            "status": manifest.get("status", "enabled"),
            "spec_path": str(manifest_path),
            "implementation": manifest.get("implementation", {}),
            "input_schema": manifest.get("input_schema", {"type": "object", "additionalProperties": True}),
            "output_schema": manifest.get("output_schema", {"type": "object", "additionalProperties": True}),
            "safety": manifest.get("safety", {}),
            "runtime_generated": True,
            "source": manifest.get("source"),
        }
        self.registry_path.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")
        return registry[tool_id]

    def _extract_artifact(self, step: dict[str, Any]) -> dict[str, Any] | None:
        for key in [
            "runtime_tool_generation",
            "runtime_generated_tool",
            "tool_generation_artifact",
            "generated_tool_artifact",
        ]:
            value = step.get(key)
            if isinstance(value, dict):
                return value
        return None

    def _load_registry(self) -> dict[str, Any]:
        try:
            return json.loads(self.registry_path.read_text(encoding="utf-8") or "{}")
        except json.JSONDecodeError:
            return {}

    def _safe_child_path(self, base_dir: Path, relative_name: str) -> Path:
        pure = PurePosixPath(relative_name.replace("\\", "/"))
        if pure.is_absolute() or ".." in pure.parts:
            raise ValueError(f"Unsafe runtime tool file path: {relative_name}")
        return base_dir / Path(*pure.parts)

    def _safe_name(self, value: str) -> str:
        return "".join(c if c.isalnum() else "_" for c in value).strip("_").lower() or "runtime_tool"
