from __future__ import annotations

import ast
import builtins
import importlib.util
from pathlib import Path
from typing import Any

from auxiliary_brain.runtime_codegen.dynamic_value_hardcode_detector import DynamicValueHardcodeDetector


class RuntimeModuleArtifactValidator:
    """Domain-neutral validation for generated runtime modules."""

    REQUIRED_FUNCTIONS = {"validate_config", "health_check", "run"}

    def validate_python_file(self, path: Path, *, runtime_variables: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        errors: list[str] = []
        try:
            source = path.read_text(encoding="utf-8")
        except Exception as exc:
            return {"valid": False, "errors": [f"unable_to_read_file: {exc}"]}
        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError as exc:
            return {"valid": False, "errors": [f"syntax_error: {exc}"]}

        defined = {n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        imported: set[str] = set()
        assigned: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported.add(alias.asname or alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    imported.add(alias.asname or alias.name)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    assigned |= self._assigned_names(target)
            elif isinstance(node, ast.AnnAssign):
                assigned |= self._assigned_names(node.target)
            elif isinstance(node, ast.For):
                assigned |= self._assigned_names(node.target)

        missing = self.REQUIRED_FUNCTIONS - defined
        for name in sorted(missing):
            errors.append(f"required_function_missing: {name}")

        available = defined | imported | assigned | set(dir(builtins))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id not in available:
                    errors.append(f"undefined_callable: {node.func.id}")
        dynamic_check = DynamicValueHardcodeDetector().detect(source, runtime_variables or [])
        if not dynamic_check.get("passed"):
            for finding in dynamic_check.get("findings", []):
                errors.append(f"hardcoded_runtime_value: {finding.get('variable')}={finding.get('value')}")

        if errors:
            return {"valid": False, "errors": sorted(set(errors))}

        try:
            name = f"runtime_module_validation_{path.stem}_{abs(hash(str(path)))}"
            spec = importlib.util.spec_from_file_location(name, str(path))
            if spec is None or spec.loader is None:
                return {"valid": False, "errors": ["module_spec_unavailable"]}
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            for fn_name in self.REQUIRED_FUNCTIONS:
                if not callable(getattr(module, fn_name, None)):
                    return {"valid": False, "errors": [f"function_not_callable: {fn_name}"]}
        except Exception as exc:
            return {"valid": False, "errors": [f"import_validation_failed: {exc}"]}

        return {"valid": True, "errors": []}

    def _assigned_names(self, target: ast.AST) -> set[str]:
        if isinstance(target, ast.Name):
            return {target.id}
        if isinstance(target, (ast.Tuple, ast.List)):
            out: set[str] = set()
            for item in target.elts:
                out |= self._assigned_names(item)
            return out
        return set()
