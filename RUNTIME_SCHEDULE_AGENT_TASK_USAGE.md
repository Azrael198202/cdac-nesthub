# Agent Scheduled Task Runtime

This runtime supports scheduled task execution without hard-coding a specific agent, capability, or task name.

## Execution model

A task remains an ordinary immediate task unless its task graph contains a structural `schedule_policy`:

```json
{
  "enabled": true,
  "mode": "recurring",
  "interval_seconds": 60,
  "next_run_at": "...",
  "controller_participant_ids": ["..."]
}
```

When a user manually executes such a task, the runtime activates the schedule and returns `scheduled`. The generic runtime scheduler loop then scans durable task graphs and dispatches only the payload participants when `next_run_at` becomes due.

## Non-hardcoded boundary

The scheduler does not know the names or meanings of any agent or capability. It only reads the structural schedule policy and excludes controller participants declared by `controller_participant_ids`.

## Behavior

- Normal tasks without `schedule_policy` execute immediately.
- Scheduled tasks execute their payload steps only when due.
- Controller steps are not re-executed during scheduled payload dispatch.
- Each scheduled dispatch uses its own runtime state run id, so background runs do not overwrite `studio_runtime`.
- The scheduler starts as runtime infrastructure and remains idle when no enabled recurring task exists.

## Operator notes

A paused `studio_runtime` entry in Runtime State Console means a previous interactive run is waiting for input or verification. It does not by itself prove that the scheduler is stopped. Check `runtime/traces/scheduled_tasks/scheduler.jsonl` or Graph Runtime schedule history for `scheduled_task_due`, `dispatch_started`, and `dispatch_completed` events.
