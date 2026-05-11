import compileall
from pathlib import Path

assert compileall.compile_dir(".", quiet=1)
assert Path("ai_core").exists()
assert Path("apps/web/index.html").exists()

bad_words = ["weather", "flight", "booking", "Tokyo"]
for word in bad_words:
    for path in Path("ai_core").rglob("*.py"):
        assert word.lower() not in path.read_text(encoding="utf-8", errors="ignore").lower(), f"{word} found in {path}"

print("smoke ok")
