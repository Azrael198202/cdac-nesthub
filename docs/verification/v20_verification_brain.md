# v20 Verification Brain

v20 upgrades the verification foundation from a single unresolved-template guard to six generic levels:

1. Template Verification: unresolved `{{...}}` references must not remain in runtime inputs or outputs.
2. Schema Verification: declared required keys and minimum participant result schema must be satisfied.
3. Dependency Verification: selected participants and dependency edges must map to existing runtime results/nodes.
4. Capability Verification: a participant bound to a registered runtime capability must execute through the registered capability path.
5. Expectation Verification: final output/result must not be empty or a placeholder value.
6. Side Effect Verification: side-effect capability results must report success and must not contain unresolved templates.

The verifier is deterministic and domain-neutral. It does not repair code directly. It produces structured checks and feeds RuntimeVerificationFoundation, which writes failure reports and evidence packages under runtime-generated locations during execution.
