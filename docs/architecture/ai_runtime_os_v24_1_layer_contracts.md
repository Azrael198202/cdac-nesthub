# AI Runtime OS v24.1 Layer Contracts

This document is the code-facing boundary map for the runtime.

## Core rule
`ai_core` is a generic brain and runtime operating system. It must not contain fixed business functions, generated user values, or capability-specific shortcuts. Runtime capabilities are generated, registered, executed, verified, and repaired outside fixed core logic.

## Layer order
1. perception
2. input_parsing
3. intent_recognition
4. requirement_completion
5. context_awareness
6. workflow_planning
7. pre_execution_validation
8. execution
9. result_verification
10. feedback_repair
11. final_synthesis

The executable source of truth is `ai_core/architecture/layer_contracts.py`.

## Model route rule
Each brain requests a model by `brain`, `task_type`, and `complexity`. Code must not hard-code a concrete provider/model in business logic. Policy chooses the provider/model.

## Verification rule
Run:

```bash
python tools/verify_v24_1_runtime_layer_contracts.py
```

This verifies layer order, forbidden late-stage replanning, and the absence of configured forbidden business terms in core brain source roots.
