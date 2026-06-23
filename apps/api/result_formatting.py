from __future__ import annotations

from pathlib import Path
from typing import Any

from ai_core.runtime_result_normalizer import normalize_runtime_response


def format_async_job_result(result: Any, *, runtime_root: str | Path | None = None, run_id: str | None = None) -> dict[str, Any]:
    return normalize_runtime_response(result, runtime_root=runtime_root, run_id=run_id)
