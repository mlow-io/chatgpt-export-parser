# ChatGPT Export CLI Spec

This file describes the implemented CLI surface for the canonical ChatGPT archive.

## Product Story

The CLI does one primary thing:

- ingest ChatGPT exports into a canonical SQLite archive

That archive:

- keeps full ChatGPT-native structure
- dedupes overlapping exports
- preserves run provenance
- supports query, search, and export workflows

## Global Options

- `--json`
- `--quiet`
- `--verbose`

## Commands

### contract

Print the versioned Python/native integration contract as JSON.

```bash
python3 -m chatgpt_parser --json contract
```

The payload includes the package version, contract version, canonical schema
version, supported input kinds, and operations. Native clients should reject
unsupported contract versions before starting an import.

### inspect-inputs

Discover canonical JSON sources and diagnostics without changing a database.

```bash
python3 -m chatgpt_parser --json inspect-inputs /path/to/export.zip
```

Inputs may be JSON files, export folders, ZIPs, or `chat.html` diagnostic
targets. `can_ingest` is true only when canonical conversation JSON was found.

### parse-and-ingest

Standard ingest command.

```bash
chatgpt-parser parse-and-ingest /path/to/export.json --db ./my_chats.db
```

Arguments:

- `inputs...`
- `--db PATH` required
- `--run-id ID` optional
- `--mode skip_existing`
- `--no-streaming`
- `--trace-run PATH`

Behavior:

- reads one or more JSON files, split-export folders, or ZIP exports
- parses conversations directly
- merges them into the canonical archive
- records run provenance in `runs`, `conversation_runs`, and `message_runs`
- emits diagnostics for unsupported or incomplete inputs in JSON mode

### canonical-ingest

Explicit alias of `parse-and-ingest`.

Same flags, same behavior, same canonical archive output.

### query

```bash
chatgpt-parser query --db ./my_chats.db --type conversations --limit 10
```

Arguments:

- `--db PATH`
- `--type conversations|conversation_detail`
- `--limit N`
- `--conversation-id ID`
- `--include-hidden true|false`
- `--format json|text`
- `--order-by FIELD [ASC|DESC]`

`--order-by` is allowlisted to conversation columns. Invalid values are rejected.

### search

```bash
chatgpt-parser search --db ./my_chats.db --q "pizza"
```

Arguments:

- `--db PATH`
- `--q QUERY`
- `--role ROLE`
- `--kind KIND`
- `--conversation-id ID`
- `--run-id ID`
- `--limit N`
- `--offset N`
- `--format json|text`

### export-conversation

```bash
chatgpt-parser export-conversation \
  --db ./my_chats.db \
  --conversation-id <UUID> \
  --output out.md \
  --frontmatter
```

Arguments:

- `--db PATH`
- `--conversation-id ID`
- `--format markdown|text|json`
- `--output FILE`
- `--include-hidden true|false`
- `--frontmatter`

Behavior:

- `markdown` emits Markdown
- `text` emits plain text, not Markdown with a different extension
- `json` emits a JSON payload containing `conversation` and `messages`

### export-conversations

Batch export selected conversations.

Arguments:

- `--db PATH`
- `--query TEXT`
- `--limit N`
- `--output-dir DIR`
- `--format markdown|text`
- `--include-hidden true|false`
- `--frontmatter`

### export-bundle

Bundle recent conversations into one Markdown file.

Arguments:

- `--db PATH`
- `--since-days N`
- `--output-markdown FILE`
- `--include-hidden true|false`
- `--frontmatter`

### check

Integrity validation for the canonical archive.

Arguments:

- `--db PATH`
- `--format json|text`

Current checks include:

- orphan `messages` -> `nodes` references
- orphan `nodes` -> `messages` references
- missing `current_node_id`
- broken `node_children` parent/child references
- `conversations.message_count` mismatches
- `conversations.message_count_main_path` mismatches
- missing `message_fts` rows for text-bearing messages
- orphan `message_fts` rows
- invalid `conversation_runs.is_canonical_snapshot` marker state

### list-runs

List canonical ingest runs.

Arguments:

- `--db PATH`
- `--format json|text`

### dump-db

- `--db PATH`
- `--output FILE.sql`

### restore-db

- `--input FILE.sql`
- `--db PATH`
- `--force`

## Notes

- Different `--db` values let users build multiple independent canonical archives.
- Provenance is retained even though the main archive is no longer run-scoped.
- There is no separate first-class catalog workflow in the product story anymore.
- `dump-db` / `restore-db` are intended to round-trip canonical archives including the FTS search surface.
