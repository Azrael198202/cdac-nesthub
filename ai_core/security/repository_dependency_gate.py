from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ai_core.approval.human_approval_gate import HumanApprovalGate
from ai_core.security.dependency_scanner import DependencyScanner


@dataclass
class RepositoryDependencyGateResult:
    status: str
    repository_path: str
    dependency_scan: dict[str, Any]
    approval: dict[str, Any] | None
    allowed_to_install: bool
    reason: str


class RepositoryDependencyGate:
    """Require explicit approval before installing dependencies from external repositories."""

    def __init__(self) -> None:
        self.scanner = DependencyScanner()
        self.approval = HumanApprovalGate()

    def evaluate(self, repository_path: str | Path, *, approved: bool = False) -> dict[str, Any]:
        path = Path(repository_path)
        scan = self.scanner.scan_path(path)
        if not path.exists():
            return asdict(RepositoryDependencyGateResult("missing", str(path), scan, None, False, "Repository path does not exist."))
        risks: list[dict[str, Any]] = []
        for finding in scan.get("findings", []) if isinstance(scan.get("findings"), list) else []:
            risks.append({"level": finding.get("severity", "review"), "message": finding.get("message"), "package": finding.get("package")})
        if not approved:
            approval = self.approval.request(
                operation="external_repository_dependency_install",
                subject={"repository_path": str(path), "dependency_scan": scan},
                risks=risks or [{"level": "review", "message": "External repository dependencies require approval before installation."}],
            )
            return asdict(RepositoryDependencyGateResult("approval_required", str(path), scan, approval, False, "Dependency installation requires human approval."))
        if not bool(scan.get("safe_to_install")):
            return asdict(RepositoryDependencyGateResult("blocked", str(path), scan, None, False, "Dependency scan did not pass."))
        return asdict(RepositoryDependencyGateResult("approved", str(path), scan, None, True, "Dependencies may be installed in sandbox."))
