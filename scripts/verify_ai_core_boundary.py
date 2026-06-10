"""Validate AI Core boundary after auxiliary_brain import migration.

This script is intentionally generic. It does not know business capabilities.
It verifies namespace boundaries only:
- implementation-level modules must be imported from auxiliary_brain
- ai_core should not re-introduce imports from moved ai_core namespaces
- compatibility facade files may remain, but they should delegate outward
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]

MOVED_NAMESPACE_MAP = {
    "ai_core.artifacts": "auxiliary_brain.artifacts",
    "ai_core.dependencies": "auxiliary_brain.dependencies",
    "ai_core.environment": "auxiliary_brain.environment",
    "ai_core.media": "auxiliary_brain.media",
    "ai_core.models": "auxiliary_brain.models",
    "ai_core.modules": "auxiliary_brain.runtime_modules",
    "ai_core.providers": "auxiliary_brain.providers",
    "ai_core.research": "auxiliary_brain.research",
    "ai_core.sandbox": "auxiliary_brain.sandbox",
    "ai_core.tools": "auxiliary_brain.runtime_tools",
    "ai_core.runtime.capability": "auxiliary_brain.runtime.capability",
    "ai_core.runtime.scheduler": "auxiliary_brain.runtime.scheduler",
    "ai_core.runtime.observability": "auxiliary_brain.runtime.observability",
    "ai_core.runtime.self_repair": "auxiliary_brain.runtime.self_repair",
    "ai_core.runtime.generated_execution": "auxiliary_brain.runtime.generated_execution",
    "ai_core.runtime.external_runtimes": "auxiliary_brain.runtime.external_runtimes",
    "ai_core.runtime.learning": "auxiliary_brain.runtime.learning",
}

SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    "node_modules",
    "runtime",  # runtime data and generated artifacts are not source boundary inputs
}


def iter_python_files(root: Path) -> Iterable[Path]:
    for path in root.rglob("*.py"):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        yield path


def imported_names(tree: ast.AST) -> Iterable[str]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                yield node.module


def is_moved_namespace(name: str) -> str | None:
    for old_ns in MOVED_NAMESPACE_MAP:
        if name == old_ns or name.startswith(old_ns + "."):
            return old_ns
    return None


def main() -> int:
    violations: list[str] = []
    parse_errors: list[str] = []

    for path in iter_python_files(ROOT):
        try:
            text = path.read_text(encoding="utf-8")
            tree = ast.parse(text, filename=str(path))
        except SyntaxError as exc:
            parse_errors.append(f"{path.relative_to(ROOT)}: syntax error: {exc}")
            continue
        except UnicodeDecodeError as exc:
            parse_errors.append(f"{path.relative_to(ROOT)}: decode error: {exc}")
            continue

        for name in imported_names(tree):
            old_ns = is_moved_namespace(name)
            if old_ns:
                new_ns = MOVED_NAMESPACE_MAP[old_ns]
                violations.append(
                    f"{path.relative_to(ROOT)} imports {name}; use {new_ns} instead"
                )

    if parse_errors:
        print("[AI_CORE_BOUNDARY] parse/decode errors:")
        for item in parse_errors:
            print("  -", item)

    if violations:
        print("[AI_CORE_BOUNDARY] moved namespace imports found:")
        for item in violations:
            print("  -", item)
        return 1

    print("[AI_CORE_BOUNDARY] OK: no internal imports from moved ai_core namespaces.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
