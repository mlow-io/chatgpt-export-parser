> Note
> This file is the execution runbook. It tells the worker how to operate against `current/plans.md`, how aggressively to proceed, and what validation and documentation discipline is required.

Now execute the current horizon end-to-end.

## Non-Negotiable Rule

- Do not stop after each milestone to ask for confirmation unless blocked by missing external input, missing credentials, or a high-risk product decision that cannot be inferred.

## Execution Rules

- Treat `current/plans.md` as the source of truth.
- Implement one milestone at a time.
- After each milestone:
  - run the listed validation commands,
  - fix failures immediately,
  - update tests when needed,
  - record decisions or discoveries in `current/plans.md`,
  - update `current/documentation.md` so it matches reality.
- Keep diffs scoped and reviewable.
- Prefer correctness and determinism over speculative expansion.
- Default to contract-preserving changes.
- If a schema, CLI, or export contract change becomes necessary, document it explicitly in `current/plans.md` before or with the change and cover it with tests.

## Bug Handling

- If a bug is discovered:
  - reproduce it when feasible,
  - add or identify coverage,
  - fix it,
  - verify the fix,
  - record a short note in `current/plans.md`.

## Completion Criteria

- All active milestones for this horizon are complete.
- Listed validations pass.
- `current/documentation.md` accurately reflects the repo state.

Start by reading `current/plans.md` and executing the next incomplete milestone.
