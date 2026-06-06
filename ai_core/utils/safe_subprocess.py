from __future__ import annotations

import subprocess
from typing import Any, Sequence


def run_text(args: Sequence[str] | str, **kwargs: Any) -> subprocess.CompletedProcess[str]:
    """Run a subprocess and decode text output safely on every OS.

    Windows often defaults to cp932/cp1252 for captured subprocess text.
    External tools and model runtimes may emit UTF-8 or mixed bytes, which can
    crash background reader threads when subprocess.run(text=True) uses the
    locale default decoder. This wrapper always uses UTF-8 with replacement so
    runtime execution never fails only because output contains non-local bytes.
    """
    kwargs.setdefault("text", True)
    kwargs.setdefault("encoding", "utf-8")
    kwargs.setdefault("errors", "replace")
    return subprocess.run(args, **kwargs)
