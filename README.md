# ChatGPT Export Parser & SQLite Ingester

Parse ChatGPT export JSON into normalized JSONL and a queryable SQLite database. This repo ships with a small **synthetic demo export** and a matching demo database so you can try the pipeline without using personal data.

## Quick Start (Demo)

```bash
# Parse + ingest the demo export into the included demo DB
python3 ChatGPT_Export_parser.py parse-and-ingest \
  demo/demo_conversations.json \
  --db demo/demo_chatgpt_export.db \
  --output-dir demo/normalized_runs/demo_run \
  --run-id demo_run \
  --force

# Run a sanity check
python3 ChatGPT_Export_parser.py check --db demo/demo_chatgpt_export.db --format json

# Search
python3 ChatGPT_Export_parser.py search --db demo/demo_chatgpt_export.db --q "Branch" --format json
```

## Production Usage (Your Own Export)

```bash
python3 ChatGPT_Export_parser.py parse-and-ingest /path/to/conversations.json --db ./chatgpt_export.db
```

## Data Safety

- This repo is configured to **ignore real exports and DBs** by default.
- `.gitignore` excludes `conversations.json`, `chatgpt_export.db`, and `normalized_runs/` to prevent PII from being committed.
- The `demo/` directory contains synthetic, non-personal data and is safe to commit.

## Repository Structure

- `ChatGPT_Export_parser.py`: CLI + parser + ingester (single file).
- `demo/`: synthetic export, demo database, and demo JSONL run.
- `tests/`: minimal `unittest` suite.
- `GEMINI.md`, `SCHEMA_AND_SPEC.md`, `CLI_SPEC.md`: docs/specs.

## GitHub Setup (Summary)

1) Create an empty repo on GitHub.
2) Add it as a remote:

```bash
git remote add origin <YOUR_GITHUB_REPO_URL>
```

3) Commit and push:

```bash
git add .
git commit -m "Initial import"
git push -u origin main
```

If you want, I can wire the remote and push once you share the repo URL.
