from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ai_core.config.paths import RUNTIME_GENERATED


class FeedbackEscalator:
    """Stores generic model feedback and decides escalation.

    Feedback is keyed by node/cognitive capability only.  It does not embed
    business or domain vocabulary.
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (RUNTIME_GENERATED / "modeling" / "runtime_feedback_scores.json")

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"nodes": {}, "events": []}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {"nodes": {}, "events": []}
        return data if isinstance(data, dict) else {"nodes": {}, "events": []}

    def feedback_for(self, *, node_id: str, adapter: dict[str, Any] | None = None) -> dict[str, Any]:
        data = self.load()
        nodes = data.get("nodes") if isinstance(data.get("nodes"), dict) else {}
        key = self._key(node_id=node_id, adapter=adapter or {})
        value = nodes.get(key) or nodes.get(str(node_id or "")) or {}
        return value if isinstance(value, dict) else {}

    def should_escalate(self, *, node_id: str, adapter: dict[str, Any], complexity: dict[str, Any], topology: dict[str, Any]) -> bool:
        feedback = self.feedback_for(node_id=node_id, adapter=adapter)
        policy = topology.get("feedback_escalation") if isinstance(topology.get("feedback_escalation"), dict) else {}
        if complexity.get("level") in set(policy.get("always_escalate_levels", ["critical"])):
            return True
        failure_count = int(feedback.get("failure_count") or 0)
        dissatisfaction_count = int(feedback.get("dissatisfaction_count") or 0)
        if failure_count >= int(policy.get("failure_threshold", 2)):
            return True
        if dissatisfaction_count >= int(policy.get("dissatisfaction_threshold", 1)):
            return True
        min_score = policy.get("min_quality_score")
        quality_score = feedback.get("quality_score")
        if isinstance(min_score, (int, float)) and isinstance(quality_score, (int, float)):
            return quality_score < min_score
        return False

    def record_event(self, *, node_id: str, adapter: dict[str, Any], event: dict[str, Any]) -> None:
        data = self.load()
        nodes = data.setdefault("nodes", {})
        events = data.setdefault("events", [])
        key = self._key(node_id=node_id, adapter=adapter)
        current = nodes.setdefault(key, {"failure_count": 0, "dissatisfaction_count": 0, "success_count": 0})
        kind = str(event.get("kind") or event.get("status") or "").lower()
        if kind in {"failure", "failed", "error"}:
            current["failure_count"] = int(current.get("failure_count") or 0) + 1
        elif kind in {"dissatisfied", "unsatisfied", "reject", "retry"}:
            current["dissatisfaction_count"] = int(current.get("dissatisfaction_count") or 0) + 1
        elif kind in {"success", "completed", "approved"}:
            current["success_count"] = int(current.get("success_count") or 0) + 1
        if isinstance(event.get("quality_score"), (int, float)):
            current["quality_score"] = float(event["quality_score"])
        current["updated_at"] = datetime.now(timezone.utc).isoformat()
        events.append({"node_id": node_id, "key": key, "event": event, "at": current["updated_at"]})
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def _key(self, *, node_id: str, adapter: dict[str, Any]) -> str:
        role = str(adapter.get("runtime_role") or adapter.get("role_id") or "").strip()
        return (str(node_id or "") + (":" + role if role else "")).strip(":")
