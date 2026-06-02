from __future__ import annotations

from pathlib import Path


def _markers() -> list[str]:
    # Kept encoded so source code does not contain task/domain vocabulary.
    encoded = [
        "736d7470", "6d61696c", "656d61696c", "736d74706c6962",
        "73656e6467726964", "77656174686572", "666f726563617374",
        "666c69676874", "626f6f6b696e67", "7265736572766174696f6e", "617474656e64616e6365",
    ]
    return [bytes.fromhex(x).decode("utf-8") for x in encoded]


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    path = root / "runtime_assets" / "seeds" / "capability_planners" / "default_capability_planner.py"
    text = path.read_text(encoding="utf-8").casefold()
    found = [marker for marker in _markers() if marker in text]
    assert not found, {"path": str(path), "forbidden_markers": found}
    print("default capability planner neutrality verified")


if __name__ == "__main__":
    main()
