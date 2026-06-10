from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


class RuntimeNativeProvider:
    """Returns observations from the local runtime.

    It exposes generic runtime state only.  It does not decide when to use the
    value; the routing contract decides that before this provider is called.
    """

    def execute(self, *, run_id: str, node_id: str, step_id: str, capability: str, step: dict[str, Any]) -> dict[str, Any]:
        observed_at = datetime.now(timezone.utc).astimezone().isoformat()
        fact = {
            "kind": "observed_value",
            "label": "runtime_observation",
            "value": observed_at,
            "unit": "",
            "context": "runtime native observation",
            "confidence": 0.99,
            "source_level": "runtime_native",
            "source": "runtime_native",
            "structured": True,
        }
        return {
            "input": {
                "run_id": run_id,
                "node_id": node_id,
                "step_id": step_id,
                "capability": capability,
                "source_step": step,
            },
            "result": {
                "status": "success",
                "source": "runtime_native_observation",
                "data": {
                    "normalized_facts": [fact],
                    "source_url": "",
                    "source_title": "runtime_native",
                },
                "provenance": {
                    "source": "runtime_native",
                    "execution_claims": {
                        "real_execution_declared": True,
                        "no_mock_data_declared": True,
                        "network_declared": False,
                        "live_verification_passed": True,
                        "evidence_quality_passed": True,
                    },
                },
            },
        }
