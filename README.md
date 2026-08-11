# ChatGPT Export Parser

Local-first Python library and CLI for turning ChatGPT exports into one cumulative, canonical SQLite archive.

This repo now has one primary data story:

- ingest raw ChatGPT export JSON or ZIP files
- merge them into a **canonical ChatGPT archive DB**
- preserve **run provenance** without duplicating the logical conversation/message rows
- keep ChatGPT-native structure (`conversations`, `messages`, `nodes`, `node_children`) so downstream readers stay simple

The canonical archive is the standard output. It is the database AtlasBench GPT should consume directly.

## What It Does

- **Canonical ingest:** overlapping exports merge into one archive instead of creating duplicate conversation copies
- **Full thread fidelity:** keeps ChatGPT-native conversation, message, and branch structure
- **Run provenance:** each ingest still gets a `run_id`, stored in `runs`, `conversation_runs`, and `message_runs`
- **Atomic runs:** if any selected source cannot be completely read, the entire ingest run is rolled back
- **FTS search:** search message text with SQLite FTS5
- **Query and export:** inspect conversations, export them to Markdown/text/JSON, or bundle recent chats
- **Multiple databases:** use any `--db` path you want; separate databases remain separate archives

## Quick Start

This repo includes synthetic demo data.

```bash
# Build a canonical archive from the demo export
chatgpt-parser parse-and-ingest \
  demo/demo_conversations.json \
  --db demo/demo_chatgpt_canonical.db \
  --run-id demo_run

# Search the canonical archive
chatgpt-parser search \
  --db demo/demo_chatgpt_canonical.db \
  --q "Branch"

# Export a conversation to Markdown
chatgpt-parser export-conversation \
  --db demo/demo_chatgpt_canonical.db \
  --conversation-id demo_conv_1 \
  --output my_chat.md
```

`parse-and-ingest` is the standard command. `canonical-ingest` remains as an explicit alias for the same workflow.
The historical `ChatGPT_Export_parser.py` entry point remains for compatibility,
but new automation and applications should use the installed command, the
package module, or the public Python API.

## Installation

No third-party dependencies are required.

```bash
git clone https://github.com/mlow-io/chatgpt-export-parser.git
cd chatgpt-export-parser
python3 -m pip install -e .
chatgpt-parser contract
```

Python 3.10 or newer is required. The package has no runtime dependencies
outside the Python standard library.

## Python Library Contract

Applications should call the public package API rather than importing CLI or
database internals:

```python
from chatgpt_parser import ingest_exports, inspect_inputs, parser_contract

inspection = inspect_inputs(["/path/to/chatgpt-export.zip"])
if inspection.can_ingest:
    result = ingest_exports(
        ["/path/to/chatgpt-export.zip"],
        "/path/to/chatgpt-archive.sqlite3",
    )
    print(result.stats)
```

The versioned native-client contract is available as Python data or JSON:

```bash
python3 -m chatgpt_parser --json contract
python3 -m chatgpt_parser --json inspect-inputs /path/to/export
```

AtlasBench GPT invokes the package module through this machine-readable
process boundary. It does not duplicate export parsing logic and does not call
the legacy `ChatGPT_Export_parser.py` shim.

## Standard Workflow

### 1. Ingest one or more exports into a canonical archive

```bash
chatgpt-parser parse-and-ingest /path/to/conversations.json \
  --db my_chats.db

chatgpt-parser parse-and-ingest /path/to/export.zip \
  --db my_chats.db

chatgpt-parser parse-and-ingest /path/to/october.json /path/to/november.json \
  --db my_chats.db \
  --run-id 2026-04-06T12-00-00Z
```

Behavior:

- the archive dedupes canonical conversations/messages across overlapping exports
- branches inside a conversation are preserved as distinct nodes/edges
- each ingest run is still recorded for provenance
- choosing a different `--db` path creates or extends a different canonical archive
- mixed valid/corrupt selections fail as a unit; callers receive structured `source_results` and the existing archive is preserved

### 2. Search

```bash
chatgpt-parser search --db my_chats.db --q "quantum computing"
```

Optional filters:

- `--role`
- `--kind`
- `--conversation-id`
- `--run-id`

### 3. Query

```bash
chatgpt-parser query --db my_chats.db --type conversations --limit 10

chatgpt-parser query \
  --db my_chats.db \
  --type conversation_detail \
  --conversation-id <UUID> \
  --format json
```

