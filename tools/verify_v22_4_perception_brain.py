from __future__ import annotations

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from perception_brain import PerceptionBrainService
from perception_brain.modality_router import PerceptionModalityRouter


def main() -> None:
    router = PerceptionModalityRouter()
    assert router.classify({"filename": "sample.png", "mime_type": "image/png"}) == "image"
    assert router.classify({"filename": "sample.mp3", "mime_type": "audio/mpeg"}) == "audio"
    assert router.classify({"filename": "sample.pdf", "mime_type": "application/pdf"}) == "document"

    root = Path("runtime/uploads/files")
    root.mkdir(parents=True, exist_ok=True)
    doc = root / "perception_verify.txt"
    doc.write_text("Generic verification material for perception normalization.", encoding="utf-8")
    service = PerceptionBrainService()
    payload = service.normalize(
        text="Normalize this artifact before core processing.",
        uploaded_artifacts=[{"artifact_id": "artifact_verify", "filename": doc.name, "path": str(doc), "mime_type": "text/plain", "size_bytes": doc.stat().st_size}],
        context={"test": "verify_v22_4_perception_brain"},
    )
    assert payload["metadata"]["artifact_count"] == 1
    assert payload["artifacts"][0]["modality"] == "document"
    assert payload["artifacts"][0]["status"] == "normalized"
    assert "[Perception Brain normalized artifacts]" in payload["normalized_text"]
    assert "Generic verification material" in payload["normalized_text"]
    print("verify_v22_4_perception_brain: OK")


if __name__ == "__main__":
    main()
