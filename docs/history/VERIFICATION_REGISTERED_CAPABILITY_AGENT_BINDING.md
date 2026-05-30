# Verification: Registered Capability Agent Binding

## Goal
When a user creates an agent that describes a capability already present in the runtime tool registry, the system must bind the agent to the registered capability instead of regenerating another tool or returning only explanatory text.

## Scenario verified
Instruction:

```text
Create an agent named "SendMail Agent" that can send smtp mail.
```

Expected behavior:

1. Route as agent creation.
2. Inspect runtime tool registry.
3. Bind the agent to the already registered `basic_smtp_mail_sender` capability.
4. Generate an agent parameter contract from the tool input schema.
5. Preserve connection schema, secret schema, and approval policy in the capability profile.
6. Do not execute the mail send action during agent creation.

## Implementation summary

Added:

- `ai_core/runtime/capability/registered_tool_agent_binder.py`

Updated:

- `auxiliary_brain/studio/service.py`
- `auxiliary_brain/delegation/delegation_runtime.py`

## Validation result

### Agent creation

Passed.

Result:

- agent created
- `capability_profile.capability_type = runtime_registered_tool`
- `capability_profile.tool_id = basic_smtp_mail_sender`
- `execution_policy = runtime_registered_tool`
- required runtime parameters are derived from the registered tool input schema

### Task execution with mock runtime profile

Passed.

Flow:

1. Configure runtime tool profile with mock transport.
2. Create `SendMail Agent`.
3. Create a task using that agent.
4. Provide task-run parameters: recipient, subject, body, mode, approval confirmation.
5. Execute task.

Result:

```text
status = completed
final_answer = Runtime capability executed successfully: basic_smtp_mail_sender.
```

### Regression check

Passed.

Instruction:

```text
Create an agent named "Writing Agent" that can write articles.
```

Result:

- agent created normally
- no runtime registered tool was bound
- existing generic agent creation behavior preserved

### Compile check

Passed.

```text
python -m compileall ai_core auxiliary_brain apps
```
