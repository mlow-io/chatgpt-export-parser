# ChatGPT Export Parser Implementation Plan

> Note
> This file is the operational source of truth for the current horizon. It breaks work into milestones, defines validations, records architecture understanding, and captures decisions as execution progresses.

## Current Status

- Mode: `repair-and-continue`
- Current frontier: horizon complete; future work should build from the expanded suite and verified canonical-archive contract rather than reopening foundational uncertainty.
- Repo state summary: the repo is small, runnable, and testable; the suite covers command-surface behavior, richer canonical invariants, ZIP/streaming parity, dump/restore round-trips, and expanded integrity checks; docs/specs have been aligned to the verified implementation.
- Biggest risks right now:
  - future real-world export oddities may still expose sparse metadata or unusual graph shapes
  - the canonical ingest path remains the highest-risk area for future regressions even after refactoring

## Verification Checklist

Core commands to keep current:
- [ ] build / dev command verified
- [ ] lint command verified
- [ ] typecheck command verified
- [x] test command verified: `python3 -m unittest discover -s tests`
- [x] any repo-specific validation command verified: demo CLI smoke workflow completed for ingest, query, search, export-conversation, check, list-runs, dump-db, and restore-db

Last verified:
- 2026-04-15: `python3 -m unittest discover -s tests`
- 2026-04-15: demo smoke workflow against a temporary DB built from `demo/demo_conversations.json`
- 2026-04-15: clean-room workflow verified across ingest, query, search, export-conversation, export-conversations, export-bundle, check, list-runs, dump-db, and restore-db

Notes:
- There is no dedicated build, lint, or typecheck command currently defined in repo docs or config. If such commands are added during the horizon, update this checklist and validate them.

## Milestones

### Milestone 01 - Baseline Reality And Drift Inventory
Scope:
- create the `current/` control stack
- baseline the test suite
- inventory command surface, schema surface, and documented claims
- record concrete implementation-vs-doc drift and identify the first high-risk correctness areas

Key files/modules:
- `current/prompt.md`
- `current/plans.md`
- `current/documentation.md`
- `README.md`
- `CLI_SPEC.md`
- `SCHEMA_AND_SPEC.md`
- `chatgpt_parser/cli/main.py`
- `chatgpt_parser/db/canonical_schema.py`
- `chatgpt_parser/db/canonical_manager.py`

Acceptance criteria:
- `current/` files exist and describe the real repo
- baseline test results are recorded
- initial drift findings and first execution priorities are documented
- the next incomplete milestone is explicit

Verification commands:
- `python3 -m unittest discover -s tests`

### Milestone 02 - Expand Regression Matrix For Existing CLI Surface
Scope:
- add tests for under-covered commands and edge cases
- deepen coverage for JSON vs ZIP ingest, streaming parity, export variants, maintenance commands, and provenance surfaces
- convert currently implicit canonical invariants into explicit tests

Key files/modules:
- `tests/test_canonical_ingest.py`
- `tests/test_cli_integration.py`
- `tests/test_search_and_check.py`
- new test modules as needed under `tests/`

Acceptance criteria:
- regression coverage materially expands beyond happy-path ingest/search/export
- the existing CLI surface has direct tests for user-facing commands and edge cases
- failing or ambiguous behavior is captured before refactors proceed

Verification commands:
- `python3 -m unittest discover -s tests`

### Milestone 03 - Harden Canonical Ingest And Schema Invariants
Scope:
- fix correctness issues exposed by the expanded regression net
- tighten canonical conversation/message snapshot behavior
- verify provenance, FTS population, node-child integrity, counts, and deterministic ingest semantics
- make only justified additive/corrective schema changes

Key files/modules:
- `chatgpt_parser/db/canonical_manager.py`
- `chatgpt_parser/db/canonical_schema.py`
- `chatgpt_parser/db/common.py`
- tests under `tests/`

Acceptance criteria:
- canonical ingest behaves correctly for overlapping exports and structural edge cases
- provenance tables and canonical tables agree on expected invariants
- any schema changes are additive/corrective, tested, and documented

Verification commands:
- `python3 -m unittest discover -s tests`
- repo-local CLI smoke commands against a temporary DB

### Milestone 04 - Tighten Query Export Search And Maintenance Behavior
Scope:
- review and harden query safety, export consistency, search behavior, and maintenance command reliability
- preserve the public CLI story while correcting unsafe or ambiguous behavior
- make output behavior clearer and more consistent where needed

