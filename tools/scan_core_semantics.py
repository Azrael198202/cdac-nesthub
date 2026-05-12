from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "ai_core"
POLICY_PATH = ROOT / "runtime" / "configs" / "policies" / "semantic_boundary.yaml"

sys.path.insert(0, str(ROOT))

from ai_core.validation.semantic_boundary_scanner import SemanticBoundaryScanner  # noqa: E402


def load_policy(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "enabled": False,
            "rules": [],
            "message": (
                "No runtime semantic boundary policy found. "
                "Create runtime/configs/policies/semantic_boundary.yaml to enable scanning."
            ),
        }

    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def main() -> int:
    policy = load_policy(POLICY_PATH)

    if not policy.get("enabled", False):
        print(policy.get("message", "Semantic boundary scan disabled."))
        return 0

    rules = policy.get("rules", [])
    if not isinstance(rules, list):
        print("Invalid semantic boundary policy: rules must be a list.")
        return 2

    scanner = SemanticBoundaryScanner()
    findings = scanner.scan_path(target_path=TARGET, rules=rules, root_path=ROOT)

    output_format = policy.get("output", "text")
    if output_format == "json":
        print(json.dumps([finding.__dict__ for finding in findings], ensure_ascii=False, indent=2))
    else:
        if findings:
            print("Semantic boundary findings:")
            for finding in findings:
                print(
                    f"- {finding.path}:{finding.line_number} "
                    f"[{finding.rule_id}] pattern={finding.pattern!r} :: {finding.line_preview}"
                )
        else:
            print("OK: no semantic boundary findings.")

    return 1 if findings and policy.get("fail_on_findings", True) else 0


if __name__ == "__main__":
    raise SystemExit(main())
