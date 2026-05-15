# CDAC NestHub v70.28

## Stability fix: evidence-satisfied short circuit

This version focuses on one critical runtime bug:

> When web evidence already satisfies the request, runtime must bypass generated tool/module execution and go directly to structured materialization and final synthesis.

## Main changes

1. Added `EvidenceSatisfiedShortCircuit`.
2. Fixed credential candidate misclassification.
3. Web evidence strategy now performs secondary discovery if the first discovery path does not materialize a result.
4. Runtime skips generated artifact creation when selected evidence already has sufficient coverage and confidence.
5. Keeps ai_core / runtime generic and domain-neutral. No hardcoded business/domain keywords are added.

## Verified flow

Expected execution order for evidence-sufficient requests:

```text
workflow_planning
↓
execution_strategy = [local_knowledge, web_evidence, tool_generation]
↓
web_evidence
↓
selected_evidence coverage/confidence check
↓
EvidenceSatisfiedShortCircuit
↓
EvidenceDirectAnswerBuilder
↓
ResultMaterial
↓
FinalAnswerSynthesizer
```

Generated modules/tools are skipped when evidence is already sufficient.

## Validation

```text
compileall: OK
pytest: 13 passed
semantic scan: no prohibited domain words found in ai_core/apps
```