Notes:

- `query --type conversations` accepts `--order-by COLUMN [ASC|DESC]`
- supported `--order-by` columns are conversation columns such as `created_at`, `updated_at`, `latest_message_at`, `message_count`, and related count fields
- invalid `--order-by` values are rejected instead of being interpolated directly into SQL

### 4. Export

```bash
chatgpt-parser export-conversation \
  --db my_chats.db \
  --conversation-id <UUID> \
  --output conversation.md \
  --frontmatter

chatgpt-parser export-conversations \
  --db my_chats.db \
  --query "postgres" \
  --limit 10 \
  --output-dir ./exports
```

Format behavior:

- `--format markdown` renders Markdown
- `--format text` renders plain text
- `--format json` emits a conversation-plus-messages JSON payload for `export-conversation`

### 5. Validate and inspect provenance

```bash
chatgpt-parser check --db my_chats.db --format json
chatgpt-parser list-runs --db my_chats.db
```

`list-runs` is now provenance inspection for the canonical archive, not a separate legacy mode.

`check` verifies more than orphan records. It also validates canonical counts, graph edges, FTS coverage, and canonical snapshot markers.

### 6. Dump and restore

```bash
chatgpt-parser dump-db --db my_chats.db --output my_chats.sql
chatgpt-parser restore-db --input my_chats.sql --db restored_chats.db
```

The dump/restore flow preserves the archive including the FTS-backed search surface.

## Canonical Data Model

The archive keeps ChatGPT-native tables:

- `conversations`
- `messages`
- `nodes`
- `node_children`
- `links`
- `attachments`
- `tool_calls`
- `tool_results`
- `message_fts`

It also adds canonical provenance tables:

- `runs`
- `conversation_runs`
- `message_runs`

Important properties:

- canonical identity is conversation/message based, not `(run_id, id)` based
- `run_id` is preserved for provenance but is not the primary identity
- later exports can supersede earlier truncated snapshots without duplicating the logical conversation row
- branch structure is preserved via `nodes` and `node_children`
- rich content is normalized into the existing schema-v2 tables: text URLs and citation metadata in `links`, image/file references in `attachments`, and linked calls/results in the tool tables
- attachment references remain present with `availability: unresolved` when the export does not include a readable local file; consumers must not fetch remote resources implicitly
- rich rows use stable IDs so overlapping canonical imports update rather than duplicate them

Useful derived conversation fields also live on the canonical `conversations` table:

- `message_count`
- `message_count_main_path`
- `earliest_message_at`
- `latest_message_at`
- role counts
- `keyword_text`
- `summary_text`

## Provenance Model

Each ingest still creates a run record.

- `runs`: one row per ingest invocation
- `conversation_runs`: which canonical conversations were seen in that run, plus the per-run snapshot metadata
- `message_runs`: which canonical messages were seen in that run

This gives you historical visibility without making the main archive run-scoped.

## Why This Replaced The Older Approach

The repo used to carry:

- a run-scoped relational DB as the main output
- a separate lightweight catalog DB

Those are no longer the primary product story.

For a normal ChatGPT-history browser, the right default is:

- one cumulative canonical archive
- no duplicate conversations from overlapping exports
- full thread content and branch fidelity
- run provenance preserved separately

## Data Safety

- Local-first only
- `conversations.json`, `*.db`, `generated/`, and other local artifacts are gitignored
- only synthetic demo content in `demo/` should be committed

## Development & Testing

```bash
python3 -m unittest discover -s tests
```

Useful smoke checks:

```bash
chatgpt-parser parse-and-ingest demo/demo_conversations.json --db demo/demo_chatgpt_canonical.db --run-id demo_run
chatgpt-parser query --db demo/demo_chatgpt_canonical.db --type conversations --limit 2 --format json
chatgpt-parser search --db demo/demo_chatgpt_canonical.db --q "branch" --format json
chatgpt-parser export-conversation --db demo/demo_chatgpt_canonical.db --conversation-id demo_conv_1 --format text
chatgpt-parser check --db demo/demo_chatgpt_canonical.db --format json
```

For deeper schema details, see [SCHEMA_AND_SPEC.md](SCHEMA_AND_SPEC.md) and [CLI_SPEC.md](CLI_SPEC.md).
