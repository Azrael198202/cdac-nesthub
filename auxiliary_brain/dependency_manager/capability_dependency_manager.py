from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from ai_core.config.paths import RUNTIME_TRACES
except Exception:  # pragma: no cover
    RUNTIME_TRACES = Path('runtime/traces')


@dataclass
class CapabilityDependencyPolicy:
    runtime_language: str = 'python'
    standard_library_only: bool = False
    allow_install: bool = True
    allow_ensurepip: bool = True
    timeout_seconds: int = 600


@dataclass
class CapabilityDependencyResult:
    passed: bool
    status: str
    checks: list[dict[str, Any]] = field(default_factory=list)
    dependencies: list[dict[str, Any]] = field(default_factory=list)
    policy: dict[str, Any] = field(default_factory=dict)
    trace_path: str = ''

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class CapabilityDependencyManager:
    """Contract-aware dependency manager for generated runtime capabilities.

    This manager is generic and language-aware.  For Python artifacts it scans
    declared and discovered imports, distinguishes standard-library modules from
    external packages, enforces explicit ``standard library only`` contracts, and
    installs allowed missing packages through ``python -m pip`` when policy permits.
    """

    IMPORT_TO_PACKAGE = {
        'PIL': 'Pillow',
        'cv2': 'opencv-python',
        'yaml': 'PyYAML',
        'bs4': 'beautifulsoup4',
        'dotenv': 'python-dotenv',
        'dateutil': 'python-dateutil',
        'sklearn': 'scikit-learn',
    }

    def __init__(self, *, run_id: str = '', trace_root: Path | None = None) -> None:
        self.run_id = run_id or 'capability_dependency'
        self.trace_root = trace_root or (RUNTIME_TRACES / 'capability_dependency_manager')

    def resolve(self, dependencies: list[dict[str, Any]], *, policy: CapabilityDependencyPolicy | None = None) -> dict[str, Any]:
        policy = policy or CapabilityDependencyPolicy()
        trace_path = self._trace_path()
        deps = self._normalize_dependencies(dependencies)
        checks: list[dict[str, Any]] = []
        self._record(trace_path, 'start', {'dependencies': deps, 'policy': asdict(policy)})

        if str(policy.runtime_language or 'python').lower() not in {'python', 'py', 'python3'}:
            result = CapabilityDependencyResult(False, 'unsupported_runtime_language', checks, deps, asdict(policy), str(trace_path))
            self._record(trace_path, 'finish', result.to_dict())
            return result.to_dict()

        for dep in deps:
            import_name = str(dep.get('import_name') or dep.get('module') or '').split('.', 1)[0]
            package = str(dep.get('package') or dep.get('name') or import_name).strip()
            source = str(dep.get('source') or '')
            check: dict[str, Any] = {'import_name': import_name, 'package': package, 'source': source}
            if not import_name and package:
                import_name = self._import_guess(package)
                check['import_name'] = import_name
            if not import_name and not package:
                check.update({'status': 'skipped', 'reason': 'empty_dependency'})
                checks.append(check)
                continue
            if self._is_stdlib_import(import_name):
                check.update({'status': 'stdlib', 'installed': False})
                checks.append(check)
                continue
            if import_name and importlib.util.find_spec(import_name) is not None:
                check.update({'status': 'available', 'installed': False})
                checks.append(check)
                continue
            if policy.standard_library_only:
                check.update({'status': 'contract_violation', 'reason': 'external_dependency_disallowed_by_standard_library_only'})
                checks.append(check)
                result = CapabilityDependencyResult(False, 'standard_library_contract_violation', checks, deps, asdict(policy), str(trace_path))
                self._record(trace_path, 'finish', result.to_dict())
                return result.to_dict()
            if not policy.allow_install:
                check.update({'status': 'missing', 'reason': 'install_not_allowed'})
                checks.append(check)
                result = CapabilityDependencyResult(False, 'missing_dependency', checks, deps, asdict(policy), str(trace_path))
                self._record(trace_path, 'finish', result.to_dict())
                return result.to_dict()
            package = self._package_for_import(import_name, package)
            if not self._safe_package_spec(package):
                check.update({'status': 'blocked', 'reason': 'unsafe_package_spec'})
                checks.append(check)
                result = CapabilityDependencyResult(False, 'unsafe_dependency_spec', checks, deps, asdict(policy), str(trace_path))
                self._record(trace_path, 'finish', result.to_dict())
                return result.to_dict()
            pip_ready = self._ensure_pip(policy)
            check['ensurepip'] = pip_ready
            if not pip_ready.get('ok'):
                check.update({'status': 'pip_unavailable', 'reason': pip_ready.get('reason')})
                checks.append(check)
                result = CapabilityDependencyResult(False, 'pip_unavailable', checks, deps, asdict(policy), str(trace_path))
                self._record(trace_path, 'finish', result.to_dict())
                return result.to_dict()
            install = self._pip_install(package, policy)
            check['pip'] = install
            importlib.invalidate_caches()
            if import_name and importlib.util.find_spec(import_name) is None:
                check.update({'status': 'install_completed_but_import_failed', 'installed': install.get('returncode') == 0})
                checks.append(check)
                result = CapabilityDependencyResult(False, 'dependency_import_verification_failed', checks, deps, asdict(policy), str(trace_path))
                self._record(trace_path, 'finish', result.to_dict())
                return result.to_dict()
            check.update({'status': 'installed' if install.get('returncode') == 0 else 'install_failed', 'installed': install.get('returncode') == 0})
            if install.get('returncode') != 0:
                checks.append(check)
                result = CapabilityDependencyResult(False, 'dependency_installation_failed', checks, deps, asdict(policy), str(trace_path))
                self._record(trace_path, 'finish', result.to_dict())
                return result.to_dict()
            checks.append(check)
        result = CapabilityDependencyResult(True, 'completed' if deps else 'not_required', checks, deps, asdict(policy), str(trace_path))
        self._record(trace_path, 'finish', result.to_dict())
        return result.to_dict()

    def _normalize_dependencies(self, dependencies: Any) -> list[dict[str, Any]]:
        if not isinstance(dependencies, list):
            return []
        out: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for item in dependencies:
            if not isinstance(item, dict):
                continue
            import_name = str(item.get('import_name') or item.get('module') or '').strip().split('.', 1)[0]
            package = str(item.get('package') or item.get('name') or import_name).strip()
            if not import_name and package:
                import_name = self._import_guess(package)
            if not import_name and not package:
                continue
            key = (import_name, package)
            if key in seen:
                continue
            seen.add(key)
            out.append({**item, 'import_name': import_name, 'package': package})
        return out

    def _is_stdlib_import(self, import_name: str) -> bool:
        name = str(import_name or '').split('.', 1)[0]
        if not name:
            return False
        if name in set(getattr(sys, 'stdlib_module_names', set())):
            return True
        spec = importlib.util.find_spec(name)
        if spec is None or not spec.origin:
            return False
        origin = str(spec.origin)
        if origin in {'built-in', 'frozen'}:
            return True
        purelib_markers = ('site-packages', 'dist-packages')
        return not any(marker in origin for marker in purelib_markers) and (origin.startswith(sys.base_prefix) or origin.startswith(sys.prefix))

    def _ensure_pip(self, policy: CapabilityDependencyPolicy) -> dict[str, Any]:
        check = self._run([sys.executable, '-m', 'pip', '--version'], timeout=60)
        if check.get('returncode') == 0:
            return {'ok': True, 'status': 'available', 'check': check}
        if not policy.allow_ensurepip:
            return {'ok': False, 'status': 'missing', 'reason': 'ensurepip_not_allowed', 'check': check}
        ensure = self._run([sys.executable, '-m', 'ensurepip', '--upgrade'], timeout=max(120, policy.timeout_seconds))
        verify = self._run([sys.executable, '-m', 'pip', '--version'], timeout=60)
        return {'ok': verify.get('returncode') == 0, 'status': 'bootstrapped' if verify.get('returncode') == 0 else 'failed', 'check': check, 'ensurepip': ensure, 'verify': verify, 'reason': None if verify.get('returncode') == 0 else 'ensurepip_failed'}

    def _pip_install(self, package: str, policy: CapabilityDependencyPolicy) -> dict[str, Any]:
        return self._run([sys.executable, '-m', 'pip', 'install', package], timeout=max(120, policy.timeout_seconds))

    def _run(self, cmd: list[str], *, timeout: int) -> dict[str, Any]:
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=timeout, check=False)
            return {'command': cmd, 'returncode': proc.returncode, 'stdout': (proc.stdout or '')[-3000:], 'stderr': (proc.stderr or '')[-3000:]}
        except Exception as exc:
            return {'command': cmd, 'returncode': -1, 'stdout': '', 'stderr': str(exc)[:3000], 'error_type': exc.__class__.__name__}

    def _package_for_import(self, import_name: str, package: str) -> str:
        return self.IMPORT_TO_PACKAGE.get(import_name, package or import_name)

    def _import_guess(self, package: str) -> str:
        name = re.split(r'[<>=!~;\[]', str(package or ''), maxsplit=1)[0].strip()
        return name.replace('-', '_')

    def _safe_package_spec(self, package: str) -> bool:
        package = str(package or '').strip()
        if not package or len(package) > 1000:
            return False
        # Conservative default for generated runtime installation. This avoids
        # shell fragments while allowing normal package names and version specs.
        return bool(re.match(r'^[A-Za-z0-9_.-]+(?:\[[A-Za-z0-9_.-]+(?:,[A-Za-z0-9_.-]+)*\])?(?:(?:==|!=|<=|>=|~=|<|>)[A-Za-z0-9_.+!*,-]+)?$', package))

    def _trace_path(self) -> Path:
        safe = re.sub(r'[^A-Za-z0-9_.-]+', '_', self.run_id or 'capability_dependency')[:80]
        path = self.trace_root / safe / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f') + '.jsonl')
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def _record(self, path: Path, stage: str, data: dict[str, Any]) -> None:
        with path.open('a', encoding='utf-8') as f:
            f.write(json.dumps({'at': datetime.now(timezone.utc).isoformat(), 'stage': stage, 'data': data}, ensure_ascii=False, default=str) + '\n')
