# AtlasBench Parser — Current Handoff

Last verified: 2026-08-29

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

Support the app's staged production archive rebuild and comparison while
preserving the exact validated parser/app pair.

## Verified Validation

- `python3 -m unittest discover -s tests`: 44 tests pass.
- `python3 -m chatgpt_parser --json contract`: implementation
  `atlasbench-parser`, contract v1, package 0.3.0, schema v2, Python 3.10+.
- AtlasBench `scripts/check_parser_contract.sh ~/AtlasBenchGPT-parser`: 44
  parser tests and 58 Swift tests pass against app `3d2cb5e`.
- Repository privacy guard and `audit_ref_privacy.sh HEAD` pass at `570d9cd`.
- Private parser CI passed on Python 3.10 and 3.13 after publication; the paired
  app pull-request CI also passed its privacy, Swift-test, and Xcode-build gate.

## Next Action

Rebuild a new staging archive from the published parser, compare it with the
active archive, and require explicit approval before activation.

## Synchronization Rule

The public `mlow-io/chatgpt-export-parser` repository remains a separate
general-purpose project at the shared historical checkpoint `4eb8e5e`. Changes
in either repository do not appear in the other automatically. Transfer a
general improvement only through an explicit reviewed commit, patch, or
cherry-pick that keeps the AtlasBench contract gate passing.
