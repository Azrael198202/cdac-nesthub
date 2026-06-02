from __future__ import annotations

import time
from apps.api.server import _normalize_agent_studio_job, _job_progress

def main() -> None:
    running = _normalize_agent_studio_job("verify_run", {
        "status": "running",
        "started_at": time.time(),
        "progress_events": [_job_progress("request accepted", "completed")],
    })
    assert running["status"] == "running", running

    timed_out = _normalize_agent_studio_job("verify_timeout", {
        "status": "running",
        "started_at": time.time() - 9999,
        "progress_events": [_job_progress("request accepted", "completed")],
    })
    assert timed_out["status"] == "failed", timed_out
    assert timed_out["stage"] == "timed_out", timed_out
    print("agent studio progress state recovery verified")

if __name__ == "__main__":
    main()
