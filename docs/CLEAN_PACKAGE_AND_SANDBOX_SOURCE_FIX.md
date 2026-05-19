# v2.9.13 Clean Package and Sandbox Source Fix

This package fixes the clean-source packaging rule that accidentally removed the source package `ai_core/sandbox`.

Rules:
- Keep source code package: `ai_core/sandbox/`
- Exclude runtime generated sandbox workspaces: `runtime/sandbox/`, temporary runtime outputs, traces, checkpoints, caches, and secrets
- Exclude Python bytecode/cache artifacts: `__pycache__/`, `*.pyc`, `*.pyo`

Reason:
`ai_core.modules.autonomous_codegen_executor` imports `ai_core.sandbox.verified_sandbox_runtime`. The source package must be included even though runtime sandbox output directories must be excluded.
