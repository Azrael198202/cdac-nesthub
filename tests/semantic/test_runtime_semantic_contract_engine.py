from ai_core.runtime.semantic import RuntimeSemanticContractEngine


def test_generic_coordinate_values_are_not_user_facing_observations():
    facts = [
        {
            "kind": "observed_value",
            "label": "value",
            "value": "33.61",
            "unit": "°",
            "context": "located at 33.61° N 130.42° E",
            "confidence": 0.9,
        },
        {
            "kind": "observed_value",
            "label": "value",
            "value": "130.42",
            "unit": "°",
            "context": "located at 33.61° N 130.42° E",
            "confidence": 0.9,
        },
    ]
    verified = RuntimeSemanticContractEngine().verify_facts(facts, state={})
    assert verified == []


def test_generic_bounded_ratio_rejects_out_of_range_value():
    facts = [
        {
            "kind": "observed_value",
            "label": "ratio",
            "value": "130.42",
            "unit": "%",
            "context": "ratio: 130.42%",
            "confidence": 0.9,
        }
    ]
    verified = RuntimeSemanticContractEngine().verify_facts(facts, state={})
    assert verified == []


def test_generic_measurement_can_be_verified_without_domain_terms():
    facts = [
        {
            "kind": "observed_value",
            "label": "value",
            "value": "25.5",
            "unit": "°C",
            "context": "observed value 25.5 °C",
            "confidence": 0.9,
        }
    ]
    verified = RuntimeSemanticContractEngine().verify_facts(facts, state={})
    assert len(verified) == 1
    assert verified[0]["verified"] is True
