from __future__ import annotations

from pathlib import Path

import uvicorn

ROOT = Path(__file__).resolve().parent
SOURCE_DIRS = [
    "apps",
    "ai_core",
    "auxiliary_brain",
    "perception_brain",
    "verification_brain",
    "repair_brain",
    "presentation_brain",
    "evidence_engine",
    "task_runtime",
]

# Runtime-generated files are execution outputs. They must never be watched in
# development reload mode, because capability acquisition writes Python files
# while a job is running. Watching them causes WatchFiles to restart the API and
# leaves the browser looking like the job is still running.
RUNTIME_EXCLUDES = [
    "runtime/generated",
    "runtime/traces",
    "runtime/logs",
    "runtime/cache",
    "runtime/registry",
    "runtime/uploads",
    "runtime/downloads",
    "runtime/profiles",
    "runtime/secrets",
]

def patterns_for(path: str) -> list[str]:
    rel = path.replace("\\", "/").rstrip("/")
    abs_path = (ROOT / rel).as_posix()
    return [
        rel,
        f"{rel}/*",
        f"{rel}/**",
        f"{rel}/**/*",
        abs_path,
        f"{abs_path}/*",
        f"{abs_path}/**",
        f"{abs_path}/**/*",
    ]

if __name__ == "__main__":
    print("Starting development API with source-only reload.")
    print("Runtime output directories are excluded from WatchFiles reload.")
    reload_excludes: list[str] = []
    for item in RUNTIME_EXCLUDES:
        reload_excludes.extend(patterns_for(item))

    uvicorn.run(
        "apps.api.server:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
        reload_dirs=[str((ROOT / d).resolve()) for d in SOURCE_DIRS],
        reload_includes=["*.py", "*.html", "*.js", "*.css", "*.json", "*.yaml", "*.yml"],
        reload_excludes=reload_excludes,
    )
