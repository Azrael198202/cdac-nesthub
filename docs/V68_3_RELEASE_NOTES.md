# v68.3 Runtime Credential Optional Upgrade

## Main changes

1. Credential-protected candidates no longer block execution by default.
2. The runtime evaluates no-key candidates and public web/evidence extraction first.
3. Credential input is treated as an optional upgrade path.
4. If credential-protected candidates are reached, the UI contract is English-only and provides two actions:
   - `continue_without_key`
   - `provide_credential`
5. Secret fields are represented as UI-ready `secret_fields` and should be rendered as password/secret inputs.
6. Choosing `continue_without_key` resumes the workflow while skipping credential-protected candidates.
7. Choosing `provide_credential` stores the secret via the runtime secret store and resumes execution.
8. Optional credential interactions are separated from required human information.
9. `waiting_optional_upgrade` is emitted instead of incorrectly returning a final failure.
10. ZIP packaging keeps only the latest version markdown files and excludes runtime-generated artifacts.

## UI contract example

```json
{
  "type": "credential_optional_upgrade",
  "title": "Optional API Key Available",
  "message": "A credential-protected provider may improve the result. You can provide an API key or continue without it.",
  "required": false,
  "secret_fields": [
    {
      "name": "credential",
      "label": "API Key / Credential",
      "interaction_type": "secret",
      "required": false,
      "placeholder": "Paste API key here"
    }
  ],
  "actions": [
    {
      "id": "continue_without_key",
      "label": "Continue without API key"
    },
    {
      "id": "provide_credential",
      "label": "Provide API key and continue"
    }
  ]
}
```

## Packaging policy

The source package keeps current source/config/schema files and removes runtime artifacts such as:

- `runtime/generated/`
- `runtime/traces/`
- `runtime/downloads/`
- `runtime/cache/`
- `runtime/tmp/`
- `__pycache__/`
- `*.pyc`

Historical version markdown files are removed from the ZIP.
