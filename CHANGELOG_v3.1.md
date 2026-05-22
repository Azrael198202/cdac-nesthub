# cdac-nesthub v3.1 update summary

## Updated pipeline

The runtime source now defines a domain-neutral ten-stage pipeline:

1. input_parsing
2. intent_recognition
3. requirement_completion
4. context_awareness
5. workflow_planning
6. pre_execution_validation
7. execution
8. result_verification
9. feedback_repair
10. final_synthesis

The stage contract is centralized in `ai_core/pipeline/stage_contract.py`.

## Key changes

- Added explicit stage boundary contracts: owner, allowed decisions, forbidden decisions, output key, executor type.
- Updated runtime bootstrap to generate the ten-stage workflow from the centralized contract.
- Removed domain-specific structured provider example from source config.
- Added `tools/validate_source_package.py` to verify syntax, stage order, runtime-output exclusion, and forbidden domain terms.
- Removed runtime-generated folders from the source package. Runtime still generates required node/prompt/schema/adapter files during `RuntimeBootstrap().ensure()`.

## Validation

Run:

```bash
python tools/validate_source_package.py
```

Expected result:

```json
{"ok": true}
```
