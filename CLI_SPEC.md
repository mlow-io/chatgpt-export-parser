# ChatGPT Export CLI – Revised Interface (draft)

This spec captures the short-term CLI surface and DB hooks we need (no GUI/semantic layer). It assumes the current parser/ingester foundations already in `ChatGPT_Export_parser.py`.

## Global Behavior
- Outputs are run-scoped: each `parse`/`parse-and-ingest` creates a run directory with JSONL, `run.json`, `stats.json` (optional), and `parser.log`.
- Provenance: every DB row carries `run_id`; runs table mirrors the on-disk metadata.
- Output controls: `--json` (machine-readable summary), `--quiet`, `--verbose`, `--log-format text|json`.
- Config precedence: CLI flags > env vars (`CHATGPT_EXPORT_DB`, `CHATGPT_EXPORT_OUTPUT_ROOT`, etc.) > config file (`~/.chatgpt_export/config.toml` by default) > hardcoded defaults.
- Config file shape (`config.toml`):
  ```toml
  [defaults]
  db_path = "./chatgpt_export.db"
  output_root = "./normalized_runs"
  export_dir = "./exports"     # optional default for raw export files
  log_format = "text"
  ```
- DB path must always be overrideable via `--db`; no global lock-in.

## Commands & Arguments

### parse
Normalize export JSON → JSONL run dir.
- Positional: `inputs...` (one or more export JSON files or `.zip` containing `conversations.json`).
- Flags: `--output-root DIR` (default `./normalized_runs`), `--output-dir DIR` (must be empty unless `--force`), `--run-id ID`, `--force`, `--no-streaming` (streaming ON by default).
- Output JSON (if `--json`):
  ```json
  {
    "run_id": "2025-12-05T23-15-00Z",
    "jsonl_dir": "./normalized_runs/2025-12-05T23-15-00Z",
    "conversations": 128,
    "messages": 3290,
    "links": 410,
    "attachments": 12,
    "tool_calls": 7,
    "tool_results": 7,
    "elapsed_sec": 14.23
  }
  ```

### ingest
Load an existing JSONL run into SQLite.
- Flags: `--jsonl-dir DIR` (required), `--db PATH` (required), `--mode skip_existing|overwrite` (default `skip_existing`), `--run-id ID` (override).
- Behavior: inserts run metadata into `runs`; bulk inserts rows; optional truncate per-run on `overwrite`.
- Output JSON:
  ```json
  { "status": "ingested", "db": "./chatgpt_export.db", "run_id": "..." }
  ```

### parse-and-ingest
Convenience: runs `parse`, then `ingest`.
- Flags: union of `parse` + `ingest` (db/mode). Streaming ON by default; disable with `--no-streaming`.
- Output JSON: same fields as `parse` plus `db` and `status: "completed"`.

### search (FTS)
Full-text search over messages (requires `message_fts`).
- Flags: `--db PATH` (required), `--q QUERY` (required), `--role ROLE`, `--kind KIND`, `--conversation-id ID`, `--run-id ID`, `--limit N` (default 50), `--offset N` (default 0), `--format json|text`.
- Output JSON: list of hits with `conversation_id`, `message_id`, `created_at`, `role`, `message_kind`, `snippet` (MATCH-highlight optional), `score` (optional).

### query
Structured queries without FTS.
- Flags: `--db PATH`, `--type conversations|conversation_detail`, `--limit N`, `--conversation-id ID`, `--include-hidden true|false`, `--format json|text`, `--order-by FIELD` (optional).
- `conversations` returns a list; `conversation_detail` returns `{ conversation, messages }` (ordered by `time_index`).

### export-conversation / export-conversations
Materialize conversations to Markdown/text (JSON option for single).
- Single: `export-conversation --db PATH --conversation-id ID --format markdown|text|json --output FILE [--frontmatter]`
- Batch: `export-conversations --db PATH --query "fts text" --limit N --format markdown|text --output-dir DIR [--frontmatter]`
- Uses search/filters to pick IDs; exports main-path (or configurable) messages.

