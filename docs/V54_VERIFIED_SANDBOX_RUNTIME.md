# v54: Verified Sandbox Execution Runtime

## 1. Why previous versions still failed

The main failure was not only tool generation. The earlier runtime depended on `workflow_planning.planned_steps`. If the LLM returned an empty plan, execution stopped with `no_planned_steps`, so API discovery, external solution discovery, tool generation, and web lookup were never triggered.

v54 adds a generic recovery layer:

```text
workflow_planning returns empty planned_steps
  -> PlanningRecoveryService creates a generic runtime capability discovery step
  -> execution can enter external discovery / tool generation / sandbox verification
```

This recovery does not contain domain-specific logic. It only preserves the original user request and moves it into the runtime discovery pipeline.

## 2. New v54 modules

### `ai_core/workflow/planning_recovery.py`

Creates a generic runtime capability-discovery step when the planner returns no executable steps.

### `ai_core/sandbox/verified_sandbox_runtime.py`

Verifies generated runtime tools before registry installation.

Verification order:

```text
static AST / py_compile check
  -> dependency scan
  -> Docker sandbox execution if available
  -> temporary venv execution fallback
  -> safe_to_register only if test passes
```

### `ai_core/security/dependency_scanner.py`

Scans dependency declarations before install or sandbox execution.

Supports:

- static dependency policy checks
- optional `pip-audit` integration if installed
- review-required status for risky dependency declarations

### `ai_core/research/repository_analyzer.py`

Clones GitHub repositories into `runtime/downloads/repositories` as untrusted evidence only.

It analyzes:

- README
- LICENSE / NOTICE
- requirements / pyproject
- top-level file list
- dependency scan result

It does not execute repository code.

### `ai_core/research/model_candidate_evaluator.py`

Evaluates model candidates and produces:

- estimated use cases
- approximate hardware requirement
- download strategy
- license review requirement
- benchmark-before-registration policy

## 3. Execution policy

External code is never directly trusted.

```text
external repo / generated tool / model candidate
  -> evidence collection
  -> license/dependency/hardware analysis
  -> sandbox verification
  -> registry only after verification
```

## 4. What v54 can do now

Given a user request that needs a missing capability, v54 can:

```text
1. preserve the original request
2. recover from empty planner output
3. search external documents / GitHub / model catalogs
4. clone GitHub repos as evidence
5. analyze README / license / dependency files
6. evaluate model candidates and hardware strategy
7. generate runtime tool artifacts
8. verify generated tools in Docker or venv sandbox
9. register only verified tools
10. execute verified tools and attach provenance
```

## 5. Remaining limitations

- Docker execution depends on local Docker availability and image availability.
- If Docker fails, v54 falls back to temporary venv. This is useful but weaker than container isolation.
- Dependency scanning is strongest when `pip-audit` is installed.
- Repo clone is implemented, but repo code is still evidence-only by default.
- Model candidates are evaluated, but automatic model download and benchmark are not yet implemented.
- LLM output quality still affects generated tool quality.

## 6. Suggested v55

v55 should implement:

```text
1. Model download manager
2. Model benchmark runner
3. Automatic model route registration after benchmark
4. Docker image preflight and local image management
5. Full generated-tool integration test suite
6. Human approval policy for installing external repo dependencies
7. Runtime memory of successful external solution patterns
```
