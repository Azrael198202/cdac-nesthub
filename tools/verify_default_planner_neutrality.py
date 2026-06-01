from __future__ import annotations

from pathlib import Path


FORBIDDEN_MARKERS = [
    "smtp",
    "mail",
    "email",
    "smtplib",
    "sendgrid",
    "weather",
    "forecast",
    "flight",
    "booking",
    "reservation",
    "attendance",
]


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    path = root / "runtime_assets" / "seeds" / "capability_planners" / "default_capability_planner.py"
    text = path.read_text(encoding="utf-8").casefold()
    found = [marker for marker in FORBIDDEN_MARKERS if marker in text]
    assert not found, {"path": str(path), "forbidden_markers": found}
    print("default capability planner neutrality verified")


if __name__ == "__main__":
    main()