Key files/modules:
- `chatgpt_parser/cli/main.py`
- `chatgpt_parser/cli/commands.py`
- `chatgpt_parser/core/exporter.py`
- `chatgpt_parser/db/maintenance.py`
- tests under `tests/`

Acceptance criteria:
- query/search/export/maintenance commands have tested, predictable behavior
- machine-readable output remains stable or is changed only for a correctness fix with updated tests/docs
- high-risk unsafe behavior is eliminated

Verification commands:
- `python3 -m unittest discover -s tests`
- targeted manual smoke commands per touched command

### Milestone 05 - Refactor High-Risk Implementation Areas
Scope:
- split concentrated logic into smaller helpers without changing product direction
- isolate graph analysis, content extraction, row assembly, and/or validation helpers where justified
- reduce the amount of behavior hidden inside one large ingest path

Key files/modules:
- `chatgpt_parser/db/canonical_manager.py`
- `chatgpt_parser/core/parser.py`
- `chatgpt_parser/utils/`
- tests under `tests/`

Acceptance criteria:
- the code is easier to reason about and review
- behavior remains covered by tests before and after refactors
- any legacy or duplicate logic is clearly demoted or removed if no longer part of the main canonical path

Verification commands:
- `python3 -m unittest discover -s tests`

### Milestone 06 - Strengthen Validation And Operational Confidence
Scope:
- expand `check` coverage and/or its implementation to catch more archive integrity failures
- add clean-room smoke workflows for ingest, query, search, export, bundle, provenance, dump, and restore
- verify the operational story from an empty temp directory forward

Key files/modules:
- `chatgpt_parser/db/maintenance.py`
- `ChatGPT_Export_parser.py`
- `demo/`
- tests under `tests/`

Acceptance criteria:
- integrity validation detects more than orphan-record cases
- end-to-end smoke coverage exercises the real CLI workflow
- clean-room archive creation and maintenance operations succeed repeatably

Verification commands:
- `python3 -m unittest discover -s tests`
- clean-room CLI smoke workflow

### Milestone 07 - Align Docs Specs And Durable Run State
Scope:
- update README/spec docs to match implemented behavior
- record additive or contract-changing decisions explicitly
- leave the repo with concise, accurate operator-facing documentation

Key files/modules:
- `README.md`
- `CLI_SPEC.md`
- `SCHEMA_AND_SPEC.md`
- `TODOS.md`
- `current/documentation.md`
- `current/plans.md`

Acceptance criteria:
- docs no longer claim fields, commands, or behaviors the code does not implement
- contract-preserving changes vs contract-changing changes are explicit
- the repo can be resumed by a future worker with minimal ambiguity

Verification commands:
- `python3 -m unittest discover -s tests`
- documentation spot-check against current code

## Risk Register

1. Canonical invariants are under-specified in tests.
- Why it matters:
  Regressions in dedupe, provenance, node topology, or counts could silently corrupt the archive while the suite still passes.
- Mitigation:
  Expand the regression matrix before invasive fixes or refactors.

2. Docs and schema notes drift from implementation details.
- Why it matters:
  Future work can be guided by false assumptions, especially around CLI contract and table fields.
- Mitigation:
  Record drift early, then update public docs only after tests and implementation are stable.

3. `canonical_manager.py` concentrates too much behavior.
- Why it matters:
  High-complexity modules make correctness fixes and future review riskier.
- Mitigation:
  Refactor after expanding coverage, keeping helpers small and behavior-preserving.

4. User-facing CLI commands outside the main ingest flow are lightly covered.
- Why it matters:
  Export, bundle, dump/restore, and list-runs can regress even if ingest still passes tests.
- Mitigation:
  Add direct tests and smoke checks for each user-facing command surface.

## Architecture Overview

### Current architecture
- `ChatGPT_Export_parser.py` is a thin shim into `chatgpt_parser.cli.main`.
- `chatgpt_parser/cli/main.py` defines the command surface and dispatches into command/maintenance/export helpers.
- `chatgpt_parser/db/canonical_manager.py` owns schema initialization plus most canonical ingest behavior and row-writing logic.
- `chatgpt_parser/db/canonical_schema.py` defines the SQLite schema and indexes.
- `chatgpt_parser/core/exporter.py` renders single and multi-conversation exports.
- `chatgpt_parser/db/maintenance.py` provides integrity checks and dump/restore/list-runs helpers.

### Stable boundaries
- The canonical archive is the primary product output.
- CLI entrypoint and package structure are already coherent.
- Standard-library-only Python is a deliberate repo constraint.

### Known drift or weak spots
- Remaining weak spots are mostly future-facing rather than active horizon blockers: more malformed exports, more sparse metadata cases, and more unusual node graph shapes.

