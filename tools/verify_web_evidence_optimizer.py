from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ai_core.web_evidence_optimizer import WebEvidenceOptimizer


def main() -> None:
    optimizer = WebEvidenceOptimizer()
    user_input = "Acquire runtime capability: Generic text transform capability. Generate schema and validate with deterministic local run."
    search_results = [
        {
            "url": "https://docs.python.org/3/tutorial/inputoutput.html",
            "title": "Python input and output documentation",
            "snippet": "The Python documentation describes standard string formatting and file-oriented input and output patterns.",
        },
        {
            "url": "https://docs.python.org/3/library/json.html",
            "title": "json documentation",
            "snippet": "The json module provides encoding and decoding support for structured data.",
        },
        {
            "url": "https://example.invalid/noise",
            "title": "Unrelated page",
            "snippet": "This page contains unrelated marketing text with no implementation details.",
        },
    ]
    documents = [
        {
            "document": {
                "url": "https://docs.python.org/3/library/json.html",
                "title": "json documentation",
                "text_excerpt": "The module provides functions for transforming structured data into text and back using deterministic standard-library behavior.",
            },
            "source_search_result": search_results[1],
        }
    ]
    result = optimizer.optimize(
        user_input=user_input,
        capability="runtime_capability_acquisition",
        objective="Generate a capability template from trustworthy implementation evidence.",
        search_results=search_results,
        documents=documents,
    )
    assert result["status"] == "verified", result
    assert result["planned_queries"], result
    assert result["evidence_pack"], result
    assert result["summary"]["ready_for_small_model"] is True, result
    assert result["optimizer_report"]["domain_specific_rules_used"] is False, result
    top = result["evidence_pack"][0]
    assert "source_url" in top and "provenance" in top, top
    print("web_evidence_optimizer: passed")


if __name__ == "__main__":
    main()
