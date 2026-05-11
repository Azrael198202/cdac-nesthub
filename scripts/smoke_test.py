import compileall
from pathlib import Path
assert compileall.compile_dir(".", quiet=1)
assert Path("ai_core").exists()
print("smoke ok")
