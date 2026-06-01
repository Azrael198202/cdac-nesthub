from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ai_core.capabilities.runtime_capability_gap_implementer import RuntimeCapabilityGapImplementer


def main() -> None:
    impl = RuntimeCapabilityGapImplementer()
    impl._load_runtime_generated_default_planner = lambda: (lambda payload: {
        "status": "planned",
        "confidence_score": 0.91,
        "needs_external_evidence": False,
        "blueprint": {
            "capability_category": "adapter",
            "requires_connection": True,
            "requires_secret": True,
            "required_inputs": ["field_1"],
            "required_connection_fields": ["field_2"],
            "required_secret_fields": ["field_3"],
        },
    })
    result = impl.implement_if_requested(
        user_input="Acquire runtime capability:\nNeutral Adapter.\nCapability id must be: verification_blueprint_adapter",
        evidence={"urls": []},
        run_id="verify_blueprint_capability_pipeline",
        allow_implementation=True,
    )
    assert result["status"] == "implemented_tested_registered", result
    stages = [x.get("stage") for x in result.get("pipeline", [])]
    assert "BlueprintPlanner" in stages, stages
    assert "ArtifactGenerator" in stages, stages
    assert any(x.get("status") == "blueprint_materialized" for x in result.get("pipeline", [])), result.get("pipeline")
    print("verify_blueprint_capability_pipeline: OK")

if __name__ == "__main__":
    main()
