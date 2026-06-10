from __future__ import annotations

from typing import Any


class WebEvidenceRepairAdvisor:
    """Optional adapter for external evidence repair.

    It is deliberately lazy and optional so importing the self-repair package does
    not require network access or web dependencies. The caller decides whether
    network use is allowed by policy.
    """

    async def advise(
        self,
        *,
        run_id: str,
        node_id: str,
        failure_summary: str,
        step: dict[str, Any] | None = None,
        user_input: str = "",
        network_allowed: bool = False,
    ) -> dict[str, Any]:
        if not network_allowed:
            return {
                "status": "web_evidence_not_allowed",
                "requires_human_review": True,
                "reason": "Runtime policy did not allow external web evidence retrieval.",
            }
        try:
            from auxiliary_brain.research.external_solution_discovery import ExternalSolutionDiscoveryEngine
        except Exception as exc:
            return {
                "status": "web_evidence_unavailable",
                "requires_human_review": True,
                "reason": str(exc),
            }
        engine = ExternalSolutionDiscoveryEngine()
        discovery = await engine.discover(
            run_id=run_id,
            node_id=node_id,
            capability="runtime_failure_repair",
            step=step or {"objective": failure_summary, "execution_strategy": ["web_evidence"]},
            user_input=user_input or failure_summary,
        )
        return {
            "status": "web_evidence_collected",
            "requires_human_review": True,
            "discovery": discovery,
            "reason": "External evidence collected. A repair must still pass validation before execution.",
        }
