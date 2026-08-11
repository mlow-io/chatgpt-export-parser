# Repository Guidelines

## Product Scope

This repo is a ChatGPT export parser whose primary output is a canonical SQLite archive.

The standard workflow is:

```bash
python3 ChatGPT_Export_parser.py parse-and-ingest /path/to/export.json --db ./my_chats.db
```

`canonical-ingest` is an explicit alias for the same canonical archive workflow.

## Project Structure

- CLI entrypoint: `ChatGPT_Export_parser.py`
- CLI implementation: `chatgpt_parser/cli/`
- Canonical DB logic: `chatgpt_parser/db/canonical_manager.py`, `chatgpt_parser/db/canonical_schema.py`
- Query/export helpers: `chatgpt_parser/core/exporter.py`
- Shared DB helpers: `chatgpt_parser/db/common.py`
- Tests: `tests/`

## Core Rules

- keep the canonical archive as the primary data model
- preserve run provenance, but not as run-scoped primary identity
- preserve branch/node structure inside conversations
- avoid reintroducing separate first-class run-scoped or catalog product stories
- keep different `--db` paths fully supported as different canonical archives

## Build, Test, and Development Commands

- Canonical ingest: `python3 ChatGPT_Export_parser.py parse-and-ingest export.json --db ./chatgpt_export.db`
- Query: `python3 ChatGPT_Export_parser.py query --db ./chatgpt_export.db --type conversations --limit 5`
- Search: `python3 ChatGPT_Export_parser.py search --db ./chatgpt_export.db --q "pizza"`
- Export: `python3 ChatGPT_Export_parser.py export-conversation --db ./chatgpt_export.db --conversation-id <uuid> --output convo.md`
- Validate: `python3 ChatGPT_Export_parser.py check --db ./chatgpt_export.db --format json`
- Tests: `python3 -m unittest discover -s tests`
- Repository privacy: `scripts/check_repository_privacy.sh`
- Candidate-ref privacy: `scripts/audit_ref_privacy.sh <ref>`

## Coding Style

- Python 3, standard library only
- small, direct functions
- snake_case for functions/variables
- preserve machine-readable CLI output behavior

## Commit Guidance

- keep diffs coherent
- update docs when CLI or schema behavior changes
- avoid stale references to removed workflows

## Data Safety

- exports and databases are local-only
- generated DBs and local artifacts should remain gitignored
- only the checked-in synthetic `demo/` fixture is approved as tracked archive-shaped data
- never push all refs or publish the local `legacy-main` history without a separate history audit
