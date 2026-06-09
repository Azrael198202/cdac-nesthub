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

        unsafe_default_calls = self._unsafe_method_calls_on_incompatible_get_defaults(tree)
        errors.extend(unsafe_default_calls)

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


    def _unsafe_method_calls_on_incompatible_get_defaults(self, tree: ast.AST) -> list[str]:
        """Detect generic type hazards such as value = obj.get(name, []); value.split(...).

        This is structural Python validation, not capability logic. It prevents
        registration of generated code that assigns an incompatible default and
        later calls a method that the default type cannot support.
        """
        assigned_defaults: dict[str, str] = {}
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
                continue
            target = node.targets[0].id
            value = node.value
            if not (isinstance(value, ast.Call) and isinstance(value.func, ast.Attribute) and value.func.attr == "get"):
                continue
            default_node = None
            if len(value.args) >= 2:
                default_node = value.args[1]
            for keyword in value.keywords or []:
                if keyword.arg == "default":
                    default_node = keyword.value
            kind = self._literal_container_kind(default_node)
            if kind:
                assigned_defaults[target] = kind
        errors: list[str] = []
        incompatible = {
            "split": {"list", "dict", "tuple", "set", "bool", "number", "none"},
            "items": {"list", "tuple", "set", "str", "bool", "number", "none"},
            "append": {"dict", "tuple", "set", "str", "bool", "number", "none"},
            "extend": {"dict", "tuple", "set", "str", "bool", "number", "none"},
        }
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name)):
                continue
            name = node.func.value.id
            method = node.func.attr
            default_kind = assigned_defaults.get(name)
            if default_kind and default_kind in incompatible.get(method, set()):
                errors.append(f"unsafe_method_call_on_incompatible_default: variable '{name}' has default {default_kind} but method '{method}' is called")
        return errors

    def _literal_container_kind(self, node: ast.AST | None) -> str:
        if node is None:
            return ""
        if isinstance(node, ast.List):
            return "list"
        if isinstance(node, ast.Dict):
            return "dict"
        if isinstance(node, ast.Tuple):
            return "tuple"
        if isinstance(node, ast.Set):
            return "set"
        if isinstance(node, ast.Constant):
            if node.value is None:
                return "none"
            if isinstance(node.value, str):
                return "str"
            if isinstance(node.value, bool):
                return "bool"
            if isinstance(node.value, (int, float)):
                return "number"
        return ""

    def _assigned_names(self, target: ast.AST) -> set[str]:
        names: set[str] = set()
        if isinstance(target, ast.Name):
            names.add(target.id)
        elif isinstance(target, (ast.Tuple, ast.List)):
            for element in target.elts:
                names.update(self._assigned_names(element))
        return names
