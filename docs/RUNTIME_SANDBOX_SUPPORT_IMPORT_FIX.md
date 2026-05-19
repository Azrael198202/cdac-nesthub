# Runtime Sandbox Support Import Fix

This version fixes sandbox verification for runtime-generated artifacts that need generic runtime support modules.

## Problem

Generated artifacts are written into a temporary sandbox directory. When an artifact imports a generic support module from `ai_core`, the temporary runner cannot resolve that package unless the project source root is exposed to the sandbox.

## Fix

- Temporary venv verification now prepends the project source root to `PYTHONPATH`.
- Docker verification mounts the project source root read-only at `/project` and sets `PYTHONPATH=/project`.
- The generic web extraction artifact was also made more self-contained for value-alias expansion, reducing unnecessary imports during verification.

## Design rule

The generated artifact can use generic runtime support, but domain-specific behavior must still come from runtime payloads, generated schemas, contracts, and workflow state.
