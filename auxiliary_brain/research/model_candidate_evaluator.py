from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class ModelCandidateEvaluation:
    status: str
    model_id: str
    estimated_use_cases: list[str]
    estimated_hardware: dict[str, Any]
    download_strategy: dict[str, Any]
    license_review_required: bool
    requires_human_review: bool
    reason: str


class ModelCandidateEvaluator:
    """Evaluate model candidates for runtime routing and download planning.

    It does not download models. It estimates suitability, hardware pressure, and
    review requirements from generic metadata so a later runtime step can decide
    whether to pull, benchmark, and register the model.
    """

    def evaluate(self, candidate: dict[str, Any], *, task_context: dict[str, Any] | None = None) -> dict[str, Any]:
        model_id = str(candidate.get("model_id") or candidate.get("id") or candidate.get("name") or "unknown")
        tags = [str(t).lower() for t in candidate.get("tags", [])] if isinstance(candidate.get("tags"), list) else []
        pipeline = str(candidate.get("pipeline_tag") or "").lower()
        lowered = " ".join([model_id.lower(), pipeline, " ".join(tags)])
        use_cases = self._use_cases(lowered, pipeline)
        hardware = self._hardware_estimate(lowered)
        download_strategy = self._download_strategy(model_id, hardware, candidate)
        license_review = not any("license:" in t or t.startswith("apache-") or t.startswith("mit") for t in tags)
        return asdict(ModelCandidateEvaluation(
            status="evaluated",
            model_id=model_id,
            estimated_use_cases=use_cases,
            estimated_hardware=hardware,
            download_strategy=download_strategy,
            license_review_required=license_review,
            requires_human_review=license_review or hardware.get("risk") == "high",
            reason="Model candidate evaluated. Download and route registration require benchmark verification.",
        ))

    def _use_cases(self, lowered: str, pipeline: str) -> list[str]:
        cases: list[str] = []
        mapping = {
            "text-generation": "general_text_generation",
            "conversational": "chat_or_instruction_following",
            "sentence-similarity": "embedding_or_retrieval",
            "automatic-speech-recognition": "speech_to_text",
            "text-to-speech": "text_to_speech",
            "image-text-to-text": "vision_language",
            "image-classification": "image_understanding",
        }
        if pipeline in mapping:
            cases.append(mapping[pipeline])
        if any(x in lowered for x in ["instruct", "chat", "qwen", "llama", "mistral"]):
            cases.append("instruction_following")
        if any(x in lowered for x in ["embed", "bge", "e5"]):
            cases.append("embedding_or_retrieval")
        if not cases:
            cases.append("unknown_requires_benchmark")
        return sorted(set(cases))

    def _hardware_estimate(self, lowered: str) -> dict[str, Any]:
        size = "unknown"
        vram_gb = None
        risk = "review"
        for marker, gb in [("72b", 48), ("70b", 48), ("32b", 24), ("14b", 16), ("13b", 16), ("8b", 8), ("7b", 8), ("4b", 6), ("3b", 4), ("1.5b", 3)]:
            if marker in lowered:
                size = marker
                vram_gb = gb
                risk = "high" if gb >= 24 else "medium" if gb >= 8 else "low"
                break
        return {
            "parameter_size_hint": size,
            "estimated_min_vram_gb": vram_gb,
            "risk": risk,
            "notes": "Estimate only. Actual requirement depends on quantization, context length, framework, and batch size.",
        }

    def _download_strategy(self, model_id: str, hardware: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
        return {
            "strategy": "defer_until_benchmark_plan_is_approved",
            "preferred_runtime": "ollama_or_vllm_or_transformers_based_on_format",
            "candidate_url": candidate.get("url"),
            "precheck": [
                "verify license",
                "verify disk space",
                "verify VRAM/CPU memory",
                "download to runtime/models cache",
                "run small benchmark",
                "register route only after benchmark passes",
            ],
            "estimated_min_vram_gb": hardware.get("estimated_min_vram_gb"),
        }
