# cdac-nesthub 9.0 Session UI Fix2

This package contains the session UI runtime fixes.

## Main fixes

- Fixed API startup error by importing `SessionMemoryStore` in `apps/api/server.py`.
- Added screen-testable session operations: create session, list sessions, switch session, keep active `session_id`, feedback promotion, and context boundary warning.
- Added runtime data reset script for clean local tests.
- Removed generated runtime artifacts, Python caches, and old markdown changelog files from the package.

## Reset test data

```bash
python scripts/reset_runtime_data.py --yes --include-runtime-generated
```

The script clears only runtime session/vector/generated test data under the project runtime directory. If `RUNTIME_POSTGRES_DSN` or `DATABASE_URL` is configured, it also truncates the runtime memory tables.
