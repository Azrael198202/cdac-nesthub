# Brain separation boundaries

This version performs the first safe separation step without changing runtime behavior.

## ai_core
Owns the generic runtime operating system:

- input parsing
- intent recognition
- workflow planning
- pre-execution validation
- execution dispatch
- final synthesis
- compatibility facades for older imports

`ai_core` must not contain domain-specific capability logic.

## auxiliary_brain
Owns lifecycle orchestration outside the core runtime:

- capability acquisition
- agent/task creation
- task graph generation
- runtime code generation
- generated asset storage

## repair_brain
Owns repair analysis and repair planning:

- receive structured failure reports
- request filtered evidence
- classify failures
- propose repair ownership and repair steps
- route implementation repair to `auxiliary_brain`

It does not silently patch code without verification.

## verification_brain
Owns result validation:

- validate generic expectations
- detect unresolved template variables
- check required structural fields
- check accepted statuses

It answers: "Is the result acceptable?"

## memory_brain
Owns runtime experience memory:

- failure categories
- repair outcomes
- useful evidence references
- successful/failed repair summaries

It stores experience, not hard-coded business rules.

## evidence_engine
Owns deterministic evidence filtering:

- collect trace/log/artifact snippets by structural identifiers
- reduce large log folders before model analysis
- keep small models away from raw noisy logs

## task_runtime
Owns task runtime lifecycle contracts:

- task revision
- graph revision
- plan revision
- active revision id

Current task execution behavior remains in the existing services; this package defines the forward boundary.
