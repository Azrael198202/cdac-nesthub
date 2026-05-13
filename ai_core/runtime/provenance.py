from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ai_core.config.paths import RUNTIME_TRACES


class ExecutionProvenanceRecorder:
    """Records generic execution provenance for tools and modules.

    This class is intentionally domain-neutral. It does not know provider names,
    API meanings, or business semantics. It records only runtime execution facts:
    which artifact ran, which input was supplied, what output was returned, how
    long it took, and whether the artifact declared real external behavior.
    """

    def __init__(self) -> None:
        self.trace_dir = RUNTIME_TRACES / "executions"
        self.trace_dir.mkdir(parents=True, exist_ok=True)

    def start(
        self,
        *,
        run_id: str,
        node_id: str,
        step_id: str,
        component_type: str,
        component_id: str,
        capability: str | None = None,
        input_data: dict[str, Any] | None = None,
        artifact: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        trace_id = self._trace_id(run_id=run_id, node_id=node_id, step_id=step_id, component_id=component_id)
        now = self._now()
        manifest = artifact if isinstance(artifact, dict) else {}
        trace = {
            "trace_id": trace_id,
            "run_id": run_id,
            "node_id": node_id,
            "step_id": step_id,
            "component_type": component_type,
            "component_id": component_id,
            "capability": capability,
            "status": "started",
            "started_at": now,
            "finished_at": None,
            "duration_ms": None,
            "input": self._safe_json(input_data or {}),
            "output": None,
            "error": None,
            "artifact": self._artifact_summary(manifest),
            "execution_claims": self._execution_claims(manifest),
            "events": [
                {
                    "type": "execution_started",
                    "time": now,
                }
            ],
            "trace_path": str(self.trace_dir / f"{trace_id}.json"),
            "_started_monotonic": time.perf_counter(),
        }
        self._write(trace)
        return trace

    def finish(self, trace: dict[str, Any], *, output: Any = None, status: str = "success", error: Any = None) -> dict[str, Any]:
        finished_at = self._now()
        started = trace.pop("_started_monotonic", None)
        duration_ms = None
        if isinstance(started, (int, float)):
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
        trace["status"] = status
        trace["finished_at"] = finished_at
        trace["duration_ms"] = duration_ms
        trace["output"] = self._safe_json(output)
        trace["error"] = self._safe_json(error) if error else None
        trace.setdefault("events", []).append({"type": "execution_finished", "time": finished_at, "status": status})
        self._write(trace)
        return trace

    def attach(self, result: dict[str, Any], trace: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(result, dict):
            result = {"status": "success", "data": {"value": result}}
        result["provenance"] = self.public_trace(trace)
        return result

    def public_trace(self, trace: dict[str, Any]) -> dict[str, Any]:
        return {
            "trace_id": trace.get("trace_id"),
            "trace_path": trace.get("trace_path"),
            "run_id": trace.get("run_id"),
            "node_id": trace.get("node_id"),
            "step_id": trace.get("step_id"),
            "component_type": trace.get("component_type"),
            "component_id": trace.get("component_id"),
            "capability": trace.get("capability"),
            "status": trace.get("status"),
            "started_at": trace.get("started_at"),
            "finished_at": trace.get("finished_at"),
            "duration_ms": trace.get("duration_ms"),
            "artifact": trace.get("artifact"),
            "execution_claims": trace.get("execution_claims"),
        }

    def _trace_id(self, *, run_id: str, node_id: str, step_id: str, component_id: str) -> str:
        raw = f"{run_id}_{node_id}_{step_id}_{component_id}_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"
        return "".join(c if c.isalnum() or c in {"_", "-"} else "_" for c in raw).strip("_") or "execution_trace"

    def _artifact_summary(self, artifact: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(artifact, dict):
            return {}
        metadata = artifact.get("metadata") if isinstance(artifact.get("metadata"), dict) else {}
        implementation = artifact.get("implementation") if isinstance(artifact.get("implementation"), dict) else {}
        runtime_interface = artifact.get("runtime_interface") if isinstance(artifact.get("runtime_interface"), dict) else {}
        return {
            "id": artifact.get("tool_id") or artifact.get("module_id") or artifact.get("id") or artifact.get("name"),
            "name": artifact.get("name"),
            "version": artifact.get("version") or metadata.get("version"),
            "status": artifact.get("status"),
            "source": artifact.get("source") or metadata.get("source"),
            "runtime_generated": artifact.get("runtime_generated") or metadata.get("runtime_generated"),
            "spec_path": artifact.get("spec_path") or artifact.get("module_spec") or metadata.get("manifest_path"),
            "module_path": implementation.get("module_path") or implementation.get("path") or artifact.get("entrypoint"),
            "callable": implementation.get("function") or implementation.get("callable") or runtime_interface.get("callable") or "run",
            "input_schema_present": isinstance(artifact.get("input_schema"), dict),
            "output_schema_present": isinstance(artifact.get("output_schema"), dict),
        }

    def _execution_claims(self, artifact: dict[str, Any]) -> dict[str, Any]:
        metadata = artifact.get("metadata") if isinstance(artifact.get("metadata"), dict) else {}
        safety = artifact.get("safety") or artifact.get("safety_policy") or metadata.get("safety") or {}
        if not isinstance(safety, dict):
            safety = {}
        network = artifact.get("network") if isinstance(artifact.get("network"), dict) else metadata.get("network") if isinstance(metadata.get("network"), dict) else {}
        claims = artifact.get("execution_claims") if isinstance(artifact.get("execution_claims"), dict) else metadata.get("execution_claims") if isinstance(metadata.get("execution_claims"), dict) else {}
        return {
            "uses_network": claims.get("uses_network", network.get("enabled", safety.get("can_read_external_data"))),
            "network_declared": bool(network) or "uses_network" in claims,
            "can_write_external_data": safety.get("can_write_external_data"),
            "can_perform_irreversible_action": safety.get("can_perform_irreversible_action"),
            "requires_human_confirmation": safety.get("requires_human_confirmation"),
            "no_mock_data_declared": claims.get("no_mock_data") or artifact.get("no_mock_data"),
            "real_execution_declared": claims.get("real_execution") or artifact.get("real_execution"),
        }

    def _safe_json(self, value: Any) -> Any:
        try:
            json.dumps(value, ensure_ascii=False)
            return value
        except Exception:
            return repr(value)

    def _write(self, trace: dict[str, Any]) -> None:
        path = Path(str(trace.get("trace_path") or self.trace_dir / "execution_trace.json"))
        path.parent.mkdir(parents=True, exist_ok=True)
        public_copy = {k: v for k, v in trace.items() if k != "_started_monotonic"}
        path.write_text(json.dumps(public_copy, ensure_ascii=False, indent=2), encoding="utf-8")

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()
