# ChatGPT Export Parser Handoff Spec (v2)

## Current Standard

This repo’s standard output is the canonical ChatGPT archive DB.

Key properties:

- full ChatGPT-native relational structure
- dedupes overlapping exports across successive ingests
- preserves run provenance separately
- keeps branch/node structure intact

## Standard Command

```bash
python3 ChatGPT_Export_parser.py parse-and-ingest /path/to/export.json --db ./my_chats.db
```

`canonical-ingest` is an alias of the same flow.

## Intended Consumers

The main downstream consumer is AtlasBench GPT, which expects a ChatGPT-native schema:

- `conversations`
- `messages`
- `nodes`
- `node_children`
- `message_fts`

## Provenance Contract

The archive is canonical, but provenance is still available:

- `runs`
- `conversation_runs`
- `message_runs`

This allows later exports to supersede earlier truncated snapshots without making the archive itself run-scoped.

## Non-Goals

- a separate first-class run-scoped database product
- a summary-only catalog database as the main output
- generic workbench-style document/chunk abstractions
