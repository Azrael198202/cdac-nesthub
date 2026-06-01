from __future__ import annotations

import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIGS_DIR = PROJECT_ROOT / "configs"
RUNTIME_GENERATED = PROJECT_ROOT / "runtime" / "generated"
RUNTIME_ASSETS = PROJECT_ROOT / "runtime_assets"

# Terms that represent concrete runtime capabilities and should not be stored
# as static acquisition templates under configs/.
CONCRETE_TEMPLATE_FILES = {
    "runtime_capability_templates.json",
    "runtime_primitive_tool_templates.seed.json",
}


def _template_count(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        data = json.loads(path.read_text(encoding="utf-8") or "{}")
    except Exception:
        return -1
    templates = data.get("templates") if isinstance(data, dict) else data
    return len(templates) if isinstance(templates, list) else 0


def main() -> None:
    failures: list[str] = []
    for name in sorted(CONCRETE_TEMPLATE_FILES):
        path = CONFIGS_DIR / name
        count = _template_count(path)
        if count != 0:
            failures.append(f"{path} contains {count} concrete templates; expected 0")
    runtime_template_count = 0
    for path in (RUNTIME_GENERATED / "capability_templates").glob("*.json"):
        runtime_template_count += max(_template_count(path), 0)
    runtime_template_count += max(_template_count(RUNTIME_GENERATED / "system_topology" / "runtime_capability_templates.json"), 0)
    runtime_planner_count = len(list((RUNTIME_ASSETS / "seeds" / "capability_planners").glob("*.py")))
    # A clean source bundle may intentionally contain no materialized templates.
    # In that case the packaged runtime asset planner seed is the valid boundary artifact;
    # templates are generated under runtime/generated only during acquisition.
    if runtime_template_count <= 0 and runtime_planner_count <= 0:
        failures.append("No runtime-owned capability templates or planner seeds were found under runtime/generated or runtime_assets")
    if failures:
        raise SystemExit("\n".join(failures))
    print("runtime config boundary verified")


if __name__ == "__main__":
    main()
