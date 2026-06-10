# AI Core Boundary Import Migration

## Purpose

This update moves active imports for non-ai_core implementation modules to the corresponding auxiliary_brain packages while keeping ai_core facade wrappers for backward compatibility.

## Import migration rules

| Old import namespace | New import namespace |
|---|---|
| ai_core.artifacts | auxiliary_brain.artifacts |
| ai_core.dependencies | auxiliary_brain.dependencies |
| ai_core.environment | auxiliary_brain.environment |
| ai_core.media | auxiliary_brain.media |
| ai_core.models | auxiliary_brain.models |
| ai_core.modules | auxiliary_brain.runtime_modules |
| ai_core.providers | auxiliary_brain.providers |
| ai_core.research | auxiliary_brain.research |
| ai_core.sandbox | auxiliary_brain.sandbox |
| ai_core.tools | auxiliary_brain.runtime_tools |
| ai_core.runtime.capability | auxiliary_brain.runtime.capability |
| ai_core.runtime.scheduler | auxiliary_brain.runtime.scheduler |
| ai_core.runtime.observability | auxiliary_brain.runtime.observability |
| ai_core.runtime.self_repair | auxiliary_brain.runtime.self_repair |
| ai_core.runtime.generated_execution | auxiliary_brain.runtime.generated_execution |
| ai_core.runtime.external_runtimes | auxiliary_brain.runtime.external_runtimes |
| ai_core.runtime.learning | auxiliary_brain.runtime.learning |

## Changed scope

Imports were updated in application layer, auxiliary_brain internal modules, repair_brain compatibility modules, and ai_core modules that still need to call delegated runtime services.

## Compatibility policy

The old ai_core paths are still kept as facade wrappers. This means old external code can still import ai_core.* during the transition, but internal project imports now prefer auxiliary_brain for implementation-level modules.

## Validation

- compileall passed for ai_core, auxiliary_brain, apps, and repair_brain.
- Import smoke test passed for:
  - apps.api.server
  - auxiliary_brain.delegation.delegation_runtime
  - auxiliary_brain.studio.service
  - ai_core.executors.tool_call_executor
  - ai_core.orchestration.workflow_runtime
- No remaining direct imports from the moved ai_core namespaces were found.
