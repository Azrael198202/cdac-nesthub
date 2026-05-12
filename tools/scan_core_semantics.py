from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "ai_core"

# This scanner is intentionally conservative.
# Project owners can add terms based on architecture rules.
SUSPICIOUS_PATTERNS = [
    r"出勤",
    r"退勤",
    r"打卡",
    r"社内",
    r"flight",
    r"weather",
    r"booking",
    r"reservation",
    r"attendance",
    r"playwright",
    r"browser",
    r"login",
    r"password",
    r"weekday",
    r"forecast",
    r"schedule",
    r"\d\{1,2\}",
    r"点時",
]


def main() -> int:
    problems = []
    for path in TARGET.rglob("*.py"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        for pattern in SUSPICIOUS_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                problems.append((path.relative_to(ROOT), pattern))

    if problems:
        print("Suspicious semantic/domain patterns found in ai_core:")
        for path, pattern in problems:
            print(f"- {path}: {pattern}")
        return 1

    print("OK: no suspicious semantic/domain patterns found in ai_core.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
