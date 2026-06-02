# v16.1.12 Progress Detail Observability

This update improves runtime acquisition observability without adding domain-specific logic to ai_core.

## Changes

- Current Run card now shows one structured progress view:
  - workflow name
  - progress percent
  - current stage
  - current action
  - elapsed time
  - last event
  - status
- Runtime Console rows are embedded below the Current Run card and update from structured runtime events.
- Capability acquisition events now carry run_id, stage_index, total_stages, action, and console_message.
- TemplateResolver -> BlueprintPlanner -> ArtifactGenerator path explicitly reports source/fallback status.
- SandboxValidator emits sub-events for validation cases instead of only `running`.
- VerificationRun emits explicit start/end events.
- Stage elapsed warning appears after long-running stages.
- Existing final/timeout recovery behavior is preserved.

## Validation

- python compileall passed.
- apps.api.server import passed.
- verify_agent_studio_progress_state_recovery passed.
- verify_blueprint_capability_pipeline passed.
