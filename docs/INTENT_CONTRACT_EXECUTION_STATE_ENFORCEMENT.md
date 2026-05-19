# Intent Contract Execution State Enforcement

This version strengthens the runtime boundary between upstream understanding and downstream execution.

## Changes

- The locked intent contract is now written into runtime state and workflow results.
- Each planned step receives an execution method decision before execution.
- Downstream workflow normalization cannot replace the upstream intent family.
- Runtime-native contracts cannot silently fall back to external evidence.
- External-information contracts cannot be executed by runtime-native observation tools.
- Local knowledge checks only run when the resolved method permits knowledge execution.
- Multi-candidate web/API fallback is blocked unless the execution contract explicitly allows it.

## Runtime Flow

```text
input_parsing
  -> intent_recognition
  -> intent_contract
  -> workflow_planning
  -> workflow_intent_guard
  -> execution_method_proposal
  -> execution_method_decision
  -> execution contract enforcement
  -> tool/API/web/runtime execution
  -> evidence quality validation
  -> output
```

## Design Rule

Models may propose execution methods, but runtime contracts make the final decision. Later stages can refine earlier results, but they cannot replace the locked intent semantics.
