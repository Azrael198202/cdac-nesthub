from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "apps" / "web" / "agent_studio.html"


def require(text: str, needle: str) -> None:
    if needle not in text:
        raise AssertionError(f"missing expected UI marker: {needle}")


def main() -> None:
    text = HTML.read_text(encoding="utf-8")
    require(text, "Model mode")
    require(text, "local_only")
    require(text, "api_only")
    require(text, "hybrid")
    require(text, "executionDashboard")
    require(text, "renderExecutionDashboard")
    require(text, "Runtime Center")
    require(text, "selectRightTab('workflow')")
    require(text, "selectRightTab('results')")
    require(text, "selectRightTab('traces')")
    require(text, "Workflow")
    require(text, "Results")
    require(text, "Traces")
    require(text, "latestModelDecision")
    print("v22.3 runtime execution center UI verification passed")


if __name__ == "__main__":
    main()
