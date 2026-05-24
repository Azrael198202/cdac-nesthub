# Conversation Context and Memory Design

## Storage split

### Postgres / relational store
Use Postgres for structured, auditable, transactional data.

Tables:

- `sessions`: one conversation lifecycle.
- `turns`: user input, final answer, compact stage results, metadata.
- `session_summaries`: rolling summaries used to keep long conversations stable.
- `feedback`: user quality evaluation for a run.

Local development uses SQLite automatically at:

```text
runtime/sessions/session_memory.sqlite3
```

Production can mirror to Postgres by setting:

```bash
export RUNTIME_POSTGRES_DSN="postgresql://user:password@host:5432/dbname"
```

or:

```bash
export DATABASE_URL="postgresql://user:password@host:5432/dbname"
```

### Vector database / retrieval memory
Use the vector layer for semantic recall.

Stored content should be compact and reusable:

- rolling conversation summary
- approved high-quality answer pattern
- successful repair pattern
- reusable execution pattern
- validated result material

Do not directly store raw long chat logs as knowledge.

Local fallback path:

```text
runtime/knowledge/vector_memory/records.jsonl
```

If Chroma is installed, records are also persisted under:

```text
runtime/knowledge/vector_memory/chroma/
```

## Runtime flow

```text
user message
  ↓
load session context window
  ↓
retrieve vector memory
  ↓
input parsing / intent / planning / execution / output
  ↓
save turn to relational store
  ↓
save rolling summary
  ↓
index compact summary into vector memory
  ↓
return final answer + session boundary status + evaluation prompt
```

## Boundary control

The runtime calculates:

- `turn_count`
- `soft_limit`
- `hard_limit`
- `should_suggest_new_session`
- `should_require_new_session`

When the soft limit is reached, the UI should suggest starting a new session while allowing continuation from the saved summary.

## Feedback promotion

Endpoint:

```text
POST /api/conversation/feedback
```

Payload:

```json
{
  "session_id": "session_xxx",
  "run_id": "conversation_core_xxx",
  "rating": "good",
  "note": "useful result"
}
```

Good feedback promotes the compact summary to local vector memory, not raw chat history.
