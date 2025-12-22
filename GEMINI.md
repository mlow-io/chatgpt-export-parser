# ChatGPT Export Parser & SQLite Ingester

This project contains a Python script designed to parse, normalize, and ingest ChatGPT data exports into a structured, relational JSONL format and an SQLite database.

## Project Overview

The core of the project is `ChatGPT_Export_parser.py`. It has evolved from a simple parser into a robust CLI tool that manages "runs" of data ingestion.

### Key Features
- **Normalization:** Flattens nested ChatGPT exports into relational entities (`conversations`, `messages`, `nodes`, etc.).
- **SQLite Integration:** Ingests normalized data into a local SQLite database with a typed schema.
- **Run Management:** Tracks ingestion "runs" with metadata (`run.json`) and organizes output in unique directories.
- **Agent-Friendly:** Outputs machine-readable JSON summaries (`--json`) and supports basic CLI querying.

## Usage

The script uses subcommands for different operations.

### 1. Parse (Normalize to JSONL)
Reads raw JSON exports and creates a directory of normalized JSONL files.

```bash
# Auto-generate a run ID and save to ./normalized_runs/<run_id>/
python3 ChatGPT_Export_parser.py parse conversations.json

# Parse directly from a zip export (conversations.json inside)
python3 ChatGPT_Export_parser.py parse export.zip

# Specify an output root
python3 ChatGPT_Export_parser.py parse conversations.json --output-root ./my_runs

# Specify a specific output directory (must be empty)
python3 ChatGPT_Export_parser.py parse conversations.json --output-dir ./clean_data

# Streaming is ON by default; disable if needed
python3 ChatGPT_Export_parser.py parse conversations.json --no-streaming
```

### 2. Ingest (JSONL to SQLite)
Takes an existing normalized directory and loads it into a database.

```bash
python3 ChatGPT_Export_parser.py ingest \
  --jsonl-dir ./normalized_runs/2025-12-05T12-00-00Z \
  --db ./chat_data.db
```

### 3. Parse and Ingest
Does both in one step.

```bash
python3 ChatGPT_Export_parser.py parse-and-ingest conversations.json \
  --db ./chat_data.db \
  --output-root ./runs
```

### 4. Query & Search
Run basic queries or full-text search against the database without leaving the CLI.

```bash
# List recent conversations
python3 ChatGPT_Export_parser.py query --db ./chat_data.db --type conversations --limit 5

# Get details for a specific conversation (JSON format)
python3 ChatGPT_Export_parser.py query \
  --db ./chat_data.db \
  --type conversation_detail \
  --conversation-id <uuid> \
  --format json

# FTS search across message text
python3 ChatGPT_Export_parser.py search --db ./chat_data.db --q "pizza" --limit 20 --format json
```

### 5. Export / Integrity / Diff / Maintenance
```bash
# Export a conversation to markdown (optional YAML frontmatter)
python3 ChatGPT_Export_parser.py export-conversation --db ./chat_data.db --conversation-id <uuid> --output convo.md --frontmatter

# Export a batch selected via FTS (optional YAML frontmatter)
python3 ChatGPT_Export_parser.py export-conversations --db ./chat_data.db --query "postgres" --limit 10 --output-dir ./exports --frontmatter

# Export a bundled markdown (and optional HTML/PDF if pandoc + PDF engine installed)
python3 ChatGPT_Export_parser.py export-bundle --db ./chat_data.db --since-days 9 --output-markdown ./exports/recent_bundle.md

# Integrity check
python3 ChatGPT_Export_parser.py check --db ./chat_data.db --format json

# List and diff runs
python3 ChatGPT_Export_parser.py list-runs --db ./chat_data.db
python3 ChatGPT_Export_parser.py diff-runs --db ./chat_data.db --run-a <run1> --run-b <run2>

# Dump / restore / migrate
python3 ChatGPT_Export_parser.py dump-db --db ./chat_data.db --output backup.sql
python3 ChatGPT_Export_parser.py restore-db --input backup.sql --db ./restored.db --force
python3 ChatGPT_Export_parser.py migrate --db ./chat_data.db
```

### Global Options
- `--json`: Output the result of the command as a JSON object to stdout (useful for scripts/agents).
- `--quiet`: Suppress logs to stdout.
- `--verbose`: Enable debug logging.

## Data Model

### Relational Tables
The data is normalized into the following tables in SQLite (and corresponding JSONL files):

- **runs**: Metadata about the ingestion run.
- **conversations**: Top-level chat metadata.
- **nodes**: Graph structure (tree) of the conversation.
- **node_children**: Parent/child edges for branch reconstruction.
- **messages**: Content (text, code, etc.) linked to nodes. Includes `time_index` and `message_kind`.
- **links**: URLs extracted from messages or conversation metadata.
- **attachments**: Multimodal content references (images, files).
- **tool_calls**: Arguments and metadata for tool usage (e.g., python, browser).
- **tool_results**: Outputs from tools.

### Message Kinds
The parser derives a `message_kind` for easier filtering:
- `user_visible_user`
- `user_visible_assistant`
- `system_context`
- `internal_reasoning` (e.g., o1 thoughts)
- `tool_call`
- `tool_result`

## Schema Documentation
For the detailed field list and CLI spec, refer to `SCHEMA_AND_SPEC.md` and `CLI_SPEC.md`.

## Development Conventions
- **Standard Library Only:** No third-party dependencies (e.g., `pandas`, `sqlalchemy`) are used.
- **Single File:** The entire logic resides in `ChatGPT_Export_parser.py` for easy portability.
- **Idempotency:** Run IDs allow tracking data provenance. `ingest` supports `skip_existing` (default) or `overwrite` modes.

## Workflow Mandate

- **Regular Commits**: After every logical change (refactors, documentation updates, or feature additions), even subtle ones, a git commit MUST be made with a clear, descriptive message.

- **Regular Pushes**: Commits should be pushed to the remote repository promptly to ensure the remote state matches the local progress.



## Roadmap

See `TODOS.md` for the current project backlog and completed features.
