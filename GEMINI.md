# ChatGPT Export Parser

## Repo Reality

This repo now centers on one primary backend:

- the canonical ChatGPT archive SQLite DB

The parser:

- reads ChatGPT export JSON or ZIP files
- preserves full ChatGPT-native conversation structure
- dedupes overlapping exports into one cumulative archive
- keeps run provenance in separate tables

The standard ingest workflow is:

```bash
python3 ChatGPT_Export_parser.py parse-and-ingest /path/to/export.json --db ./my_chats.db
```

`canonical-ingest` is an explicit alias for the same path.

## Key Commands

```bash
python3 ChatGPT_Export_parser.py parse-and-ingest conversations.json --db ./chat_data.db
python3 ChatGPT_Export_parser.py query --db ./chat_data.db --type conversations --limit 5
python3 ChatGPT_Export_parser.py search --db ./chat_data.db --q "pizza" --format json
python3 ChatGPT_Export_parser.py export-conversation --db ./chat_data.db --conversation-id <uuid> --output convo.md
python3 ChatGPT_Export_parser.py check --db ./chat_data.db --format json
python3 ChatGPT_Export_parser.py list-runs --db ./chat_data.db
```

## Data Model

Primary canonical tables:

- `conversations`
- `messages`
- `nodes`
- `node_children`
- `links`
- `attachments`
- `tool_calls`
- `tool_results`
- `message_fts`

Provenance tables:

- `runs`
- `conversation_runs`
- `message_runs`

## Working Assumptions

- canonical archive is the standard output
- different `--db` paths are different canonical archives
- run provenance remains important, but not as the primary data model
- branch structure within a conversation must remain intact
- overlapping exports should merge, not duplicate

## Validation

Run:

```bash
python3 -m unittest discover -s tests
```
