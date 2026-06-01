from __future__ import annotations

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
DEFAULT = "qwen3.5:2b-instruct"
FOUR = "qwen3.5:4b-instruct"


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    policy = json.loads((ROOT / "configs" / "model_stage_policy.seed.json").read_text(encoding="utf-8"))
    catalog = policy.get("model_catalog", {})
    assert_true(DEFAULT in catalog, "missing Qwen3.5 2B model catalog entry")
    assert_true(FOUR in catalog, "missing Qwen3.5 4B model catalog entry")
    assert_true(policy["stages"]["input_parsing"]["default"] == DEFAULT, "input_parsing default must be Qwen3.5 2B")
    assert_true(policy["stages"]["simple_intent"]["default"] == DEFAULT, "simple_intent default must be Qwen3.5 2B")
    assert_true(policy["stages"]["workflow_planning"]["default"] in {DEFAULT, FOUR}, "workflow_planning must use Qwen3.5 local models first")

    providers = yaml.safe_load((ROOT / "runtime" / "configs" / "models" / "providers.yaml").read_text(encoding="utf-8"))
    ollama = providers["providers"]["ollama"]
    assert_true(ollama["model"] == DEFAULT, "ollama default model must be Qwen3.5 2B")
    assert_true(DEFAULT in ollama.get("fallback_models", []), "ollama fallback must include Qwen3.5 2B")
    assert_true(FOUR in ollama.get("fallback_models", []), "ollama fallback must include Qwen3.5 4B")
    assert_true(ollama.get("provider_models", {}).get(DEFAULT) == DEFAULT, "ollama provider model mapping missing Qwen3.5 2B")
    assert_true(ollama.get("provider_models", {}).get(FOUR) == FOUR, "ollama provider model mapping missing Qwen3.5 4B")

    user_model_selection = (ROOT / "ai_core" / "runtime" / "modeling" / "user_model_selection.py").read_text(encoding="utf-8")
    assert_true(DEFAULT in user_model_selection, "user model selection defaults must include Qwen3.5 2B")
    planner = (ROOT / "runtime_assets" / "seeds" / "capability_planners" / "default_capability_planner.py").read_text(encoding="utf-8")
    assert_true(DEFAULT in planner, "default capability planner must default to Qwen3.5 2B")

    index = (ROOT / "apps" / "web" / "index.html").read_text(encoding="utf-8")
    studio = (ROOT / "apps" / "web" / "agent_studio.html").read_text(encoding="utf-8")
    assert_true(DEFAULT in index, "web console must expose Qwen3.5 2B")
    assert_true(FOUR in index, "web console must expose Qwen3.5 4B")
    assert_true(DEFAULT in studio, "Agent Studio must default local selection to Qwen3.5 2B")
    print("Qwen3.5 local defaults verified")


if __name__ == "__main__":
    main()
