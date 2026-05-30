# Verification: registered tool user execution mode policy

Result: passed.

Scenario:
- Runtime-generated capability was sandbox-verified with mock/verify mode.
- After registration, a user/Agent invocation supplied only normal task inputs.
- The user did not supply an execution mode field.
- The registered tool had a runtime-declared execution policy.

Expected behavior:
- Sandbox verification may continue to use mock/verify values.
- Enabled user execution applies registry-declared defaults after approval.
- Actual tool payload contains `mode=send`.
- Tool result proves `external_action_executed=true`.

Validation performed:
- `RuntimeRegisteredToolService.execute_tool()` applied `runtime_execution_policy.confirmed_input_values`.
- A local SMTP protocol server accepted one message via the real smtplib path.
- Result data contained `mode=smtp_send` and `external_action_executed=true`.
- Captured message contained the provided subject and body.
- `python -m compileall ai_core apps auxiliary_brain` passed.

Design note:
- The core does not hardcode SMTP or mail behavior.
- User execution defaults are read from the registered runtime tool specification.
- This keeps the generic Agent/Task parameter form flow intact.
