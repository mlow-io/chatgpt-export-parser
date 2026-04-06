# Parser Roadmap

## Current Direction

The parser is now oriented around one standard output:

- canonical ChatGPT archive SQLite DB

## Near-Term Follow-Up

1. Keep canonical ingest stable against larger overlapping export sets.
2. Expand tests around supersession/deduping when a later export extends an existing conversation.
3. Tighten export/query ergonomics for canonical-only workflows.
4. Remove any remaining stale references to older run-scoped or catalog-first language.

## Completed

- canonical ChatGPT archive v2 implemented
- run provenance preserved via `runs`, `conversation_runs`, and `message_runs`
- branch-aware graph preserved with `nodes` and `node_children`
- `parse-and-ingest` aligned with canonical archive ingestion
- catalog and old run-scoped product framing demoted/removed from the main story
