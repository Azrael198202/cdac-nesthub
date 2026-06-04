from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ai_core.config.paths import RUNTIME_GENERATED, RUNTIME_TRACES
from auxiliary_brain.capability_acquisition.trace_logger import CapabilityAcquisitionTraceLogger


class AuxiliaryCapabilityRepairCoordinator:
    """Auxiliary-brain owner for runtime capability repair requests.

    ai_core may diagnose that an implementation-level repair is needed, but it
    only writes a neutral patch request.  This coordinator consumes that request
    in auxiliary_brain and prepares the patch lifecycle artifacts.  Concrete
    patch generation can be driven by a strong model or another runtime planner;
    registration is allowed only after sandbox and execution verification.
    """

    def __init__(self) -> None:
        self.request_dir = RUNTIME_GENERATED / "capability_patch_requests"
        self.patch_dir = RUNTIME_GENERATED / "capability_patches"
        self.trace = CapabilityAcquisitionTraceLogger(root=RUNTIME_TRACES / "capability_repair")

    def prepare_patch_lifecycle(self, *, request_id: str) -> dict[str, Any]:
        request = self._load_request(request_id)
        run_id = str(request.get("request_id") or request_id or "capability_repair")
        self.trace.record(run_id=run_id, stage="repair_request_loaded", status=str(request.get("status") or "loaded"), payload=request)
        if not request:
            result = {"ok": False, "status": "request_not_found", "request_id": request_id}
            self.trace.record(run_id=run_id, stage="repair_request_loaded", status="not_found", payload=result)
            return result
        lifecycle = {
            "request_id": run_id,
            "status": "patch_lifecycle_prepared",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "tool_id": request.get("tool_id"),
            "required_steps": [
                {"stage": "read_failure_trace", "owner": "auxiliary_brain", "status": "pending"},
                {"stage": "generate_patch_outside_ai_core", "owner": "auxiliary_brain", "status": "pending"},
                {"stage": "sandbox_validation", "owner": "auxiliary_brain", "status": "pending"},
                {"stage": "execution_verification", "owner": "auxiliary_brain", "status": "pending"},
                {"stage": "registry_update", "owner": "auxiliary_brain", "status": "blocked_until_verified"},
            ],
            "source_request": request,
        }
        out_dir = self.patch_dir / self._safe_name(run_id)
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / "patch_lifecycle.json"
        path.write_text(json.dumps(lifecycle, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        self.trace.record(run_id=run_id, stage="patch_lifecycle_prepared", status="pending_patch_generation", payload={"path": str(path), "lifecycle": lifecycle})
        return {"ok": True, "status": "patch_lifecycle_prepared", "request_id": run_id, "path": str(path), "lifecycle": lifecycle}

    def _load_request(self, request_id: str) -> dict[str, Any]:
        path = self.request_dir / f"{self._safe_name(request_id)}.json"
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8") or "{}")
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _safe_name(self, value: str) -> str:
        return "".join(c if c.isalnum() or c in {"_", "-"} else "_" for c in str(value)).strip("_") or "unknown"
