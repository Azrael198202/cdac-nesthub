from __future__ import annotations

import json
import tempfile
from pathlib import Path

from ai_core.approval.human_approval_gate import HumanApprovalGate
from ai_core.environment.docker_preflight import DockerPreflight
from ai_core.models.model_benchmark import RuntimeModelBenchmark
from ai_core.models.model_lifecycle import RuntimeModelLifecycle
from ai_core.models.model_route_registry import RuntimeModelRouteRegistry
from ai_core.security.repository_dependency_gate import RepositoryDependencyGate


def main() -> None:
    docker = DockerPreflight().check()
    assert "docker_available" in docker

    gate = HumanApprovalGate().request(operation="smoke_test", subject={"ok": True})
    assert gate["status"] == "approval_required"
    assert Path(gate["request_path"]).exists()

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "requirements.txt").write_text("requests==2.32.3\n", encoding="utf-8")
        dep = RepositoryDependencyGate().evaluate(root, approved=False)
        assert dep["status"] == "approval_required"
        assert dep["allowed_to_install"] is False

    reg = RuntimeModelRouteRegistry().register_after_benchmark(
        candidate={"model_id": "unit-test-model", "runtime": "unit"},
        benchmark={"passed": False, "model_id": "unit-test-model", "runtime": "unit"},
    )
    assert reg["status"] == "blocked"

    life = RuntimeModelLifecycle().process_candidate({
        "model_id": "unit-test-model",
        "runtime": "unit",
        "requires_human_review": True,
    })
    assert life["status"] == "approval_required"
    assert life["knowledge_saved"] is False

    print(json.dumps({
        "smoke_test_v55": "OK",
        "docker_preflight_status": docker["status"],
        "approval_path": gate["request_path"],
        "dependency_gate_status": dep["status"],
        "route_block_status": reg["status"],
        "lifecycle_status": life["status"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
