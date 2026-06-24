from __future__ import annotations

import argparse
import shutil
from pathlib import Path


def remove_path(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(description="Clean runtime-generated artifacts that may contain stale generated tools.")
    parser.add_argument("--runtime-root", default="runtime", help="Runtime root directory. Default: runtime")
    parser.add_argument("--all", action="store_true", help="Remove tools, tests, task artifacts, deliveries, and gap resolutions.")
    args = parser.parse_args()

    runtime_root = Path(args.runtime_root)
    generated = runtime_root / "generated"
    targets = [
        generated / "tools",
        generated / "tests",
        generated / "capability_gap_resolutions",
        generated / "self_repair",
        generated / "capability_replay",
    ]
    if args.all:
        targets.extend([
            generated / "tasks",
            runtime_root / "deliveries",
            runtime_root / "cache" / "tool_modules",
        ])

    for target in targets:
        if target.exists():
            remove_path(target)
            print(f"removed: {target}")
        target.mkdir(parents=True, exist_ok=True)
        print(f"ready: {target}")

    # Python bytecode can keep old dynamic modules reachable in local dev runs.
    for pycache in Path(".").rglob("__pycache__"):
        try:
            shutil.rmtree(pycache)
            print(f"removed: {pycache}")
        except Exception:
            pass
    print("generated_runtime_clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
