# cdac-nesthub v68.4

Runtime source package with final answer synthesis and evidence-supported trust evaluation.

# CDAC NestHub Runtime Source v68.3

This package contains the full source tree for v68.3.

## v68.3 focus

- No-key candidates are evaluated first.
- Credential-protected candidates are optional upgrades, not default blockers.
- The optional API key UI contract is English-only.
- Users can either continue without an API key or provide one and resume execution.
- Runtime-generated artifacts are excluded from the source ZIP.
- Historical version markdown files are excluded; only current version documentation is kept.

See `V68_3_RELEASE_NOTES.md` for details.


## Current Version: v69/v70 Runtime Model Governance

This package includes the merged v69/v70 changes:

- runtime context reduction
- prompt budget management
- generic model response cache
- provider-neutral token usage logging
- universal runtime-configured model adapter
- timeout and latency telemetry
- no provider-specific adapter files in `ai_core`

See `V69_70_RUNTIME_MODEL_GOVERNANCE_RELEASE_NOTES.md` for details.
