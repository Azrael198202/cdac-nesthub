from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ai_core.tools.runtime_registered_tool_service import RuntimeRegisteredToolService


def main() -> None:
    service = RuntimeRegisteredToolService()
    schema = {
        "type": "object",
        "properties": {
            "flag_a": {"type": "boolean"},
            "flag_b": {"type": "boolean"},
            "count": {"type": "integer"},
            "ratio": {"type": "number"},
            "items": {"type": "array", "items": {"type": "string"}},
            "nested": {"type": "object", "properties": {"enabled": {"type": "boolean"}}},
        },
    }
    value = {
        "flag_a": "false",
        "flag_b": "true",
        "count": "587",
        "ratio": "1.5",
        "items": '["a", "b"]',
        "nested": {"enabled": "0"},
    }
    out = service._coerce_by_schema(value, schema)  # intentional boundary test for generic coercion
    assert out["flag_a"] is False, out
    assert out["flag_b"] is True, out
    assert out["count"] == 587, out
    assert out["ratio"] == 1.5, out
    assert out["items"] == ["a", "b"], out
    assert out["nested"]["enabled"] is False, out
    print("runtime value type coercion verified")


if __name__ == "__main__":
    main()
