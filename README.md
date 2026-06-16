# cdac-nesthub v21

## Local development startup

Use this command for local reload mode:

```bash
python dev_server.py
```

`dev_server.py` watches source directories only. Runtime-owned output directories are intentionally excluded:

- `runtime/generated`
- `runtime/traces`
- `runtime/logs`
- `runtime/cache`
- `runtime/registry`
- `runtime/uploads`
- `runtime/downloads`
- `runtime/profiles`
- `runtime/secrets`

Do **not** start the API with this command from the project root:

```bash
uvicorn apps.api.server:app --reload
```

That command watches runtime-generated capability files. During capability acquisition the runtime writes files such as `tool.py`, `test_tool.py`, and `test_contract_smoke.py`; root reload will restart the API while the job is still running.

For maximum stability while testing capability generation, use no-reload mode:

```bash
python main.py
```

## Runtime capability verification

Generated runtime tools are now checked by both execution smoke tests and runtime output contract checks. A tool cannot pass verification only by returning `status=completed`.

The verifier rejects outputs that are copied placeholders or format strings, for example returning `yyyy-mm-dd` as a runtime value when the input format was `YYYY-MM-DD HH:mm`. For declared temporal formats, the returned temporal field must parse according to the requested format.

## Fix: async job runtime failure propagation

This version fixes a lifecycle wrapping bug where the async worker reported
`Async job completed` even when the underlying runtime operation failed.

Key changes:
- Conversation runtime now propagates failed result_verification into the outer response status.
- Async job store normalizes nested runtime verification and implementation status.
- Agent Studio API infers terminal status from verification contracts, not just the outer wrapper.
- Failed capability acquisition now returns a visible failure message instead of a misleading completed status.
- Added tests for runtime failure visibility.

Validation:
- `pytest -q tests/runtime` => 15 passed
