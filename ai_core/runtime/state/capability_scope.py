from __future__ import annotations

import json
import threading
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ai_core.config.paths import RUNTIME_TRACES


@dataclass
class CapabilityScopedInteraction:
    """Durable state for one capability-owned user interaction.

    This is generic runtime state isolation.  It does not know what any
    capability does; it only scopes pending input, verification, and repair
    material by session, run, and capability identifiers so unrelated
    capabilities cannot reuse stale prompts from the same UI session.
    """

    interaction_id: str
    session_id: str
    run_id: str
    capability_id: str
    interaction_type: str
    status: str = "waiting"
    request: dict[str, Any] = field(default_factory=dict)
    response: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class CapabilityScopedStateStore:
    def __init__(self, state_dir: Path | str | None = None) -> None:
        self.state_dir = Path(state_dir) if state_dir else RUNTIME_TRACES / "capability_scoped_state"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def record_interaction(
        self,
        *,
        session_id: str,
        run_id: str,
        capability_id: str,
        interaction_type: str,
        request: dict[str, Any],
    ) -> dict[str, Any]:
        now = self._now()
        session_id = self._safe_id(session_id or "default_session")
        run_id = self._safe_id(run_id or "runtime_run")
        capability_id = self._safe_id(capability_id or "runtime_capability")
        interaction_type = self._safe_id(interaction_type or "runtime_interaction")
        interaction_id = self._safe_id(str(request.get("interaction_id") or f"{run_id}_{capability_id}_{interaction_type}"))
        item = CapabilityScopedInteraction(
            interaction_id=interaction_id,
            session_id=session_id,
            run_id=run_id,
            capability_id=capability_id,
            interaction_type=interaction_type,
            status="waiting",
            request=dict(request or {}),
            created_at=now,
            updated_at=now,
        )
        payload = item.to_dict()
        payload["request"] = self._attach_scope(payload["request"], payload)
        with self._lock:
            self._write_item(payload)
            self._write_session_pointer(session_id, payload)
        return payload

    def resolve_interaction(
        self,
        *,
        session_id: str = "",
        run_id: str = "",
        capability_id: str = "",
        interaction_id: str = "",
        response: dict[str, Any] | None = None,
        status: str = "resolved",
    ) -> dict[str, Any] | None:
        with self._lock:
            item = self._find_item(session_id=session_id, run_id=run_id, capability_id=capability_id, interaction_id=interaction_id)
            if not item:
                return None
            item["status"] = status or "resolved"
            item["response"] = response or {}
            item["updated_at"] = self._now()
            self._write_item(item)
            self._write_session_pointer(item.get("session_id", ""), item)
            return item

    def active_for_scope(self, *, session_id: str = "", run_id: str = "", capability_id: str = "") -> dict[str, Any] | None:
        with self._lock:
            return self._find_item(session_id=session_id, run_id=run_id, capability_id=capability_id, interaction_id="", active_only=True)

    def is_request_current(self, request: dict[str, Any], *, session_id: str = "", run_id: str = "") -> bool:
        """Return whether a pending request belongs to the selected scope.

        UI/API can use this to avoid showing stale pending input from a previous
        capability in the same session.
        """
        scope = request.get("scope") if isinstance(request.get("scope"), dict) else {}
        req_run = str(scope.get("run_id") or request.get("source_run_id") or "").strip()
        req_session = str(scope.get("session_id") or request.get("session_id") or "").strip()
        if run_id and req_run and self._safe_id(req_run) != self._safe_id(run_id):
            return False
        if session_id and req_session and self._safe_id(req_session) != self._safe_id(session_id):
            return False
        return True

    def _attach_scope(self, request: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        out = dict(request or {})
        scope = dict(out.get("scope") if isinstance(out.get("scope"), dict) else {})
        scope.update({
            "session_id": payload.get("session_id", ""),
            "run_id": payload.get("run_id", ""),
            "capability_id": payload.get("capability_id", ""),
            "interaction_id": payload.get("interaction_id", ""),
            "interaction_type": payload.get("interaction_type", ""),
        })
        out["scope"] = scope
        out.setdefault("session_id", scope["session_id"])
        out.setdefault("source_run_id", scope["run_id"])
        out.setdefault("capability_id", scope["capability_id"])
        out.setdefault("interaction_id", scope["interaction_id"])
        for field in out.get("fields") or []:
            if isinstance(field, dict):
                # field["scope"] may be a schema section such as input,
                # connection, or secrets.  Do not overwrite it with runtime
                # ownership metadata.  Store ownership in runtime_scope instead.
                field["runtime_scope"] = dict(scope)
                field.setdefault("source_run_id", scope["run_id"])
                field.setdefault("capability_id", scope["capability_id"])
                field.setdefault("interaction_id", scope["interaction_id"])
        return out

    def _find_item(self, *, session_id: str = "", run_id: str = "", capability_id: str = "", interaction_id: str = "", active_only: bool = False) -> dict[str, Any] | None:
        candidates: list[dict[str, Any]] = []
        if interaction_id:
            path = self.state_dir / "interactions" / f"{self._safe_id(interaction_id)}.json"
            item = self._read_json(path)
            if item:
                candidates.append(item)
        else:
            base = self.state_dir / "interactions"
            for path in base.glob("*.json") if base.exists() else []:
                item = self._read_json(path)
                if item:
                    candidates.append(item)
        safe_session = self._safe_id(session_id) if session_id else ""
        safe_run = self._safe_id(run_id) if run_id else ""
        safe_cap = self._safe_id(capability_id) if capability_id else ""
        filtered = []
        for item in candidates:
            if safe_session and self._safe_id(item.get("session_id", "")) != safe_session:
                continue
            if safe_run and self._safe_id(item.get("run_id", "")) != safe_run:
                continue
            if safe_cap and self._safe_id(item.get("capability_id", "")) != safe_cap:
                continue
            if active_only and str(item.get("status") or "") not in {"waiting", "paused", "requires_input"}:
                continue
            filtered.append(item)
        filtered.sort(key=lambda x: str(x.get("updated_at") or x.get("created_at") or ""), reverse=True)
        return filtered[0] if filtered else None

    def _write_item(self, payload: dict[str, Any]) -> None:
        path = self.state_dir / "interactions" / f"{self._safe_id(payload.get('interaction_id', 'interaction'))}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _write_session_pointer(self, session_id: str, payload: dict[str, Any]) -> None:
        sid = self._safe_id(session_id or "default_session")
        path = self.state_dir / "sessions" / sid / "latest_interaction.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _read_json(self, path: Path) -> dict[str, Any] | None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        return data if isinstance(data, dict) else None

    def _safe_id(self, value: str) -> str:
        raw = str(value or "")[:180]
        safe = "".join(ch if ch.isalnum() or ch in {"_", "-", "."} else "_" for ch in raw).strip("._")
        return safe or "default"

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()


capability_scoped_state_store = CapabilityScopedStateStore()
