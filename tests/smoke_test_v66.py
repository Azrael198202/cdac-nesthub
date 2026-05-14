from ai_core.tools.generic_web_extract_artifact import GenericWebExtractArtifactFactory
from ai_core.sandbox.verified_sandbox_runtime import VerifiedSandboxRuntime


def main() -> None:
    artifact = GenericWebExtractArtifactFactory().build_artifact(
        capability="external_information_access",
        candidate={
            "name": "Verified Example Page",
            "url": "https://example.com/example",
            "tool_type": "html_extract",
            "source": "test",
            "evidence": {
                "document": {
                    "text_excerpt": "Example 2026-05-15 Fukuoka detailed evidence 27 C 0 mm"
                }
            },
        },
        evidence_text="Example 2026-05-15 Fukuoka detailed evidence 27 C 0 mm",
    )
    result = VerifiedSandboxRuntime().verify_tool_artifact(
        artifact=artifact,
        test_input={
            "known": {
                "location": "Fukuoka",
                "date": "2026-05-15",
                "detail_level": "detailed",
            }
        },
        allow_network=False,
        timeout_seconds=20,
    )
    assert result["status"] == "passed", result
    assert result["safe_to_register"] is True, result
    print("smoke_test_v66: OK")


if __name__ == "__main__":
    main()
