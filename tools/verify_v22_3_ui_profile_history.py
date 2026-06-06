from pathlib import Path
root = Path(__file__).resolve().parents[1]
agent = (root / "apps/web/agent_studio.html").read_text()
settings = (root / "apps/web/settings.html").read_text()
assert "Presentation profile" in settings
assert "settingsPresentationProfile" in settings
assert "executionHistory" in agent
assert "startExecutionRecord" in agent
assert "renderExecutionHistoryInto" in agent
assert "Progress" in agent and "Workflow" in agent and "Results" in agent and "Traces" in agent
print("v22.3 UI profile and execution history verification passed")
