# AGENTS.md

## Product Scope

This repository is the dedicated AtlasBench parser. It converts raw ChatGPT
exports into a canonical, cumulative SQLite archive for AtlasBench GPT. It is
independent of the separate general-purpose `chatgpt-export-parser` repository:
do not merge, publish from, or describe that repository as this project's
upstream by default.

The standard workflow is:

```bash
atlasbench-parser parse-and-ingest /path/to/export.json --db ./my_chats.db
```

`canonical-ingest` is an explicit alias for the same canonical archive workflow.

Keep the boundary narrow:

- The parser owns raw-export interpretation, identity, deduplication, graph
  reconstruction, schema maintenance, and canonical SQLite creation.
- Downstream applications own import orchestration, browsing, presentation,
  app-local notes, and user-requested exports.
- Do not add generic corpus ingestion, cloud services, dashboards, or a second
  primary storage model.

## Current State

Stable records live in:

- `README.md` — product, installation, workflow, and safety
- `CLI_SPEC.md` — versioned command behavior
- `SCHEMA_AND_SPEC.md` — canonical schema and provenance rules
- `TODOS.md` — short ordered follow-up list

Do not create parallel `current/`, prompt, implementation, or generated
documentation stacks. Update the stable records above when behavior changes.

## Code Map

- Package/native API: `chatgpt_parser/api.py`
- CLI entrypoints: `python3 -m chatgpt_parser`, `atlasbench-parser`, and the
  legacy compatibility shim `ChatGPT_Export_parser.py`
- CLI implementation: `chatgpt_parser/cli/`
- Canonical DB logic: `chatgpt_parser/db/canonical_manager.py`, `chatgpt_parser/db/canonical_schema.py`
- Query/export helpers: `chatgpt_parser/core/exporter.py`
- Shared DB helpers: `chatgpt_parser/db/common.py`
- Tests: `tests/`

## Core Rules

- keep the canonical archive as the primary data model
- preserve run provenance, but not as run-scoped primary identity
- preserve branch/node structure inside conversations
- treat source-equivalent conversations as unchanged canonical content:
  record new run provenance without rewriting messages, FTS, or resources
- avoid reintroducing separate first-class run-scoped or catalog product stories
- keep different `--db` paths fully supported as different canonical archives

## Build, Test, and Development Commands

- Contract: `python3 -m chatgpt_parser --json contract` must report
  `implementation_id: "atlasbench-parser"`, contract v1, and canonical schema v2
- Canonical ingest: `python3 -m chatgpt_parser canonical-ingest export.json --db ./chatgpt_export.db`
- Validate: `python3 -m chatgpt_parser check --db ./chatgpt_export.db --format json`
- Tests: `python3 -m unittest discover -s tests`
- Repository privacy: `scripts/check_repository_privacy.sh`
- Candidate-ref privacy: `scripts/audit_ref_privacy.sh <ref>`

## Coding Style

- Python 3, standard library only
- small, direct functions
- snake_case for functions/variables
- preserve machine-readable CLI output behavior
- keep this checkout isolated from a separately installed `chatgpt_parser`
  module; AtlasBench supplies the selected checkout through `PYTHONPATH`

## Commit Guidance

- keep diffs coherent
- update docs when CLI or schema behavior changes
- avoid stale references to removed workflows

## Data Safety

- exports and databases are local-only
- generated DBs and local artifacts should remain gitignored
- only the checked-in synthetic `demo/` fixture is approved as tracked archive-shaped data
- the candidate-ref audit covers reachable tracked paths and text; it does not
  certify commit-author metadata
- the private legacy object graph is quarantined outside this clean checkout;
  never use the quarantine as a push source or publish its refs
