import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ai_core.runtime.modeling.model_runtime_preflight import ModelRuntimePreflight

preflight = ModelRuntimePreflight()
called = {}
class FakeDownloader:
    def download(self, candidate, *, approved=False, timeout_seconds=0):
        called["candidate"] = candidate
        called["approved"] = approved
        called["timeout_seconds"] = timeout_seconds
        return {
            "status":"downloaded",
            "model_id": candidate["model_id"],
            "runtime":"ollama",
            "local_path": None,
            "command":["ollama","pull",candidate["model_id"]],
            "metadata_path":"runtime/downloads/models/test.download.json",
            "ready_for_benchmark": True,
            "requires_human_review": False,
            "reason":"ok",
        }
preflight.model_downloader = FakeDownloader()
result = preflight._maybe_download_local_model("ollama", "unit-test-model:latest")
assert result["attempted"] is True, result
assert called["candidate"]["model_id"] == "unit-test-model:latest", called
assert called["approved"] is True, called
assert called["timeout_seconds"] >= 30, called
print("verify_local_model_auto_download_hook: OK")
