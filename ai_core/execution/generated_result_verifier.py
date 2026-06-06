from __future__ import annotations

from typing import Any


class GeneratedResultVerifier:
    """Validates that generated execution output is backed by runtime evidence.

    This verifier is intentionally domain-neutral. It does not inspect domain
    vocabulary. It only checks generic proof signals: declared real execution,
    network or external access evidence, source references, and material-quality
    metadata. A generated module may return a syntactically successful payload,
    but that payload must not be treated as verified unless at least one generic
    evidence signal is present.
    """

    GENERATED_SOURCES = {
        "runtime_generated_module",
        "runtime_registered_module",
        "runtime_generated_tool",
        "runtime_tool",
    }

    def verify(self, result: dict[str, Any], *, provenance: dict[str, Any] | None = None, artifact: dict[str, Any] | None = None) -> dict[str, Any]:
        if not isinstance(result, dict):
            return self._failed("invalid_result", "Generated execution returned a non-object result.")

        source = str(result.get("source") or "").strip()
        if source and source not in self.GENERATED_SOURCES:
            return self._passed("non_generated_source")

        provenance = provenance if isinstance(provenance, dict) else result.get("provenance")
        if not isinstance(provenance, dict):
            provenance = {}
        artifact = artifact if isinstance(artifact, dict) else {}

        if self._has_positive_execution_claims(result, provenance, artifact):
            return self._passed("positive_execution_claims")
        if self._has_source_reference(result):
            return self._passed("source_reference_present")
        if self._has_quality_confirmation(result):
            return self._passed("quality_confirmation_present")

        return self._failed(
            "missing_evidence_proof",
            "Generated execution output has no generic proof of real execution, source references, or evidence quality.",
        )

    def enforce(self, result: dict[str, Any], *, provenance: dict[str, Any] | None = None, artifact: dict[str, Any] | None = None) -> dict[str, Any]:
        verification = self.verify(result, provenance=provenance, artifact=artifact)
        if verification.get("passed"):
            result.setdefault("verification", {})
            if isinstance(result.get("verification"), dict):
                result["verification"]["generated_result_verification"] = verification
            return result

        original_keys = sorted(str(k) for k in result.keys()) if isinstance(result, dict) else []
        return {
            "status": "error",
            "error": {
                "code": "generated_result_missing_evidence",
                "message": verification.get("reason") or "Generated result is not evidence-backed.",
            },
            "data": {
                "verification": verification,
                "original_status": result.get("status") if isinstance(result, dict) else None,
                "original_keys": original_keys,
            },
            "source": result.get("source") or "runtime_generated_output",
            "requires_human_confirmation": False,
        }

    def _has_positive_execution_claims(self, result: dict[str, Any], provenance: dict[str, Any], artifact: dict[str, Any]) -> bool:
        claim_sets: list[dict[str, Any]] = []
        for obj in (result, provenance, artifact):
            if isinstance(obj, dict):
                claims = obj.get("execution_claims")
                if isinstance(claims, dict):
                    claim_sets.append(claims)
        for claims in claim_sets:
            if claims.get("live_verification_passed") is True:
                return True
            if claims.get("network_declared") is True and claims.get("real_execution_declared") is True:
                return True
            if claims.get("no_mock_data_declared") is True and claims.get("real_execution_declared") is True:
                return True
        return False

    def _has_source_reference(self, value: Any) -> bool:
        if isinstance(value, dict):
            for key, item in value.items():
                key_text = str(key).lower()
                if key_text in {"source_url", "source_urls", "evidence_url", "evidence_urls", "sources", "references"}:
                    if self._non_empty_reference(item):
                        return True
                if self._has_source_reference(item):
                    return True
        if isinstance(value, list):
            return any(self._has_source_reference(item) or self._non_empty_reference(item) for item in value)
        return False

    def _non_empty_reference(self, item: Any) -> bool:
        if isinstance(item, str):
            text = item.strip()
            # Domain-neutral but strict: a generated output must point to an
            # external or traceable evidence reference, not just any label.
            return text.startswith("http://") or text.startswith("https://") or text.startswith("file://")
        if isinstance(item, list):
            return any(self._non_empty_reference(x) for x in item)
        if isinstance(item, dict):
            for key, value in item.items():
                key_text = str(key).lower()
                if key_text in {"url", "href", "uri", "path", "trace_path", "source_url", "evidence_url"}:
                    if self._non_empty_reference(value):
                        return True
            return any(self._non_empty_reference(x) for x in item.values())
        return False

    def _has_quality_confirmation(self, result: dict[str, Any]) -> bool:
        candidates = [
            result.get("answer_material_quality"),
            result.get("evidence_quality"),
            result.get("quality"),
        ]
        data = result.get("data")
        if isinstance(data, dict):
            candidates.extend([
                data.get("answer_material_quality"),
                data.get("evidence_quality"),
                data.get("quality"),
            ])
        for item in candidates:
            if isinstance(item, dict) and item.get("passed") is True:
                return True
        return False

    def _passed(self, reason: str) -> dict[str, Any]:
        return {"passed": True, "reason": reason, "trust_level": "evidence_backed_or_declared"}

    def _failed(self, code: str, reason: str) -> dict[str, Any]:
        return {"passed": False, "code": code, "reason": reason, "trust_level": "synthetic_or_unverified"}
