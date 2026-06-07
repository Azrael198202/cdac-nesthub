from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from ai_core.approval.human_approval_gate import HumanApprovalGate
from ai_core.config.paths import RUNTIME_TRACES
from ai_core.knowledge.knowledge_service import KnowledgeService
from ai_core.models.model_benchmark import RuntimeModelBenchmark
from ai_core.models.model_downloader import RuntimeModelDownloader
from ai_core.models.model_route_registry import RuntimeModelRouteRegistry


@dataclass
class ModelLifecycleResult:
    status: str
    candidate: dict[str, Any]
    approval: dict[str, Any] | None
    download: dict[str, Any] | None
    benchmark: dict[str, Any] | None
    registration: dict[str, Any] | None
    knowledge_saved: bool
    report_path: str
    reason: str


class RuntimeModelLifecycle:
    """Orchestrate model approval, download, benchmark, route registration, and knowledge recording."""

    def __init__(self) -> None:
        self.approval_gate = HumanApprovalGate()
        self.downloader = RuntimeModelDownloader()
        self.benchmark = RuntimeModelBenchmark()
        self.routes = RuntimeModelRouteRegistry()
        self.knowledge = KnowledgeService()
        self.trace_root = RUNTIME_TRACES / "model_lifecycle"
        self.trace_root.mkdir(parents=True, exist_ok=True)

    def process_candidate(self, candidate: dict[str, Any], *, route: str = "runtime_discovered", approved: bool = False) -> dict[str, Any]:
        approval = None
        if bool(candidate.get("requires_human_review") or candidate.get("license_review_required")) and not approved:
            approval = self.approval_gate.request(
                operation="model_download_and_benchmark",
                subject=candidate,
                risks=[{"level": "review", "message": "Model license, size, or runtime requirements need review before download."}],
            )
            return self._finish("approval_required", candidate, approval, None, None, None, False, "Approval required before model download.")

        download = self.downloader.download(candidate, approved=approved)
        if not bool(download.get("ready_for_benchmark")):
            return self._finish("download_not_ready", candidate, approval, download, None, None, False, download.get("reason", "Download did not complete."))

        runtime = str(download.get("runtime") or candidate.get("runtime") or "unknown")
        model_id = str(download.get("model_id") or candidate.get("model_id") or "")
        bench = self.benchmark.benchmark(model_id=model_id, runtime=runtime)
        if not bool(bench.get("passed")):
            return self._finish("benchmark_failed", candidate, approval, download, bench, None, False, bench.get("reason", "Benchmark failed."))

        enriched_candidate = {**candidate, "runtime": runtime, "local_path": download.get("local_path")}
        registration = self.routes.register_after_benchmark(candidate=enriched_candidate, benchmark=bench, route=route)
        saved = False
        if registration.get("status") == "registered":
            self.knowledge.save_success_case("model_lifecycle", {
                "type": "model_route_registration",
                "candidate": enriched_candidate,
                "download": download,
                "benchmark": bench,
                "registration": registration,
            })
            saved = True
        return self._finish(registration.get("status", "completed"), enriched_candidate, approval, download, bench, registration, saved, registration.get("reason", "Completed."))

    def _finish(self, status: str, candidate: dict[str, Any], approval: dict[str, Any] | None, download: dict[str, Any] | None, benchmark: dict[str, Any] | None, registration: dict[str, Any] | None, knowledge_saved: bool, reason: str) -> dict[str, Any]:
        path = self.trace_root / f"{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}.json"
        result = asdict(ModelLifecycleResult(status, candidate, approval, download, benchmark, registration, knowledge_saved, str(path), reason))
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return result
