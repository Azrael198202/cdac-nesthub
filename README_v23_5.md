# v23.5 Runtime Artifact Preflight Repair

This version fixes a generic capability acquisition failure path where an LLM-generated runtime artifact can pass static checks but fail or hang during sandbox unit validation.

Changes:

- Added a capability-neutral preflight in `RuntimeBlueprintArtifactGenerator` before generated files are written for registration.
- The preflight imports the generated entrypoint, calls it with the exact `verification_input`, and verifies the result is JSON-serializable.
- If preflight fails, the failure evidence is fed back into the next generation attempt.
- No capability-specific markers or business/domain keyword logic were added to `code_generator.py`.
- The generator boundary scan for Gmail/SMTP/weather/timezone/zoneinfo-specific keywords in `code_generator.py` is clean.

Observed failure from uploaded `generated.zip`:

- Generated `current_time_provider/tool.py` passed compile.
- Sandbox unit test timed out.
- Reproducing the entrypoint showed the generated implementation could not handle its own verification input and returned a non-JSON-native object.
- The failure should have been caught before artifact registration gate; v23.5 adds that generic preflight.
