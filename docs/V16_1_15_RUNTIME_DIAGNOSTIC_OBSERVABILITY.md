# V16.1.15 Runtime Diagnostic Observability

## Fixed

- The UI run id is now used as the ai_core conversation correlation id when Agent Studio provides a client run id.
- Capability acquisition, planner model attempts, fallback, sandbox validation, registry, and final events are now visible under the same run scope.
- Heartbeat updates no longer overwrite the current semantic stage.
- Current Run now follows the newest correlated runtime event instead of a stale parent event.
- Planner model events include duration, timeout, attempt id, model id, model source, prompt stage, reason, and diagnosis.
- Runtime Console auto-scroll follows only when the user is already near the bottom. Manual scrolling is no longer forced back to the bottom on each refresh.

## Planner failure diagnosis

A local planner attempt can fail quickly when the provider returns an empty response, thinking text, or prose instead of a JSON object. The runtime now records this as an exact failure reason such as `model_returned_non_json`, with the attempt duration and timeout limit. The deterministic blueprint fallback is then shown explicitly as the next stage when enabled.

## Boundary

The fix is observability/correlation only. It does not add business-specific capability logic to ai_core.
