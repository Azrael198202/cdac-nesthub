from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
EXPECTED_STAGES = [
    "input_parsing",
    "intent_recognition",
    "requirement_completion",
    "context_awareness",
    "workflow_planning",
    "agent_action_planning",
    "execution_preparation",
    "pre_execution_validation",
    "execution",
    "result_verification",
    "feedback_repair",
    "final_synthesis",
]
FORBIDDEN_RUNTIME_PATHS = [
    "runtime/generated",
    "runtime/sessions",
    "runtime/traces",
    "runtime/checkpoints",
    "runtime/cache",
    "runtime/results",
    "runtime/temp",
    "runtime/configs/secrets",
]
DOMAIN_TERMS: list[str] = []
SKIP_DIRS = {".git", "__pycache__", ".venv", "venv", "node_modules"}


def iter_source_files() -> list[Path]:
    files: list[Path] = []
    for p in ROOT.rglob("*"):
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        if p.is_file() and p.suffix.lower() in {".py", ".json", ".yaml", ".yml", ".md", ".txt", ".html"}:
            files.append(p)
    return files


def check_runtime_outputs_absent() -> list[str]:
    errors: list[str] = []
    for rel in FORBIDDEN_RUNTIME_PATHS:
        p = ROOT / rel
        if p.exists() and any(p.iterdir()):
            errors.append(f"runtime output path is not empty: {rel}")
    return errors


def check_stage_contract() -> list[str]:
    errors: list[str] = []
    from ai_core.pipeline.stage_contract import PipelineStageContract

    found = PipelineStageContract().ordered_stage_ids()
    if found != EXPECTED_STAGES:
        errors.append(f"stage order mismatch: {found}")
    return errors


def check_domain_terms() -> list[str]:
    errors: list[str] = []
    if not DOMAIN_TERMS:
        return errors
    pattern = re.compile(r"(?<![A-Za-z0-9_])(?:" + "|".join(re.escape(t) for t in DOMAIN_TERMS) + r")(?![A-Za-z0-9_])", re.IGNORECASE)
    for p in iter_source_files():
        rel = p.relative_to(ROOT).as_posix()
        if rel == "tools/validate_source_package.py":
            continue
        text = p.read_text(encoding="utf-8", errors="ignore")
        for m in pattern.finditer(text):
            line = text.count("\n", 0, m.start()) + 1
            errors.append(f"domain term '{m.group(0)}' in {rel}:{line}")
    return errors


def check_python_syntax() -> list[str]:
    errors: list[str] = []
    for p in ROOT.rglob("*.py"):
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        try:
            ast.parse(p.read_text(encoding="utf-8"), filename=str(p))
        except SyntaxError as exc:
            errors.append(f"syntax error: {p.relative_to(ROOT)}:{exc.lineno}: {exc.msg}")
    return errors


def main() -> int:
    checks = {
        "python_syntax": check_python_syntax(),
        "stage_contract": check_stage_contract(),
        "runtime_outputs_absent": check_runtime_outputs_absent(),
        "domain_terms_absent": check_domain_terms(),
    }
    ok = all(not v for v in checks.values())
    print(json.dumps({"ok": ok, "checks": checks}, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
