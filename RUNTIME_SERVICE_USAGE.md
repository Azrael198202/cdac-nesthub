# Runtime Service On-Demand Creation

This version adds a generic runtime-service layer for background workers.

## Concepts

- Capability: implements a callable runtime function.
- Agent: wraps a capability or behavior for user-facing use.
- Task: defines a workflow graph.
- Runtime service: long-running background runtime infrastructure that can monitor persisted state and dispatch due work.

The runtime service layer is generic. The built-in service type provided here is `durable_task_dispatcher`, which starts the existing durable task runner and dispatches recurring task graphs when their schedule policy becomes due.

## Commands

Create a runtime service:

```text
Create runtime service named Durable Task Dispatcher.
```

Start it:

```text
Start runtime service Durable Task Dispatcher.
```

List services:

```text
List runtime services.
```

Stop it:

```text
Stop runtime service Durable Task Dispatcher.
```

## Recommended scheduled workflow

Create the task that should run repeatedly:

```text
Create a task named SendTimeMailTask.

Execution policy:
run every 60 seconds.

Step 1:
Call Time Agent.

Step 2:
Call SendGMail Agent.
Parameters:
- to: example@example.com
- subject: Current Time
- body: {{Step1.final_answer}}
```

If no dispatcher service is running, the system returns a runtime service suggestion.
Then create/start the service:

```text
Create runtime service named Durable Task Dispatcher.
Start runtime service Durable Task Dispatcher.
```

The service will scan durable task graphs and dispatch due tasks in the background.
