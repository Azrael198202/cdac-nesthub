from __future__ import annotations

import ast
import builtins
import importlib.util
from pathlib import Path
from typing import Any

from auxiliary_brain.runtime_codegen.dynamic_value_hardcode_detector import DynamicValueHardcodeDetector


class RuntimeToolArtifactValidator:
    """Validates runtime-generated Python tool artifacts generically.

    This validator is intentionally domain-neutral. It does not know what the
    tool does. It only checks whether the generated code is structurally usable:

    - Python syntax is valid
    - declared callable exists
    - callable is actually callable
    - common undefined local function calls are detected before registration

    It does not contain business/API/provider logic.
    """

    def validate_python_file(self, path: Path, *, callable_name: str = "run", runtime_variables: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        errors: list[str] = []
        try:
            source = path.read_text(encoding="utf-8")
        except Exception as exc:
            return {"valid": False, "errors": [f"unable_to_read_file: {exc}"]}

        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError as exc:
            return {"valid": False, "errors": [f"syntax_error: {exc}"]}

        defined_functions = {node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        imported_names: set[str] = set()
        assigned_names: set[str] = set()
        builtin_names = set(dir(builtins))

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported_names.add(alias.asname or alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    imported_names.add(alias.asname or alias.name)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    assigned_names.update(self._assigned_names(target))
            elif isinstance(node, ast.AnnAssign):
                assigned_names.update(self._assigned_names(node.target))
            elif isinstance(node, ast.For):
                assigned_names.update(self._assigned_names(node.target))
            elif isinstance(node, ast.With):
                for item in node.items:
                    if item.optional_vars:
                        assigned_names.update(self._assigned_names(item.optional_vars))

        if callable_name not in defined_functions:
            errors.append(f"callable_missing: function '{callable_name}' is not defined")

        available = defined_functions | imported_names | assigned_names | builtin_names
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                name = node.func.id
                if name not in available:
                    errors.append(f"undefined_callable: name '{name}' is called but not defined/imported")

        dynamic_check = DynamicValueHardcodeDetector().detect(source, runtime_variables or [])
        if not dynamic_check.get("passed"):
            for finding in dynamic_check.get("findings", []):
                errors.append(f"hardcoded_runtime_value: {finding.get('variable')}={finding.get('value')}")

        if errors:
            return {"valid": False, "errors": sorted(set(errors))}

        # Importability check. Generated module top-level code should not crash
        # on import. Network calls should be inside run(), not at import time.
        try:
            module_name = f"runtime_tool_validation_{path.stem}_{abs(hash(str(path)))}"
            spec = importlib.util.spec_from_file_location(module_name, str(path))
            if spec is None or spec.loader is None:
                return {"valid": False, "errors": ["module_spec_unavailable"]}
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            fn = getattr(module, callable_name, None)
            if not callable(fn):
                return {"valid": False, "errors": [f"callable_not_callable: {callable_name}"]}
        except Exception as exc:
            return {"valid": False, "errors": [f"import_validation_failed: {exc}"]}

        return {"valid": True, "errors": []}

    def _assigned_names(self, target: ast.AST) -> set[str]:
        names: set[str] = set()
        if isinstance(target, ast.Name):
            names.add(target.id)
        elif isinstance(target, (ast.Tuple, ast.List)):
            for element in target.elts:
                names.update(self._assigned_names(element))
        return names
