from __future__ import annotations

import importlib
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from typing import Any

from ai_core.runtime.environment.permission_policy import RuntimePermissionPolicy


@dataclass
class DependencyInstallResult:
    ok: bool
    status: str
    reason: str | None = None
    import_name: str | None = None
    package: str | None = None
    command: list[str] | None = None
    stdout: str | None = None
    stderr: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "status": self.status,
            "reason": self.reason,
            "import_name": self.import_name,
            "package": self.package,
            "command": self.command,
            "stdout": (self.stdout or "")[-2000:],
            "stderr": (self.stderr or "")[-2000:],
        }


class RuntimeDependencyInstaller:
    """Safe, generic Python dependency self-healing helper.

    The core does not infer business behavior. It only repairs missing Python
    dependencies when a provider/module declares a package mapping or when the
    missing import name is safe to install directly.
    """

    DEFAULT_IMPORT_TO_PACKAGE = {
        "PIL": "Pillow",
        "cv2": "opencv-python",
        "yaml": "PyYAML",
        "sklearn": "scikit-learn",
        "bs4": "beautifulsoup4",
        "dotenv": "python-dotenv",
        "dateutil": "python-dateutil",
    }

    def __init__(self, policy: RuntimePermissionPolicy | None = None) -> None:
        self.policy = policy or RuntimePermissionPolicy.from_env()

    def missing_import_from_exception(self, exc: BaseException) -> str:
        name = getattr(exc, "name", "") or ""
        if name:
            return str(name).split(".")[0]
        text = f"{exc.__class__.__name__}: {exc}"
        patterns = [
            r"ModuleNotFoundError:\s+No module named ['\"]([^'\"]+)['\"]",
            r"ImportError:\s+No module named ['\"]([^'\"]+)['\"]",
            r"No module named ['\"]([^'\"]+)['\"]",
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(1).split(".")[0]
        return ""

    def install_for_missing_import(self, import_name: str, *, provider: dict[str, Any] | None = None) -> dict[str, Any]:
        import_name = str(import_name or "").strip().split(".")[0]
        provider = provider if isinstance(provider, dict) else {}
        if not import_name:
            return DependencyInstallResult(False, "skipped", "missing_import_name").to_dict()
        if importlib.util.find_spec(import_name) is not None:
            return DependencyInstallResult(True, "already_available", import_name=import_name).to_dict()
        if not self.policy.can_execute(kind="install"):
            return DependencyInstallResult(False, "requires_setup", "install_not_allowed_by_policy", import_name=import_name).to_dict()
        package = self._package_for_import(import_name, provider=provider)
        if not package:
            return DependencyInstallResult(False, "requires_setup", "unknown_package_mapping", import_name=import_name).to_dict()
        return self.install_package(package, import_name=import_name)

    def install_declared_dependencies(self, provider: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        provider = provider if isinstance(provider, dict) else {}
        deps = provider.get("python_dependencies") or provider.get("dependencies") or []
        if isinstance(deps, str):
            deps = [deps]
        results: list[dict[str, Any]] = []
        for dep in deps if isinstance(deps, list) else []:
            package = str(dep.get("package") if isinstance(dep, dict) else dep or "").strip()
            import_name = str(dep.get("import") or dep.get("import_name") if isinstance(dep, dict) else "").strip()
            if not import_name:
                import_name = self._import_guess_from_package(package)
            if import_name and importlib.util.find_spec(import_name) is not None:
                results.append(DependencyInstallResult(True, "already_available", import_name=import_name, package=package).to_dict())
                continue
            results.append(self.install_package(package, import_name=import_name))
        return results

    def install_package(self, package: str, *, import_name: str | None = None) -> dict[str, Any]:
        package = str(package or "").strip()
        if not package:
            return DependencyInstallResult(False, "skipped", "missing_package", import_name=import_name).to_dict()
        if not self._safe_package_spec(package):
            return DependencyInstallResult(False, "requires_setup", "unsafe_package_spec", import_name=import_name, package=package).to_dict()
        if not self.policy.can_execute(kind="install"):
            return DependencyInstallResult(False, "requires_setup", "install_not_allowed_by_policy", import_name=import_name, package=package).to_dict()
        command = [sys.executable, "-m", "pip", "install", package]
        proc = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=max(120, int(getattr(self.policy, "command_timeout_seconds", 900) or 900)),
            check=False,
        )
        ok = proc.returncode == 0
        if ok:
            importlib.invalidate_caches()
            if import_name and importlib.util.find_spec(import_name.split(".")[0]) is None:
                ok = False
        return DependencyInstallResult(
            ok=ok,
            status="installed" if ok else "failed",
            reason=None if ok else "pip_install_failed",
            import_name=import_name,
            package=package,
            command=command,
            stdout=proc.stdout,
            stderr=proc.stderr,
        ).to_dict()

    def _package_for_import(self, import_name: str, *, provider: dict[str, Any]) -> str:
        mapping: dict[str, Any] = dict(self.DEFAULT_IMPORT_TO_PACKAGE)
        custom = provider.get("python_import_package_map") or provider.get("import_package_map") or {}
        if isinstance(custom, dict):
            mapping.update({str(k): str(v) for k, v in custom.items()})
        deps = provider.get("python_dependencies") or provider.get("dependencies") or []
        if isinstance(deps, list):
            for dep in deps:
                if isinstance(dep, dict):
                    key = str(dep.get("import") or dep.get("import_name") or "").strip()
                    pkg = str(dep.get("package") or "").strip()
                    if key and pkg:
                        mapping[key.split(".")[0]] = pkg
        if import_name in mapping:
            return str(mapping[import_name])
        if self._safe_package_spec(import_name):
            return import_name
        return ""

    def _import_guess_from_package(self, package: str) -> str:
        name = re.split(r"[<>=!~;\[]", str(package or ""), maxsplit=1)[0].strip()
        return name.replace("-", "_")

    def _safe_package_spec(self, package: str) -> bool:
        package = str(package or "").strip()
        if not package or len(package) > 160:
            return False
        if re.search(r"[;&|`$(){}<>\\]", package):
            return False
        return bool(re.match(r"^[A-Za-z0-9_.-]+([<>=!~]=?[A-Za-z0-9_.+!*,-]+)?$", package))
