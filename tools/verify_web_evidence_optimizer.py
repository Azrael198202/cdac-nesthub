from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ai_core.web_evidence_optimizer import WebEvidenceOptimizer


def main() -> None:
    optimizer = WebEvidenceOptimizer()
    user_input = "Acquire runtime capability: Generic text transport sender. Generate schema and validate with dry run."
    search_results = [
        {
            "url": "https://docs.python.org/3/library/email.message.html",
            "title": "email.message documentation",
            "snippet": "The email.message module provides a class for representing messages and parameters.",
        },
        {
            "url": "https://docs.python.org/3/library/smtplib.html",
            "title": "smtplib documentation",
            "snippet": "The smtplib module defines an SMTP client session object that can be used to send mail.",
        },
        {
            "url": "https://example.invalid/noise",
            "title": "Unrelated page",
            "snippet": "This page contains random unrelated marketing text with no implementation details.",
        },
    ]
    documents = [
        {
            "document": {
                "url": "https://docs.python.org/3/library/smtplib.html",
                "title": "smtplib documentation",
                "text_excerpt": "This module defines an SMTP client session object. For normal use, connect to a host, authenticate when required, and use TLS/SSL when credentials are sent. The module is part of the Python standard library.",
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
