from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ai_core.config.paths import RUNTIME_GENERATED


class RuntimeGovernanceRegistry:
    """Persists runtime-generated model/capability governance artifacts.

    This registry is intentionally generic.  It stores the model inventory,
    generated topology, missing-model recommendations, and feedback signals
    under runtime/generated so the source tree remains domain-neutral.
    """

    def __init__(self, base_dir: Path | None = None) -> None:
        self.base_dir = base_dir or (RUNTIME_GENERATED / "system_topology")

    def write_bootstrap_artifacts(
        self,
        *,
        topology: dict[str, Any],
        provider_inventory: dict[str, Any],
        feature_inventory: dict[str, Any],
        source: str,
    ) -> None:
        self.base_dir.mkdir(parents=True, exist_ok=True)
        now = datetime.now(timezone.utc).isoformat()
        self._write("runtime_governance_graph.json", {**topology, "bootstrap_source": source, "updated_at": now})
        self._write("model_inventory.json", {"updated_at": now, **(provider_inventory or {})})
        self._write("feature_inventory_snapshot.json", {"updated_at": now, **(feature_inventory or {})})
        self._write("model_requirements.json", self._extract_requirements(topology, now))
        self._write("missing_model_recommendations.json", {
            "updated_at": now,
            "recommendations": topology.get("missing_model_recommendations") if isinstance(topology, dict) else [],
            "policy": topology.get("missing_model_policy", {}) if isinstance(topology, dict) else {},
        })

    def _extract_requirements(self, topology: dict[str, Any], updated_at: str) -> dict[str, Any]:
        return {
            "updated_at": updated_at,
            "model_role_defaults": topology.get("model_role_defaults", {}) if isinstance(topology, dict) else {},
            "capability_semantic_graph": topology.get("capability_semantic_graph", {}) if isinstance(topology, dict) else {},
            "execution_mode_rules": topology.get("execution_mode_rules", {}) if isinstance(topology, dict) else {},
            "mcp_discovery_policy": topology.get("mcp_discovery_policy", {}) if isinstance(topology, dict) else {},
        }

    def _write(self, name: str, payload: dict[str, Any]) -> None:
        (self.base_dir / name).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
