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
  - canonical ingest flow refactored into smaller helper stages without changing tested behavior
  - README, CLI spec, schema notes, and roadmap docs aligned with the verified implementation
  - clean-room workflow verified across ingest, query, search, export, validation, provenance listing, dump, and restore
- In progress:
  - none
- Remaining frontier:
  - future incremental hardening only; the current horizon is complete

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
  - future real-world exports may still expose edge cases not represented by the synthetic fixtures
  - canonical supersession/deduping remains the highest-sensitivity behavior for future changes

## Known Issues

- No active blocker was left open in this horizon.
- Future work should assume real export variability is still the main remaining risk surface.

## Recommended Next Actions

- Use the expanded suite and `check` behavior as the baseline for any future canonical-archive changes.
- Prefer additive hardening for new real-world export shapes over any shift away from the canonical-only product story.
