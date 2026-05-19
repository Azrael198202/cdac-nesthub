# Runtime Secret Resume Persistence Fix

This version fixes delegated resume credential persistence.

## What was wrong

The Agent Studio form posted `provided_inputs`, but the delegation resume path did not forward those values into the primary runtime resume call. As a result, the primary runtime kept the same `secret_input` pending action and the UI displayed the credential dialog repeatedly.

## What changed

- Delegation resume now forwards `provided_inputs` to `_resume_agent_request_with_progress`.
- Agent Studio proactively saves `secret_key/value` through `/api/agent-studio/secret` before resuming the delegated run.
- The primary runtime resume path still saves the same secret as a second durable safeguard.

## Expected result

After entering `OPENAI_API_KEY` and clicking Submit & Continue, `runtime/configs/secrets/secrets.json` is created or updated and the checkpoint resumes instead of showing the same dialog again.
