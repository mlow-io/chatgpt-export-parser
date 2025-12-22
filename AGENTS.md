# Repository Guidelines

## Project Structure & Module Organization
- Core CLI/parser: `ChatGPT_Export_parser.py` (all logic: parse → JSONL → ingest → query).
- Docs/specs: `README.md` (quick start + data safety), `GEMINI.md` (overview/usage), `SCHEMA_AND_SPEC.md` (schema + CLI notes), `CLI_SPEC.md` (draft CLI surface), `chat_gpt_export_tool_handoff_spec_v_2.md` (broader app plan).
- Outputs (created at runtime): run-scoped directories under `normalized_runs/<run_id>/` with `*.jsonl`, `run.json`, `parser.log`.

## Build, Test, and Development Commands
- Parse only: `python3 ChatGPT_Export_parser.py parse export.json --output-root ./normalized_runs`.
- Ingest JSONL → SQLite: `python3 ChatGPT_Export_parser.py ingest --jsonl-dir ./normalized_runs/<run_id> --db ./chatgpt_export.db`.
- Parse + ingest: `python3 ChatGPT_Export_parser.py parse-and-ingest export.json --db ./chatgpt_export.db`.
- Query (examples): `python3 ChatGPT_Export_parser.py query --db ./chatgpt_export.db --type conversations --limit 5`.
- Add `--json` for machine-readable summaries; use `--verbose/--quiet` to tune logging.

## Coding Style & Naming Conventions
- Language: Python 3, standard library only (no external deps).
- Style: PEP 8-ish; 4-space indentation; keep functions small and pure where possible.
- Names: snake_case for variables/functions; UpperCamelCase for classes; constants in ALL_CAPS.
- Logging: prefer structured, informative messages; keep user-facing stdout clean when `--json` is used.

## Testing Guidelines
- **Test Suite**: A `unittest` harness exists in the `tests/` directory.
- **Running Tests**: Execute `python3 -m unittest discover -s tests` to run the full suite.
- **Writing Tests**:
  - Prefer lightweight script-based checks that exercise CLI commands against sample exports.
  - Keep fixture exports small and anonymized; store under `tests/fixtures/` if needed (currently using synthetic data in `tests/`).
  - Report expected exit codes and key JSON fields in assertions.

## Commit & Pull Request Guidelines
- Commits: concise, imperative summaries (e.g., “Add FTS search subcommand”, “Refine run metadata write”); group related changes together.
- PRs: include a brief description, key commands run (parse/ingest/query), and any new docs or schema changes referenced. If modifying schema or CLI, link to the relevant doc updates (`CLI_SPEC.md`, schema doc).
- Avoid unrelated formatting churn; preserve existing user changes in the worktree.

## Security & Configuration Tips
- Config precedence: treat CLI flags as authoritative. A config/env precedence scheme is described in `CLI_SPEC.md` but not fully implemented in the current script.
- Never delete JSONL artifacts; `overwrite` should only affect DB rows for a specific run_id.
- Keep exports containing sensitive data local; no network calls are needed for normal operation.
