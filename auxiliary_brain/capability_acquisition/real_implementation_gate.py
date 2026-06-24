from __future__ import annotations

import ast
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Mapping


@dataclass(frozen=True)
class RealImplementationGateResult:
    passed: bool
    status: str
    reason: str
    checks: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _read_tool_source(tool_dir: str | Path) -> str:
    path = Path(tool_dir) / "tool.py"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _marker_present(source: str, marker: str) -> bool:
    if "|" in marker:
        return any(_marker_present(source, part) for part in marker.split("|"))
    return marker in source


def _constant_present(source: str, constant: str) -> bool:
    if not constant or len(str(constant)) < 2:
        return True
    return str(constant) in source


def _looks_echo_only(source: str) -> bool:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    run_funcs = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "run"]
    if not run_funcs:
        return False
    suspicious = 0
    for fn in run_funcs:
        for node in ast.walk(fn):
            if isinstance(node, ast.Return):
                text = ast.unparse(node.value) if hasattr(ast, "unparse") else ""
                if re.search(r"\b(payload|input|data)\b", text) and not re.search(r"\b(send|connect|write|execute|request|open)\b", text):
                    suspicious += 1
    call_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute):
                call_names.add(func.attr)
            elif isinstance(func, ast.Name):
                call_names.add(func.id)
    real_calls = {"connect", "send_message", "sendmail", "request", "urlopen", "open", "execute", "commit", "write"}
    return suspicious > 0 and not (call_names & real_calls)


def run_real_implementation_gate(tool_dir: str | Path, behavior_contract: Mapping[str, Any]) -> RealImplementationGateResult:
    source = _read_tool_source(tool_dir)
    checks: list[dict[str, Any]] = []
    if not source:
        return RealImplementationGateResult(False, "failed", "tool_source_missing", [])

    for marker in behavior_contract.get("required_markers", []) or []:
        passed = _marker_present(source, str(marker))
        checks.append({"name": "required_marker", "marker": marker, "passed": passed})
    for call in behavior_contract.get("required_calls", []) or []:
        passed = _marker_present(source, str(call))
        checks.append({"name": "required_call", "call": call, "passed": passed})
    for constant in behavior_contract.get("required_constants", []) or []:
        passed = _constant_present(source, str(constant))
        checks.append({"name": "required_constant", "constant": constant, "passed": passed})

    if behavior_contract.get("disallow_echo_only"):
        echo = _looks_echo_only(source)
        checks.append({"name": "not_echo_only", "passed": not echo})

    failed = [c for c in checks if not c.get("passed")]
    return RealImplementationGateResult(
        passed=not failed,
        status="passed" if not failed else "failed",
        reason="real_implementation_verified" if not failed else "real_implementation_contract_failed",
        checks=checks,
    )
