# ChatGPT Export Viewer – Handoff Spec (v2)

This document describes the goals and architecture for a local ChatGPT export viewer. It covers:
- Normalization of ChatGPT exports
- Storage in JSONL and SQLite
- FastAPI backend
- React + Electron desktop frontend
- Coordination / launch expectations

## 1. Overall Goal

Normalize ChatGPT export JSON into a clean, queryable dataset and wrap it in a small desktop app so we can:
- Point at a directory of ChatGPT export JSON files.
- Normalize each run into JSONL files.
- Ingest those JSONL files into a lightweight SQL database (SQLite) for querying.
- Expose the data via a FastAPI backend.
- Explore conversations and analytics via a React UI, packaged as an Electron app.

Important constraint: **Every run must still emit JSONL files** into an output directory (per run) even though SQLite is our primary query store. JSONL is a first-class artifact, not a temporary scratch format.

## 2. Data / Storage Model

### 2.1 Normalized Entities

We normalize the raw ChatGPT export into the following logical entities:

- `conversations`
- `nodes` (the graph from `mapping`)
- `messages`
- `links`
- `attachments`
- `tool_calls`
- `tool_results`

These are written both to:
- JSONL files (one file per entity, one JSON object per line), and
- Corresponding SQLite tables with essentially the same schema.

### 2.2 JSONL Output

Per run, we create an output directory (e.g. `normalized/<timestamp>/` or user-provided) containing:

- `conversations.jsonl`
- `nodes.jsonl`
- `messages.jsonl`
- `links.jsonl`
- `attachments.jsonl`
- `tool_calls.jsonl`
- `tool_results.jsonl`
- `stats.json`
- `parser.log`

This directory is **retained per run** as an immutable snapshot. The app should never silently overwrite or discard JSONL artifacts unless explicitly configured to do so.

### 2.3 SQLite Schema

We also maintain a SQLite database that mirrors the JSONL schema. Tables:

- `conversations`
- `nodes`
- `messages`
- `links`
- `attachments`
- `tool_calls`
- `tool_results`

Each table has reasonable primary keys and foreign keys:

- `conversations(id PRIMARY KEY, ...)`
- `nodes(id PRIMARY KEY, conversation_id REFERENCES conversations(id), ...)`
- `messages(id PRIMARY KEY, node_id REFERENCES nodes(id), conversation_id REFERENCES conversations(id), ...)`
- `links(id PRIMARY KEY, conversation_id, message_id, ...)`
- etc.

Suggested indexes:

- `messages(conversation_id, main_path_index)`
- `messages(conversation_id, created_at)`
- `links(conversation_id)`
- `links(domain)`
- `nodes(conversation_id)`
- `tool_calls(conversation_id)`
- `tool_results(tool_call_id)`

### 2.4 Parser → JSONL → DB Pipeline

Refactor the existing Python parser into a library with the following behavior:

- Input: one or more ChatGPT export JSON files (each is a list of conversations).
- For each run:
  1. Create a new output directory (or use a specified one) and write JSONL files as we normalize the data.
  2. Ingest those same normalized rows into SQLite.

The pipeline should treat JSONL as a first-class log of what was ingested:
- SQLite is built from JSONL, not the original export directly (this makes re-ingestion, migration, and debugging easier).

Support dedupe / incremental behavior:
- Use `conversations.id` as the primary key.
- On ingestion, either:
  - `INSERT OR IGNORE` to skip existing conversations, or
  - Allow an explicit `--overwrite` mode that deletes and reinserts rows for that conversation.

We also want provenance fields (e.g. `source_file`, `source_index`) and per-run identifiers so we can trace which JSONL run a given DB row came from.

## 3. FastAPI Backend

### 3.1 Responsibilities

- Manage configuration/state:
  - Export directory/directories.
  - Path to the SQLite DB.
  - Path pattern for JSONL output directories.
- Expose parse/import operations:
  - Kick off a parse job for selected export files.
  - Track job status and stats.
- Expose read APIs for:
  - Conversations list/search.
  - Conversation detail (messages, links, branches).
  - Links and basic analytics.

### 3.2 Example Endpoints

Config/system:
- `GET /config` – return current configuration (export dir, db path, jsonl output root).
- `POST /config` – set config.

Jobs/import:
- `POST /jobs/parse` – body includes `{ export_dir, files?, jsonl_output_dir? }`.
  - Creates a new JSONL output directory for the run if not specified.
  - Invokes the parser to write JSONL + ingest into SQLite.
  - Returns a `job_id` and the JSONL run directory.
- `GET /jobs/{job_id}` – return state, progress, and aggregated stats.

Data queries:
- `GET /conversations` – paginated list with filters (q, date range, min message count).
- `GET /conversations/{id}` – metadata + messages, optionally links and attachments.
- `GET /conversations/{id}/links` – links for a conversation.
- `GET /links` – global link queries (by domain, date range, etc.).
- `GET /stats/overview` – high-level stats (totals, distribution of message counts, top domains).

The backend should never modify or delete JSONL outputs. All mutating operations are confined to SQLite.

## 4. React + Electron Frontend

### 4.1 Electron Responsibilities

- Package the React UI as a desktop app.
- Provide system dialogs for directory picking:
  - Export directory.
  - Optional DB path.
  - Optional JSONL output root.
- Spawn and manage the FastAPI backend process locally:
  - On app start, launch backend (Python/uvicorn) with config (DB path, default output root).
  - Wait until a `/health` check passes.
  - Gracefully terminate backend on app exit.

### 4.2 React UI Views

Key screens:

1. **Setup / Configuration**
   - Pick export directory (directory picker via Electron IPC).
   - Pick or confirm DB location.
   - Pick or confirm JSONL output root directory.
   - Save configuration (POST /config).

2. **Import / Jobs**
   - Select which export files to parse (list files in export dir).
   - Trigger `POST /jobs/parse`.
   - Show job status and basic stats for each run.
   - Show link to the JSONL output directory for each run.

3. **Conversation List**
   - Table of conversations with filters and sorting.
   - Columns: title, created_at, message_count, duration, model, etc.
   - Clicking a row goes to conversation detail.

4. **Conversation Detail**
   - Metadata pane.
   - Main chat view for the main path messages.
   - Option to toggle hidden/branch messages.
   - Side tab for links and attachments.

5. **Analytics / Visualizations**
   - Charts for:
     - Distribution of messages per conversation.
     - Conversations over time.
     - Top link domains.

The frontend only talks to FastAPI; Electron’s role is process management and file system dialogs.

## 5. Coordination / Launch

Desired UX:
- One app the user runs that takes care of everything.

Dev/runtime story:

- Python package for backend + parser:
  - Exposes library functions and a CLI.
  - Backend entry point that starts FastAPI/uvicorn.
- Electron app:
  - On startup, spawns the backend process with a configured DB path and JSONL root.
  - Frontend calls FastAPI for config, jobs, and data.

Important: **Parser runs must always write JSONL into a per-run directory first, then ingest from those JSONL files into SQLite.** This guarantees we always have a durable log of what was imported, supports replays/migrations, and keeps the DB implementation swappable.

## 6. Next-Wave Features (Optional / Future)

- Message-level `time_index` and `message_kind` fields for easier querying.
- Branch metadata (`branch_root_id`, `branch_index`) for alternate paths/regens.
- More advanced dedupe/resume strategies when rerunning on overlapping exports.
- Optional PII-masking modes for JSONL and/or DB.
- True streaming ingestion (e.g. `ijson`) for very large export files.

