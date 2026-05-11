import compileall
from pathlib import Path
assert compileall.compile_dir(".", quiet=1)
for word in ["weather", "flight", "booking", "Tokyo"]:
    # Node runner may contain generic parsing keywords; this test only ensures no fixed Tokyo/business sample.
    if word == "Tokyo":
        for path in Path("ai_core").rglob("*.py"):
            assert word.lower() not in path.read_text(encoding="utf-8", errors="ignore").lower()
print("smoke ok")
