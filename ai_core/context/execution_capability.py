from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ExecutionCapability:
    """Generic capability detected from a reusable execution asset.

    The resolver deliberately avoids task-specific keywords. It ranks objective
    evidence only: existing executable files, callable contracts, explicit
    generation contracts, and generic runtime delegation.
    """

    mode: str
    confidence: float
    reason: str
    artifact_paths: list[str] = field(default_factory=list)
    callable_name: str | None = None
    parameter_schema: list[dict[str, Any]] = field(default_factory=list)
    requires_model: bool = False
    requires_planning: bool = False


class ExecutionCapabilityResolver:
    """Resolve how a saved asset should be reused.

    Resolution is evidence-first:
    1. verified executable artifact
    2. callable function inside verified artifact
    3. explicit model-generation contract with no executable artifact
    4. generic runtime delegation fallback

    This prevents one-off routing rules from leaking into the core runtime.
    """

    EXECUTABLE_SUFFIXES = {".py"}

    def resolve(self, asset: dict[str, Any], provided_inputs: dict[str, Any] | None = None) -> ExecutionCapability:
        paths = self._existing_executable_paths(asset.get("artifact_paths") or [])
        provided = provided_inputs or {}
        if paths:
            callable_name = self._select_callable(paths[0], provided)
            schema = asset.get("parameter_schema") if isinstance(asset.get("parameter_schema"), list) else []
            return ExecutionCapability(
                mode="executable_artifact",
                confidence=0.95 if callable_name else 0.9,
                reason="verified_executable_artifact",
                artifact_paths=[str(p) for p in paths],
                callable_name=callable_name,
                parameter_schema=schema,
                requires_model=False,
                requires_planning=False,
            )
        explicit_mode = str(asset.get("execution_mode") or "").strip()
        if explicit_mode == "llm_generation":
            return ExecutionCapability(
                mode="model_generation",
                confidence=0.75,
                reason="explicit_model_generation_contract",
                parameter_schema=asset.get("parameter_schema") if isinstance(asset.get("parameter_schema"), list) else [],
                requires_model=True,
                requires_planning=False,
            )
        return ExecutionCapability(
            mode="runtime_delegation",
            confidence=0.4,
            reason="no_direct_reuse_capability_detected",
            parameter_schema=asset.get("parameter_schema") if isinstance(asset.get("parameter_schema"), list) else [],
            requires_model=False,
            requires_planning=False,
        )

    def _existing_executable_paths(self, raw_paths: list[Any]) -> list[Path]:
        paths: list[Path] = []
        for raw in raw_paths:
            if not isinstance(raw, str) or not raw.strip():
                continue
            path = Path(raw)
            if path.exists() and path.is_file() and path.suffix in self.EXECUTABLE_SUFFIXES:
                paths.append(path)
        return paths

    def _select_callable(self, path: Path, provided_inputs: dict[str, Any]) -> str | None:
        functions = self.public_functions(path)
        if not functions:
            return None
        input_keys = {str(k) for k in provided_inputs.keys()}
        for fn in functions:
            args = set(fn.get("args") or [])
            if args and args.issubset(input_keys):
                return str(fn.get("name") or "")
        if len(functions) == 1 and (functions[0].get("args") or []):
            return str(functions[0].get("name") or "")
        return None

    def public_functions(self, path: Path) -> list[dict[str, Any]]:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except Exception:
            return []
        functions: list[dict[str, Any]] = []
        for node in tree.body:
            if not isinstance(node, ast.FunctionDef) or node.name.startswith("_"):
                continue
            args = [a.arg for a in node.args.args if a.arg not in {"self", "cls"}]
            defaults = args[len(args) - len(node.args.defaults):] if node.args.defaults else []
            annotations: dict[str, str] = {}
            for a in node.args.args:
                if a.annotation is not None:
                    annotations[a.arg] = ast.unparse(a.annotation) if hasattr(ast, "unparse") else ""
            functions.append({"name": node.name, "args": args, "defaults": defaults, "annotations": annotations})
        return functions
