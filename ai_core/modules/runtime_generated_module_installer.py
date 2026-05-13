from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

from ai_core.config.paths import RUNTIME_GENERATED
from ai_core.modules.module_artifact_validator import RuntimeModuleArtifactValidator
from ai_core.modules.module_registry import RuntimeModuleRegistry


class RuntimeGeneratedModuleInstaller:
    """Installs executable runtime-generated modules and registers them."""

    def __init__(self) -> None:
        self.modules_dir = RUNTIME_GENERATED / "modules"
        self.modules_dir.mkdir(parents=True, exist_ok=True)
        self.registry = RuntimeModuleRegistry()
        self.validator = RuntimeModuleArtifactValidator()

    def install_artifact(self, *, artifact: dict[str, Any], capability: str, source_step: dict[str, Any] | None = None, user_input: str = "") -> dict[str, Any]:
        module_id = self._safe_name(str(artifact.get("module_id") or f"module_{capability}"))
        target_dir = self.modules_dir / module_id
        target_dir.mkdir(parents=True, exist_ok=True)

        files = artifact.get("files")
        if not isinstance(files, dict) or not files:
            raise ValueError("Runtime module artifact must contain files.")

        for rel_name, content in files.items():
            path = self._safe_child_path(target_dir, str(rel_name))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(str(content), encoding="utf-8")

        module_py = target_dir / "module.py"
        if not module_py.exists():
            # Fall back to first python file if artifact named it differently.
            py_files = list(target_dir.glob("*.py"))
            if py_files:
                module_py = py_files[0]
            else:
                raise ValueError("Runtime module artifact did not include module.py or any .py file.")

        validation = self.validator.validate_python_file(module_py)
        if not validation.get("valid"):
            raise ValueError("Generated runtime module failed validation: " + "; ".join(validation.get("errors", [])))

        manifest = dict(artifact.get("manifest") or {})
        manifest.setdefault("module_id", module_id)
        manifest.setdefault("capability", capability)
        manifest.setdefault("capabilities", [capability])
        manifest.setdefault("status", "enabled")
        manifest.setdefault("created_at", datetime.utcnow().isoformat())
        manifest.setdefault("runtime_generated", True)
        manifest.setdefault("source", "runtime_generated_module_artifact")
        manifest.setdefault("source_user_input", user_input)
        manifest.setdefault("source_step", source_step or {})
        manifest.setdefault("execution_claims", {
            "real_execution": artifact.get("real_execution"),
            "no_mock_data": artifact.get("no_mock_data"),
            "uses_network": artifact.get("uses_network"),
            "generated_by_runtime": True,
        })
        manifest_path = target_dir / "module.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

        return self.registry.register(
            module_id=module_id,
            capability=capability,
            module_dir=target_dir,
            status="enabled",
            metadata={
                "source": "runtime_generated_module_installer",
                "manifest_path": str(manifest_path),
                "entrypoint": str(module_py),
            },
        )

    def _safe_child_path(self, base_dir: Path, relative_name: str) -> Path:
        pure = PurePosixPath(relative_name.replace("\\", "/"))
        if pure.is_absolute() or ".." in pure.parts:
            raise ValueError(f"Unsafe runtime module file path: {relative_name}")
        return base_dir / Path(*pure.parts)

    def _safe_name(self, value: str) -> str:
        return "".join(c if c.isalnum() else "_" for c in value).strip("_").lower() or "runtime_module"
