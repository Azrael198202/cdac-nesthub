# v68.1 no-key priority runtime update

## Main changes

- API key is not mandatory by default.
- No-key candidates and public web extraction are evaluated first.
- Credential-protected candidates become an optional upgrade only after no-key execution paths fail.
- Added direct evidence fallback: if generated adapters fail but verified no-key evidence already covers runtime parameters, the runtime can synthesize a valid result without asking for a key.
- Added optional API key interaction contract with choices:
  - continue_without_key
  - provide_credential
  - skip_protected_candidates
- Workflow should not return a waiting message as final answer when a usable no-key answer exists.
- ai_core remains domain-neutral; no business-specific terms were added.

## Verification

- python compileall ai_core: OK
- ai_core business keyword scan for weather/Fukuoka/forecast: OK
