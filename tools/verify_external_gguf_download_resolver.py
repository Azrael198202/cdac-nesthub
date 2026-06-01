from __future__ import annotations

import json
import tempfile
from pathlib import Path

from ai_core.runtime.external_runtimes.gguf_model_resolver import GGUFModelResolver
from ai_core.models.model_downloader import RuntimeModelDownloader


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "runtime" / "external_runtimes" / "models"
        resolver = GGUFModelResolver(root)
        c4 = resolver.resolve_candidate({"model_id": "qwen3.5:4b-q4_k_m"})
        assert c4.get("runtime") == "ollama_gguf", c4
        assert c4.get("filename") == "Qwen3.5-4B-Q4_K_M.gguf", c4
        assert "huggingface.co/unsloth/Qwen3.5-4B-GGUF/resolve/main/Qwen3.5-4B-Q4_K_M.gguf" in c4.get("gguf_url", ""), c4
        c2 = resolver.resolve_candidate({"model_id": "qwen3.5:2b-q4_k_m"})
        assert c2.get("runtime") == "ollama_gguf", c2
        assert c2.get("filename") == "Qwen3.5-2B-Q4_K_M.gguf", c2
        assert c2.get("sha256"), c2
        local_dir = root / "qwen3.5_4b-q4_k_m"
        local_dir.mkdir(parents=True, exist_ok=True)
        local_file = local_dir / "Qwen3.5-4B-Q4_K_M.gguf"
        local_file.write_bytes(b"dummy")
        c4_local = resolver.resolve_candidate({"model_id": "qwen3.5:4b-q4_k_m"})
        assert c4_local.get("gguf_path") == str(local_file), c4_local
    print("OK: external GGUF download resolver resolves Q4_K_M sources and local cache.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
