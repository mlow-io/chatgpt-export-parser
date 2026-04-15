# ChatGPT Export Parser Documentation

> Note
> This file is the live operator guide and current-state log. It should stay concise, factual, and aligned with the real repo as work progresses.

## Mode

`repair-and-continue`

## What This Project Is

- A local-first Python CLI for converting ChatGPT export JSON/ZIP files into a canonical SQLite archive.
- A repo whose primary product story is the canonical archive, with query, search, export, provenance inspection, and maintenance commands around that archive.

## Current State

- Complete:
  - canonical archive ingestion exists and is the main workflow
  - baseline unittest suite passes on the starting state
  - `current/` long-horizon control stack has been created
  - real CLI smoke workflow verified for ingest, query, search, export-conversation, check, and list-runs using the demo fixture
  - regression coverage expanded for multi-export, bundle export, run listing, and dump/restore round-trips
  - dump/restore round-trip repaired for FTS-backed archives
  - `query --order-by` safety tightened and plain-text export behavior corrected
  - SQLite connection warnings removed from the verified test run
  - canonical snapshot marker handling fixed for older non-canonical reimports
  - regression coverage expanded for rich extraction paths plus ZIP and streaming ingest parity
  - `check` now validates counts, FTS coverage, graph edges, and canonical snapshot markers in addition to orphan-record cases
- In progress:
  - Milestone 05/07 work: internal refactor cleanup and docs/spec alignment
- Remaining frontier:
  - refactor concentrated ingest code into smaller helpers without changing behavior
  - strengthen clean-room workflow confidence and final end-to-end validation
  - align docs/specs with verified implementation

## How To Run

- Canonical ingest:
  `python3 ChatGPT_Export_parser.py parse-and-ingest /path/to/export.json --db ./chatgpt_export.db`
- Query:
  `python3 ChatGPT_Export_parser.py query --db ./chatgpt_export.db --type conversations --limit 5`
- Search:
  `python3 ChatGPT_Export_parser.py search --db ./chatgpt_export.db --q "pizza"`
- Validate:
  `python3 ChatGPT_Export_parser.py check --db ./chatgpt_export.db --format json`

## How To Verify

- Automated suite:
  `python3 -m unittest discover -s tests`
- Repo-local smoke workflow:
  ingest demo data, then exercise `query`, `search`, `export-conversation`, `check`, and `list-runs` against a temporary DB

## Repo Structure Overview

- `ChatGPT_Export_parser.py`: thin CLI shim
- `chatgpt_parser/cli/`: command parsing and command handlers
- `chatgpt_parser/db/`: canonical schema, ingest manager, maintenance helpers, shared DB utilities
- `chatgpt_parser/core/`: exporter plus older parsing support code
- `tests/`: current regression coverage
- `current/`: long-horizon control stack for this run

## Architecture Notes

- Stable:
  - canonical archive is the source of truth
  - CLI shape is small and understandable
  - repo uses Python standard library only
- Evolving:
  - test coverage breadth across the full CLI surface
  - validation depth for archive integrity
  - internal decomposition of the canonical ingest implementation
- Risky or unclear:
  - exact boundary between “documented guarantee” and “current behavior” is not fully explicit yet
  - some spec/schema details drift from live code
  - canonical supersession/deduping edge cases still need more explicit coverage than the operational command surfaces now have

## Known Issues

- `SCHEMA_AND_SPEC.md` documents at least one field not present in the live schema (`message_runs.created_at`).
- `chatgpt_parser/db/canonical_manager.py` remains a concentrated implementation hotspot.
- Demo export examples should be more explicit about valid conversation IDs; the verified demo branching conversation ID is `demo_conv_1`.

## Recommended Next Actions

- Refactor concentrated ingest helpers while keeping the now-expanded suite green.
- Update public docs/specs so they reflect verified command behavior, the repaired dump/restore path, and stronger integrity checks.
