# Task Execution Types

The runtime supports two task execution types.

## One-shot task

A task without a durable `schedule_policy` is a one-shot task.

Command:

```text
Execute task TaskName
```

Behavior:

- Executes the task immediately.
- Does not persist or activate any schedule.
- Every execution is a new manual run.

## Scheduled task

A task with a durable `schedule_policy` is a scheduled task.

Command:

```text
Execute task TaskName
```

Behavior:

- Activates or refreshes the schedule.
- Does not execute the payload immediately unless a due tick is reached by the runtime scheduler.

Additional commands:

```text
Pause task TaskName
Resume task TaskName
Run task TaskName now
```

Behavior:

- `Pause task` sets `schedule_policy.enabled=false`.
- `Resume task` sets `schedule_policy.enabled=true` and refreshes `next_run_at` if needed.
- `Run task now` executes the payload steps once without changing the durable schedule.

The scheduler is generic. It uses only `task.schedule_policy` and controller participant ids; it does not depend on concrete agent names, capability names, or business-domain words.
