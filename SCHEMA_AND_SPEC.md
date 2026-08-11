# ChatGPT Export Parser – Canonical Schema & CLI Notes

This repo now standardizes on one SQLite output:

- the **canonical ChatGPT archive DB**

The archive is ChatGPT-native and cumulative:

- logical conversation/message identity is canonical
- `run_id` is preserved for provenance, but not used as the primary identity
- overlapping exports dedupe and merge into one archive
- branch structure stays explicit through `nodes` and `node_children`

## Canonical Archive Properties

`parse-and-ingest` and `canonical-ingest` both write the same DB shape.

Key rules:

- one logical row per canonical conversation
- one logical row per canonical message
- run provenance stored separately in dedicated tables
- later exports can supersede older truncated snapshots
- identical source snapshots add run provenance without rewriting canonical
  messages, FTS entries, or rich-resource rows
- different `--db` targets produce different canonical archives

## Common Conventions

- timestamps are ISO 8601 UTC
- JSON objects/lists are stored as JSON strings in SQLite
- every major row still carries `run_id` for provenance/debuggability
- `message_kind` is derived as one of:
  - `user_visible_user`
  - `user_visible_assistant`
  - `system_context`
  - `internal_reasoning`
  - `tool_call`
  - `tool_result`
  - `unknown`

## Tables

### runs

One row per ingest invocation.

- `run_id` PRIMARY KEY
- `started_at`
- `finished_at`
- `input_files` JSON
- `stats` JSON

### conversations

Canonical conversation rows.

- `id` PRIMARY KEY
- `run_id`
- `source_id`
- `title`
- `created_at`
- `updated_at`
- `earliest_message_at`
- `latest_message_at`
- `default_model`
- `models_used`
- `is_archived`
- `is_starred`
- `current_node_id`
- `message_count`
- `message_count_main_path`
- role counts
- `safe_url_count`
- `blocked_url_count`
- `summary_text`
- `keyword_text`
- `metadata`
- `source_file`

`metadata.source_fingerprint` is an internal SHA-256 fingerprint of the raw
conversation object. It is used only to recognize identical reimports; archives
created before this field existed are rewritten once and then gain the fast
path on later identical runs.

### conversation_runs

Per-run conversation snapshots and provenance.

- `run_id`
- `conversation_id`
- snapshot metadata such as message counts and timestamps
- `imported_at`
- `is_canonical_snapshot`

### nodes

Canonical conversation graph nodes.

- `conversation_id`
- `id`
- `run_id`
- `parent_id`
- `message_id`
- `is_root`
- `is_in_main_path`
- `depth`
- `main_path_index`

### node_children

Explicit branch edges.

- `conversation_id`
- `parent_node_id`
- `child_node_id`
- `child_index`
- `run_id`

### messages

Canonical messages.

- `conversation_id`
- `id`
- `run_id`
- `node_id`
- `role`
- `author_name`
- `recipient`
- `channel`
- `content_type`
- `text`
- `raw_content`
- `created_at`
- `updated_at`
- `is_hidden`
- `hidden_reason`
- `is_in_main_path`
- `main_path_index`
- `depth`
- `model`
- `metadata`
- `time_index`
- `message_kind`

### message_runs

Per-run message provenance.

- `run_id`
- `conversation_id`
- `message_id`
- `imported_at`

### links

- `id`
- `conversation_id`
- `message_id`
- `run_id`
- `source`
- `url`
- `display_text`
- `position_start`
- `position_end`
- `scheme`
- `domain`
- `path`
- `query`
- `kind`
- `metadata`

### attachments

- `id`
- `conversation_id`
- `message_id`
- `run_id`
- `type`
- `filename`
- `mime_type`
- `filesize_bytes`
- `source_ref`
- `metadata`

### tool_calls

- `id`
- `conversation_id`
- `message_id`
- `run_id`
- `tool_name`
- `call_index`
- `arguments_json`
- `raw_arguments`
- `metadata`

### tool_results

- `id`
- `conversation_id`
- `message_id`
- `tool_call_id`
- `run_id`
- `result_json`
- `raw_result`
- `metadata`

### message_fts

SQLite FTS5 table over canonical message text.

- `message_id`
- `conversation_id`
- `run_id`
- `role`
- `text`

### meta

- `key`
- `value`

## CLI Surface

### Standard ingest

`parse-and-ingest`

- input: one or more ChatGPT export JSON or ZIP files
- output: canonical archive DB
- required: `--db`
- optional: `--run-id`
- optional: `--mode skip_existing`
- optional: `--no-streaming`

### Explicit alias

`canonical-ingest`

Same behavior and flags as `parse-and-ingest`.

### Query/search/export

- `query`
- `search`
- `export-conversation`
- `export-conversations`
- `export-bundle`
- `check`
- `list-runs`
- `dump-db`
- `restore-db`

Behavior notes:

- `query --type conversations` only accepts allowlisted `--order-by` values
- `export-conversation --format text` and `export-conversations --format text` emit plain text, not Markdown
- `check` validates archive counts, graph edges, FTS coverage, and canonical snapshot markers in addition to basic orphan references

## Canonical Notes

- The canonical archive is the preferred and standard DB shape.
- `list-runs` remains useful because provenance is still real, just no longer the primary data model.
- You can keep multiple canonical archives simply by choosing different `--db` paths.
- Branches are not deduped away. Branch/node structure inside a conversation remains intact.
- Successive overlapping exports dedupe only where they represent the same logical conversation/message identity.
- A later non-canonical run must not clear the existing canonical snapshot marker in `conversation_runs`.
- `dump-db` / `restore-db` preserve the FTS-backed search surface as part of the canonical archive workflow.
