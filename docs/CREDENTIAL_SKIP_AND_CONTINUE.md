# Credential Skip and Continue

This version changes credential recovery from a single-path input flow into a two-choice continuation flow.

When a credential-protected provider or method is available, the runtime can now:

1. accept the key, save it, and resume the same checkpoint with the credential-enabled method available;
2. skip the credential, mark the provider/method as skipped for the current run, clear the waiting state, and continue with another allowed fallback path.

The UI exposes this as:

- `Submit & Continue` for providing a key;
- `Continue without this key` for skipping the credential-protected method.

The runtime records skip intent under `runtime_execution_preferences`:

```json
{
  "credential_mode": "skip",
  "skip_credential_candidates": true,
  "skipped_secret_keys": ["..."]
}
```

This prevents the same generic credential prompt from being shown repeatedly for the same run.
