# AtlasBench Parser — Current Handoff

Last verified: 2026-08-31

## Product Identity

This is the independent private parser dependency for AtlasBench GPT. Its
machine-readable contract identifies it as `atlasbench-parser`. It is not a
branch, distribution, or automatically synchronized copy of the public
general-purpose parser.

## Checkpoints

- Validated local implementation: `570d9cd` on `main`
- Published private `origin/main` contains implementation `570d9cd` and its
  documentation successors.
- Paired AtlasBench app implementation: `3d2cb5e` on
  `codex/parser-contract-hardening`
- Published app branch contains implementation `3d2cb5e` and its documentation
  successors.

The complete cross-repository gate tested parser `570d9cd` with app `3d2cb5e`.
Documentation-only reconciliation commits may follow those implementations
without changing the tested code pair.

## Active Goal

Establish evidence-backed compatibility for materially different ChatGPT export
representations while preserving the exact validated parser/app pair until a
verified adapter is ready.

## Compatibility Work

- Local commit `e3a7874` adds the content-free structural profiler (`profile-input`
  / `profile_export`) and synthetic privacy tests. It does not change canonical
  schema v2, ingest semantics, or any payload adapter.
- The profiler accepts one explicitly selected local input, never writes a
  database or extracts an archive, and emits only opaque labels, sanitized
  member handles, hashes, structural statistics, safe enums, findings, and a
  structural fingerprint.
- No real export has been profiled or ingested for this compatibility work.
- JSONL is detected only to report it as unsupported; no authoritative evidence
  currently supports JSONL as a ChatGPT export payload.

## Verified Validation

- `python3 -m unittest discover -s tests`: 50 tests pass at `e3a7874`.
- `python3 -m chatgpt_parser --json contract`: implementation
  `atlasbench-parser`, contract v1, package 0.3.0, schema v2, Python 3.10+.
- AtlasBench `scripts/check_parser_contract.sh` passes with the local profiler
  commit: 50 parser tests and 58 Swift tests pass against app `3d2cb5e`.
- AtlasBench `scripts/check_parser_contract.sh ~/AtlasBenchGPT-parser`: 44
  parser tests and 58 Swift tests pass against app `3d2cb5e`.
- Repository privacy guard and `audit_ref_privacy.sh HEAD` pass at `570d9cd`.
- Private parser CI passed on Python 3.10 and 3.13 after publication; the paired
  app pull-request CI also passed its privacy, Swift-test, and Xcode-build gate.

## Next Action

Obtain one exact user-supplied export path and acquisition date, run only the
content-free profiler with an opaque label, inspect the generated report for
leakage, then classify its packaging and payload evidence before proposing any
adapter or staging ingest.

## Synchronization Rule

The public `mlow-io/chatgpt-export-parser` repository remains a separate
general-purpose project at the shared historical checkpoint `4eb8e5e`. Changes
in either repository do not appear in the other automatically. Transfer a
general improvement only through an explicit reviewed commit, patch, or
cherry-pick that keeps the AtlasBench contract gate passing.
