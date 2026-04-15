# ChatGPT Export Parser Long-Horizon Prompt

> Note
> This file is the project contract for the current long-horizon run. It defines what this repo is, what this run is trying to achieve, and what constraints and completion criteria must govern execution.

## Mode

`repair-and-continue`

## Repo Reality Summary

- What the repo currently is:
  A Python 3 standard-library-only CLI that ingests ChatGPT export JSON/ZIP data into a canonical SQLite archive and exposes query, search, export, validation, and maintenance commands.
- What already works:
  Canonical ingest, aliasing through `parse-and-ingest` and `canonical-ingest`, SQLite schema initialization, branch/node preservation, FTS-backed search, single-conversation export, and a passing baseline unittest suite.
- What is partially implemented:
  Some commands exist with lighter test coverage than the core ingest path, the canonical manager still concentrates a large amount of behavior in one module, and the public specs/docs need tighter alignment with implementation details.
- What appears broken, risky, or stale:
  Documentation drift exists in the schema/spec narrative, validation depth is shallow relative to the archive’s invariants, query behavior needs closer safety review, and the CLI surface is not yet covered evenly by tests.

## Current Run Objective

Make the canonical archive workflow robust and production-shaped without inventing a new product direction. The run should harden canonical ingest correctness, deepen regression coverage across the existing CLI surface, tighten safety and consistency in query/export/maintenance behavior, reduce implementation risk through targeted refactors, and align public documentation with the code that actually exists.

## Hard Constraints

- Keep the canonical archive as the primary product and data model.
- Preserve run provenance without turning run-scoped identity back into the main story.
- Preserve conversation branch/node structure and support separate canonical archives via different `--db` targets.
- Preserve machine-readable CLI output behavior unless a tested correction is required.
- Prefer additive or corrective schema and CLI changes over renames or product-direction churn.

## Non-Goals For This Run

- Reintroducing a separate catalog-first or run-scoped primary workflow.
- Rewriting the project around external dependencies, ORMs, or a new packaging/tooling stack.
- Adding speculative new product surfaces unrelated to canonical archive robustness.

## Deliverables

- A `current/` control stack that accurately describes the run and stays updated.
- Expanded regression coverage for ingest, export, query, search, validation, and maintenance commands.
- Hardened canonical archive behavior with clearer invariants and safer CLI handling.
- Refactored high-risk implementation areas with smaller, more testable helpers.
- Updated docs/specs that match repo reality and explicitly describe guarantees and limits.

## Done When

- The next-horizon milestones in `current/plans.md` are complete and validated.
- The unittest suite passes after each milestone and at the end of the run.
- Manual CLI smoke checks cover the canonical ingest/query/search/export/check workflow and relevant maintenance commands.
- Public docs/specs no longer claim behavior or schema details that the code does not implement.

## Risk Reduction Expectations

- Reduce the risk of silent canonical data corruption or ambiguity by expanding validation and invariant coverage.
- Reduce the risk of future regressions by moving behavior from implicit assumptions into tests and clearer module boundaries.

## Execution Start

Read `current/plans.md` first. Treat it as the source of truth for milestone order, validations, and decision logging.
