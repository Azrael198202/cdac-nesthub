from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai_core.architecture import RuntimeLayerContractRegistry


def test_runtime_layer_contracts_are_complete():
    registry = RuntimeLayerContractRegistry()
    report = registry.validate()
    assert report["ok"], report
    layers = [item.layer_id for item in registry.ordered()]
    assert layers == [
        "perception",
        "input_parsing",
        "intent_recognition",
        "requirement_completion",
        "context_awareness",
        "workflow_planning",
        "pre_execution_validation",
        "execution",
        "result_verification",
        "feedback_repair",
        "final_synthesis",
    ]


def test_late_layers_do_not_replan_or_reselect_execution():
    registry = RuntimeLayerContractRegistry()
    for layer_id in ["execution", "result_verification", "final_synthesis"]:
        contract = registry.by_id(layer_id)
        assert contract is not None
        forbidden = set(contract.forbidden_decisions)
        assert "intent_reclassification" in forbidden or layer_id == "final_synthesis"
        assert "unplanned_fallback" in forbidden or layer_id != "result_verification"
        assert "new_search" in forbidden or layer_id == "execution"


def test_core_source_has_no_forbidden_business_terms():
    terms = [
        "weather", "forecast", "gmail", "smtp", "shopify", "attendance",
        "出勤", "退勤", "打卡", "booking", "reservation",
    ]
    source_roots = [ROOT / "ai_core", ROOT / "auxiliary_brain", ROOT / "perception_brain", ROOT / "verification_brain", ROOT / "repair_brain", ROOT / "presentation_brain", ROOT / "memory_brain"]
    hits = []
    for source_root in source_roots:
        for path in source_root.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore").casefold()
            for term in terms:
                if re.search(re.escape(term.casefold()), text):
                    hits.append(f"{path.relative_to(ROOT)}:{term}")
    assert not hits, hits[:20]


if __name__ == "__main__":
    test_runtime_layer_contracts_are_complete()
    test_late_layers_do_not_replan_or_reselect_execution()
    test_core_source_has_no_forbidden_business_terms()
    print("v24.1 runtime layer contracts verified")
