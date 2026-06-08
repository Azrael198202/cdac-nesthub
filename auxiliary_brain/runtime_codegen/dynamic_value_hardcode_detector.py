from __future__ import annotations

import ast
import re
from typing import Any


class DynamicValueHardcodeDetector:
    """Detect hardcoded runtime values in generated Python source.

    Generated adapters/modules should be reusable. Values derived from the
    current user request or workflow must be read from payload, not embedded in
    code literals. This detector is domain-neutral and checks the runtime
    variables attached to the generation request/manifest.
    """

    def detect(self, source: str, runtime_variables: list[dict[str, Any]] | dict[str, Any] | None) -> dict[str, Any]:
        variables = self._normalize(runtime_variables)
        if not variables:
            return {"passed": True, "findings": [], "checked_runtime_variables": []}
        string_literals = self._string_literals(source)
        findings: list[dict[str, Any]] = []
        for variable in variables:
            name = variable.get("name")
            aliases = [str(a) for a in variable.get("aliases") or [] if self._should_check_alias(str(a))]
            for alias in aliases:
                for literal in string_literals:
                    if self._contains_hardcoded_value(literal, alias):
                        findings.append({
                            "variable": name,
                            "value": alias,
                            "literal_excerpt": literal[:240],
                            "reason": "runtime_value_hardcoded_in_python_literal",
                        })
                        break
        return {
            "passed": not findings,
            "findings": findings[:50],
            "checked_runtime_variables": [{"name": v.get("name"), "alias_count": len(v.get("aliases") or [])} for v in variables],
        }

    def _normalize(self, value: list[dict[str, Any]] | dict[str, Any] | None) -> list[dict[str, Any]]:
        if isinstance(value, dict):
            raw = value.get("runtime_variables") if isinstance(value.get("runtime_variables"), list) else []
            return [x for x in raw if isinstance(x, dict)]
        if isinstance(value, list):
            return [x for x in value if isinstance(x, dict)]
        return []

    def _string_literals(self, source: str) -> list[str]:
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return []
        out: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                out.append(node.value)
            elif isinstance(node, ast.JoinedStr):
                static_parts = []
                for item in node.values:
                    if isinstance(item, ast.Constant) and isinstance(item.value, str):
                        static_parts.append(item.value)
                if static_parts:
                    out.append("".join(static_parts))
        return out

    def _should_check_alias(self, alias: str) -> bool:
        alias = alias.strip()
        if len(alias) < 2:
            return False
        if alias.lower() in {"true", "false", "none", "null", "get", "post", "json", "html"}:
            return False
        # Single small numbers are too noisy unless date-like aliases are longer.
        if re.fullmatch(r"\d{1,2}", alias):
            return False
        return True

    def _contains_hardcoded_value(self, literal: str, alias: str) -> bool:
        if not literal or not alias:
            return False
        lit = literal.lower()
        val = alias.lower()
        if val not in lit:
            return False
        # If the literal is a key name or accesses payload, allow it.
        allowed_patterns = [
            f"payload.get('{val}')",
            f'payload.get("{val}")',
            f"['{val}']",
            f'["{val}"]',
        ]
        if any(p in lit for p in allowed_patterns):
            return False
        return True
