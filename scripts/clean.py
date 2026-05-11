from pathlib import Path
import shutil

for p in Path(".").rglob("__pycache__"):
    shutil.rmtree(p, ignore_errors=True)

for p in Path(".").rglob("*.pyc"):
    p.unlink(missing_ok=True)

print("cache cleaned")