### Intended next-state evolution
- Keep the same product story and command family.
- Turn current assumptions into tests and explicit invariants.
- Refactor concentrated implementation areas only after the regression net is stronger.
- Update docs after behavior is verified, not before.

## Implementation Notes And Decision Log

- 2026-04-15 / Milestone 01:
  - Decision:
    Use `repair-and-continue` mode rather than `continue`.
  - Why:
    The repo is functional, but docs/specs and verification depth are not yet strong enough to support safe aggressive iteration.
- 2026-04-15 / Milestone 01:
  - Decision:
    Preserve the canonical archive CLI story by default and treat schema/CLI contract changes as exceptions that require explicit justification.
  - Why:
    The stated run objective is robustness and production-shaping, not a new product direction.
- 2026-04-15 / Milestone 01:
  - Decision:
    Baseline testing starts with `python3 -m unittest discover -s tests`.
  - Why:
    It is the only repo-defined automated verification command currently present and it passes on the starting state.
- 2026-04-15 / Milestone 01:
  - Decision:
    Treat Milestone 01 as complete after verifying a real CLI smoke workflow against the demo fixture, not just the unittest suite.
  - Why:
    The horizon needs an operator-level baseline before changing behavior.
- 2026-04-15 / Milestone 01:
  - Decision:
    Use `demo_conv_1` and `demo_conv_2` as the documented demo conversation IDs in future smoke examples unless examples are changed to derive IDs dynamically.
  - Why:
    A guessed conversation ID failed during manual smoke testing even though the export command itself worked, which shows the docs should be more concrete.
- 2026-04-15 / Milestone 02:
  - Decision:
    Add direct tests for `export-conversations`, `export-bundle`, `list-runs`, and `dump-db`/`restore-db` before deeper refactors.
  - Why:
    These were existing user-facing commands with lighter coverage than the core ingest path.
- 2026-04-15 / Milestone 02:
  - Decision:
    Treat `message_fts` as a logical virtual table during restore instead of replaying raw FTS shadow-table internals from `iterdump`.
  - Why:
    The original dump/restore path failed on real round-trips because the FTS restore sequence was not portable.
- 2026-04-15 / Milestone 02:
  - Decision:
    Restrict `query --order-by` to an allowlisted conversation-column contract with optional `ASC`/`DESC`.
  - Why:
    Raw string interpolation into `ORDER BY` was an unnecessary safety and correctness risk.
- 2026-04-15 / Milestone 02:
  - Decision:
    Make `export-conversation --format text` and `export-conversations --format text` use a dedicated plain-text renderer.
  - Why:
    A text format flag that silently emitted markdown was a contract mismatch.
- 2026-04-15 / Milestone 02:
  - Decision:
    Fix SQLite connection lifetime explicitly in maintenance helpers and in the canonical ingest test helper.
  - Why:
    Expanded verification surfaced unclosed-connection warnings that obscured signal and indicated real cleanup gaps.
- 2026-04-15 / Milestone 03:
  - Decision:
    Preserve the existing canonical snapshot marker when ingesting an older non-canonical run.
  - Why:
    The previous implementation could erase which run actually backed the canonical conversation snapshot.
- 2026-04-15 / Milestone 03:
  - Decision:
    Expand regression coverage for rich extraction paths and ingest modes.
  - Why:
    Links, attachments, tool rows, ZIP input, and streaming parity were part of the product surface but not directly protected by tests.
- 2026-04-15 / Milestone 03:
  - Decision:
    Extend `check` to verify graph edges, conversation counts, FTS coverage, and canonical snapshot marker consistency.
  - Why:
    Orphan-record checks alone were too weak for a canonical archive intended to be a durable SQLite source of truth.
- 2026-04-15 / Milestone 05:
  - Decision:
    Split `ingest_conversation()` into named helper stages for message collection, conversation-row assembly, node upserts, edge upserts, and message upserts.
  - Why:
    The function had become the main concentration point for canonical ingest behavior, which made future correctness work riskier than necessary.
- 2026-04-15 / Milestone 07:
  - Decision:
    Update README and spec docs only after the clean-room workflow and expanded test suite were both green.
  - Why:
    The public contract should trail verified behavior, not lead it.
- 2026-04-15 / Milestone 07:
  - Decision:
    Treat the horizon as complete after a clean-room archive round-trip matched conversations, messages, and FTS search hits before and after restore.
  - Why:
    That exercised the full canonical archive workflow, including the repaired dump/restore path.
