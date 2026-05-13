# v53: Verified External Capability Discovery Runtime

## Goal

v53 extends v52 from API-only discovery to a broader runtime discovery loop:

```text
user request
  -> generic intent/workflow planning
  -> capability gap detection
  -> external evidence discovery
  -> web/document/API/repository/model candidate collection
  -> runtime tool/module/model-route generation proposal
  -> sandbox/static verification
  -> registration only after verification
  -> execution with provenance
```

## What changed

### 1. External solution discovery

Added:

```text
ai_core/research/external_solution_discovery.py
```

This component searches for external evidence at runtime:

- generic web documentation and guides
- public repository candidates
- markdown/README-like documents
- candidate model catalog entries

It writes traces under:

```text
runtime/traces/external_solution_discovery/
runtime/generated/external_discovery_requests/
runtime/downloads/external_candidates/
```

The engine is domain-neutral. It does not know any fixed business topic, API provider, model name, or task-specific workflow.

### 2. Repository and model candidates are evidence, not trusted code

The discovery result includes a safety policy:

```json
{
  "external_code_is_untrusted": true,
  "direct_execution_allowed": false,
  "must_verify_in_sandbox_before_registration": true,
  "must_preserve_license_and_source_provenance": true,
  "model_download_requires_explicit_policy_or_human_approval": true
}
```

GitHub repositories and model catalog entries are not executed or installed automatically.
They are passed to the runtime LLM/code-generation route as evidence.

### 3. Runtime tool generation receives broader evidence

`ToolCallExecutor` now sends both:

```json
{
  "api_discovery": {},
  "external_solution_discovery": {}
}
```

to `RuntimeToolArtifactGenerator`.

This lets runtime generation use:

- API documentation
- external implementation examples
- README/Markdown instructions
- model candidates
- license/source provenance

while still keeping `ai_core` free of business logic.

### 4. Sandbox/static verifier

Added:

```text
ai_core/tools/sandbox_verifier.py
```

The verifier currently checks:

- Python syntax
- `py_compile`
- blocked imports/calls for obviously unsafe behavior
- manifest-level review flags

This is a generic preflight gate, not a complete OS sandbox.

### 5. Tool generation safety prompt strengthened

`RuntimeToolArtifactGenerator` now instructs the model:

- treat external code as untrusted evidence
- do not blindly copy or execute external code
- preserve source/license provenance
- generate the smallest safe adapter
- use documentation evidence for parameters, authentication, response shape, and verification

## Expected result

For a request that requires real external data or missing capability, v53 should be able to:

1. detect a missing runtime capability;
2. search external sources for candidate APIs, code, docs, and models;
3. collect evidence and trace it;
4. generate a runtime tool from evidence;
5. verify the artifact before registration;
6. execute it if safe;
7. return result, provenance, and blocked reasons if verification fails.

## Important limitation

v53 does not yet perform fully isolated container execution. It performs static and compile-time verification. Real sandbox execution should be added in the next version.
