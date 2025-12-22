# ChatGPT Export Parser – Data Model & CLI Spec (2025-12)

This document is the authoritative schema and CLI specification for the current parser/ingester. All outputs are run-scoped and machine-consumable.

## Run Outputs & Artifacts
- Per-run directory (default `./normalized_runs/<run_id>/`):
  - JSONL files: `conversations.jsonl`, `nodes.jsonl`, `node_children.jsonl`, `messages.jsonl`, `links.jsonl`, `attachments.jsonl`, `tool_calls.jsonl`, `tool_results.jsonl`
  - `run.json` (metadata: run_id, created_at, input_files, stats, version)
  - `manifest.json` (paths, sizes, record counts, log path, stats)
  - `parser.log` (detailed log)
- Ingested into SQLite (`--db`), mirroring JSONL schema plus `runs` and `meta`.
- FTS: `message_fts` (FTS5) populated on ingest from `messages.text`.

## Common Conventions
- Every row has `run_id` (TEXT) for provenance.
- Timestamps: ISO 8601 UTC (`...Z`).
- JSON objects/lists are stored as JSON strings in SQLite.
- `message_kind`: derived enum (`user_visible_user`, `user_visible_assistant`, `system_context`, `internal_reasoning`, `tool_call`, `tool_result`, `unknown`).
- `time_index`: per-conversation chronological index.

## JSONL / SQLite Schemas

### runs
- `run_id` PK, `jsonl_dir`, `started_at`, `finished_at`, `input_files` (JSON), `stats` (JSON)

### conversations
- `run_id`, `id`, `source_id`, `title`, `created_at`, `updated_at`
- `default_model`, `models_used` (list)
- `is_archived`, `is_starred`, `current_node_id`
- `message_count`, `safe_url_count`, `blocked_url_count`
- `metadata` (JSON), `source_file`

### nodes
- `run_id`, `id`, `conversation_id`
- `parent_id`, `children_ids` (list)
- `message_id`
- `is_root`, `is_in_main_path`
- `depth`, `main_path_index`

### node_children
- `run_id`, `conversation_id`
- `parent_node_id`, `child_node_id`, `child_index`

### messages
- `run_id`, `id`, `node_id`, `conversation_id`
- `role`, `author_name`, `recipient`, `channel`
- `content_type`, `text`, `raw_content` (JSON)
- `created_at`, `updated_at`
- `is_hidden`, `hidden_reason`
- `is_in_main_path`, `main_path_index`, `depth`
- `model`, `metadata` (JSON)
- `time_index` (int), `message_kind` (enum)

### links
- `run_id`, `id`, `conversation_id`, `message_id`
- `source` (message_text, safe_url, blocked_url, etc.)
- `url`, `display_text`, `position_start`, `position_end`
- `scheme`, `domain`, `path`, `query`
- `kind`, `metadata`

### attachments
- `run_id`, `id`, `conversation_id`, `message_id`
- `type`, `filename`, `mime_type`, `filesize_bytes`, `source_ref`
- `metadata` (e.g., dimensions)

### tool_calls
- `run_id`, `id`, `conversation_id`, `message_id`
- `tool_name`, `call_index`
- `arguments_json` (parsed), `raw_arguments`, `metadata`

### tool_results
- `run_id`, `id`, `conversation_id`, `message_id`, `tool_call_id`
- `result_json`, `raw_result`, `metadata`

### meta (DB only)
- `key` PK, `value` (includes `schema_version`)

### message_fts (FTS5)
- `message_id`, `conversation_id`, `run_id`, `role`, `text`

## CLI Surface (Current)
- parse: JSON/zip → JSONL run dir (streaming ON by default; `--no-streaming`; zip supported)
- ingest: JSONL → SQLite (`--mode skip_existing|overwrite`)
- parse-and-ingest: parse then ingest
- query: list/detail
- search: FTS over messages (role/kind/conversation/run filters)
- export-conversation / export-conversations: markdown/text/json; optional `--frontmatter`
- export-bundle: one markdown with TOC (optional HTML/PDF via pandoc + PDF engine), optional `--frontmatter`, `--css`, `--pdf-engine`
- check: integrity
- list-runs / diff-runs
- dump-db / restore-db
- migrate: schema migrations (currently schema_version=3: adds `node_children`, enables FK constraints, rebuilds FTS)

## Run Metadata Examples
`run.json`:
```json
{
  "run_id": "2025-12-05T13-00-15Z",
  "created_at": "2025-12-05T13:00:15Z",
  "input_files": ["conversations.json"],
  "stats": { "conversations": 1104, "messages": 41650, "errors": 0 },
  "version": "0.2.0"
}
```
`manifest.json`:
```json
{
  "run_id": "2025-12-05T13-00-15Z",
  "output_dir": "./normalized_runs/2025-12-05T13-00-15Z",
  "created_at": "2025-12-05T13:00:15Z",
  "log_file": "./normalized_runs/2025-12-05T13-00-15Z/parser.log",
  "run_json": "./normalized_runs/2025-12-05T13-00-15Z/run.json",
  "files": {
    "conversations.jsonl": { "path": "...", "size_bytes": 123, "records": 1104 },
    "messages.jsonl": { "path": "...", "size_bytes": 456, "records": 41650 }
  },
  "stats": { "conversations": 1104, "messages": 41650, "errors": 0, "elapsed": 4.04 }
}
```

## Export Formatting
- Markdown exports (single/batch/bundle) render messages with fenced code blocks to avoid HTML/TeX bleed; optional YAML frontmatter (`--frontmatter`).
- Bundled exports embed default CSS; HTML/PDF via pandoc if available; PDF requires a PDF engine (wkhtmltopdf/weasyprint/prince/chrome/pdflatex).

## Defaults & Behaviors
- Streaming parse ON by default; disable with `--no-streaming`.
- Zip inputs supported (reads `conversations.json` inside).
- `run_id` auto-generated if not provided; outputs live under `./normalized_runs/<run_id>/` by default.
- Logging: stdout INFO unless `--quiet`/`--json`; file logs in run dir for parse/parse-and-ingest.
