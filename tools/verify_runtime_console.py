from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


from ai_core.runtime.observability.runtime_console import emit_console_event, list_console_sources, read_console_source

emit_console_event(area="verify", event="runtime_console", status="completed", message="console verification event", data={"token":"should not be secret", "api_key":"abc"})
sources = list_console_sources()
assert any(item.get("path") == "runtime/logs/runtime_console.jsonl" for item in sources), sources[:5]
read = read_console_source("runtime/logs/runtime_console.jsonl", tail=True)
assert read.get("ok") is True, read
assert "console verification event" in read.get("content", "")
assert "abc" not in read.get("content", "")
html = Path("apps/web/runtime_console.html")
assert html.exists(), "runtime_console.html missing"
server = Path("apps/api/server.py").read_text(encoding="utf-8")
assert "/runtime-console" in server
assert "/api/runtime-console/sources" in server
print("runtime console verification passed")