### check
Integrity validation.
- Flags: `--db PATH`, `--format json|text`.
- Validates FK-like relations (nodes↔messages, conversations.current_node_id in nodes), PK uniqueness, optional depth/main_path coherence.
- Output JSON: `{ "ok": true }` or `{ "ok": false, "errors": [...] }`.

### list-runs
Enumerate runs.
- Flags: `--db PATH`, `--format json|text`.
- Output: rows from `runs` with `run_id`, `jsonl_dir`, `started_at`, `finished_at`, `input_files`, `stats`.

### diff-runs
Compare two runs by run_id.
- Flags: `--db PATH`, `--run-a ID`, `--run-b ID`, `--format json|text`.
- Output JSON: `{ "only_in_b": [...conversation_ids], "only_in_a": [...], "changed": [{ "conversation_id": "...", "message_count_a": 10, "message_count_b": 12 }] }`.

### dump-db / restore-db
- `dump-db --db PATH --output FILE.sql` (uses `sqlite3 .dump` or internal export).
- `restore-db --input FILE.sql --db PATH` (creates/overwrites target DB).

### migrate
Schema migrations keyed off `meta.schema_version`.
- Flags: `--db PATH`, `--to-version N` (optional; defaults to latest).
- Applies sequential SQL migrations; idempotent if already at target.

## Logging
- Default console: INFO (unless `--quiet` or `--json`).
- File: `parser.log` inside run dir for parse; optional `--log-file PATH` for other commands.
- `--log-format json` switches console/file to JSON logs (fields: `ts`, `level`, `msg`, `run_id`, `command`).

## SQL Starters (FTS + Meta)

Create FTS table (run during migrate/init):
```sql
CREATE VIRTUAL TABLE IF NOT EXISTS message_fts USING fts5(
  message_id UNINDEXED,
  conversation_id UNINDEXED,
  run_id UNINDEXED,
  role,
  text,
  tokenize='unicode61'
);
```

Indexes helpful for queries:
```sql
CREATE INDEX IF NOT EXISTS idx_messages_conv_kind ON messages(run_id, conversation_id, message_kind);
CREATE INDEX IF NOT EXISTS idx_messages_time ON messages(run_id, conversation_id, time_index);
```

Meta table for schema versioning:
```sql
CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT
);
INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', '1'), ('created_at', datetime('now'));
```

Minimal migration sketch (example: version 1 → 2)
```sql
ALTER TABLE messages ADD COLUMN time_index INTEGER;
ALTER TABLE messages ADD COLUMN message_kind TEXT;
-- If upgrading older DBs without run_id, add and backfill:
ALTER TABLE conversations ADD COLUMN run_id TEXT;
ALTER TABLE nodes ADD COLUMN run_id TEXT;
ALTER TABLE messages ADD COLUMN run_id TEXT;
ALTER TABLE links ADD COLUMN run_id TEXT;
ALTER TABLE attachments ADD COLUMN run_id TEXT;
ALTER TABLE tool_calls ADD COLUMN run_id TEXT;
ALTER TABLE tool_results ADD COLUMN run_id TEXT;
CREATE TABLE IF NOT EXISTS runs (...); -- see main schema
UPDATE meta SET value='2' WHERE key='schema_version';
```

FTS ingest hook (during ingest for each message with text):
```sql
INSERT INTO message_fts(message_id, conversation_id, run_id, role, text)
VALUES (?, ?, ?, ?, ?);
```

## Notes for Implementation
- Keep ingestion order: JSONL → DB; FTS rows derive from `messages.text`.
- Keep `run.json` authoritative for `run_id`, `input_files`, `stats`.
- Don’t delete JSONL artifacts; `overwrite` mode only affects DB rows for a run.
- Ensure `--json` outputs are stable and documented for agent consumption.
