from pathlib import Path

from auxiliary_brain.capability_acquisition.code_generator import RuntimeBlueprintArtifactGenerator
from auxiliary_brain.runtime.capability.acquisition_gate import RuntimeCapabilityAcquisitionGate


def test_generator_adds_generic_payload_entrypoint_without_domain_logic():
    source = """def helper(input, connection, secrets):\n    return {\"status\": \"success\", \"data\": input}\n"""
    generator = RuntimeBlueprintArtifactGenerator()
    patched = generator._ensure_payload_entrypoint(source, function_name="run")
    namespace = {}
    exec(patched, namespace)
    result = namespace["run"]({"input": {"x": 1}, "connection": {}, "secrets": {}})
    assert result["status"] == "success"
    assert result["data"] == {"x": 1}


def test_registration_gate_accepts_static_only_when_validation_passed():
    gate = RuntimeCapabilityAcquisitionGate()
    decision = gate.evaluate_before_registration(
        pre_validation_decision={"passed": True, "status": "pre_validation_passed"},
        validation={"passed": True, "isolation_level": "static_only", "checks": []},
        verification_run={"passed": True, "status": "static_validation_only"},
        sandbox_result={"status": "completed", "isolation_level": "static_only"},
    )
    assert decision["safe_to_register"] is True
    assert decision["status"] == "registration_gate_passed"
