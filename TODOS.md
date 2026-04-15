# Parser Roadmap

## Current Direction

The parser is now oriented around one standard output:

- canonical ChatGPT archive SQLite DB

## Near-Term Follow-Up

1. Keep canonical ingest stable against larger overlapping export sets and additional real-world export oddities.
2. Expand regression coverage for more malformed or sparse export shapes, especially around partial metadata and unusual node graphs.
3. Consider whether `check` should grow optional repair-oriented guidance or remain strictly diagnostic.
4. Continue trimming stale historical docs that no longer help the canonical-only product story.

## Completed

- canonical ChatGPT archive v2 implemented
- run provenance preserved via `runs`, `conversation_runs`, and `message_runs`
- branch-aware graph preserved with `nodes` and `node_children`
- `parse-and-ingest` aligned with canonical archive ingestion
- catalog and old run-scoped product framing demoted/removed from the main story
- regression coverage expanded across query/export/maintenance flows
- dump/restore round-trip repaired for FTS-backed archives
- canonical snapshot marker handling fixed for older non-canonical reimports
- `check` expanded beyond orphan-reference validation
