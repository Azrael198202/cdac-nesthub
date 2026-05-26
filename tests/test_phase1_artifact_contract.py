from __future__ import annotations

from pathlib import Path
import shutil

from ai_core.config.paths import PROJECT_ROOT
from ai_core.artifacts.uploaded_artifact_contract import UploadedArtifactContractBuilder


def _contract_for(tmp_path: Path, source: str, known: dict | None = None) -> dict:
    work_dir = PROJECT_ROOT / "runtime" / "temp" / "pytest_artifact_contract"
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    artifact = work_dir / "artifact.py"
    artifact.write_text(source, encoding="utf-8")
    builder = UploadedArtifactContractBuilder()
    state = {"run_id": "test_run", "runtime_inputs": known or {}}
    step = {"uploaded_artifacts": [{"path": str(artifact), "name": artifact.name}], "parameters": {"known": known or {}}}
    try:
        return builder.build_contract(state=state, step=step, step_id="step_1")
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def test_no_argument_python_artifact_requires_no_parameters(tmp_path: Path) -> None:
    contract = _contract_for(tmp_path, "def run():\n    return {'answer_material': 'ok'}\n")
    assert contract["status"] == "prepared"
    assert contract["required_parameters"] == []
    assert contract["missing_parameter_fields"] == []
    assert contract["approved_in_preparation"] is True


def test_required_python_argument_requests_missing_parameter(tmp_path: Path) -> None:
    contract = _contract_for(tmp_path, "def run(value: str):\n    return {'answer_material': value}\n")
    assert contract["status"] == "missing_parameters"
    assert contract["required_parameters"] == ["value"]
    assert [field["name"] for field in contract["missing_parameter_fields"]] == ["value"]
    assert contract["approved_in_preparation"] is False


def test_optional_python_argument_records_default_without_blocking(tmp_path: Path) -> None:
    contract = _contract_for(tmp_path, "def run(value: str = 'default'):\n    return {'answer_material': value}\n")
    assert contract["status"] == "prepared"
    assert contract["required_parameters"] == []
    assert contract["optional_parameters"] == ["value"]
    assert contract["default_parameter_values"] == {"value": "default"}
    assert contract["missing_parameter_fields"] == []


def test_single_payload_style_does_not_require_payload_field(tmp_path: Path) -> None:
    contract = _contract_for(tmp_path, "def run(payload):\n    return payload\n")
    assert contract["status"] == "prepared"
    assert contract["required_parameters"] == []
    assert contract["selected_artifact"]["execution_entrypoint"].get("payload_style") == "single_object"


def test_known_value_satisfies_required_argument(tmp_path: Path) -> None:
    contract = _contract_for(tmp_path, "def run(value: str):\n    return {'answer_material': value}\n", known={"value": "real"})
    assert contract["status"] == "prepared"
    assert contract["missing_parameter_fields"] == []
    assert contract["known_parameter_values"] == {"value": "real"}


def test_placeholder_value_does_not_satisfy_required_argument(tmp_path: Path) -> None:
    contract = _contract_for(tmp_path, "def run(value: str):\n    return {'answer_material': value}\n", known={"value": "missing"})
    assert contract["status"] == "missing_parameters"
    assert [field["name"] for field in contract["missing_parameter_fields"]] == ["value"]


def test_keyword_only_argument_contract(tmp_path: Path) -> None:
    contract = _contract_for(tmp_path, "def run(*, value: int, label: str = 'x'):\n    return {'answer_material': value}\n")
    assert contract["required_parameters"] == ["value"]
    assert contract["optional_parameters"] == ["label"]
    assert contract["default_parameter_values"] == {"label": "x"}
