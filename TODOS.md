# Project Roadmap & Implementation Status

## Current TODOs

### Refactoring Plan: Modular Package Structure
*Goal: Decompose the monolithic `ChatGPT_Export_parser.py` into a maintainable `chatgpt_parser` package without breaking existing functionality or tests.*

**1. Target Package Structure**
```text
chatgpt-parser/
├── chatgpt_parser/           # New Package Root
│   ├── __init__.py           # Exposes version and main entry point
│   ├── __main__.py           # Allows `python -m chatgpt_parser`
│   ├── config.py             # Constants: SCHEMA_VERSION, URL_REGEX, DEFAULT_CSS
│   ├── cli/                  # Command Line Interface
│   │   ├── __init__.py
│   │   ├── main.py           # Argparse setup & dispatch (entry point)
│   │   └── commands.py       # run_parse, run_ingest, run_search (Controllers)
│   ├── core/                 # Business Logic
│   │   ├── __init__.py
│   │   ├── parser.py         # process_conversation, determine_message_kind
│   │   └── exporter.py       # export_conversation_to_markdown, render_*
│   ├── db/                   # Data Access Layer
│   │   ├── __init__.py
│   │   ├── manager.py        # SQLiteManager class
│   │   └── schema.py         # CREATE_TABLES_SQL, schema versioning
│   └── utils/                # Shared Helpers
│       ├── __init__.py
│       ├── io.py             # stream_json_array, write_jsonl_line
│       ├── text.py           # markdown_escape, extract_urls
│       └── logging.py        # setup_logging
├── ChatGPT_Export_parser.py  # (Legacy wrapper) imports from package and runs main
└── tests/                    # Updated to import from chatgpt_parser.*
```

**2. Implementation Steps**
- [ ] **Phase 1: Scaffolding & Utils**
    - Create `chatgpt_parser/` and subdirectories.
    - Move `URL_REGEX`, `DEFAULT_CSS`, `CURRENT_SCHEMA_VERSION` to `config.py`.
    - Move `stream_json_array`, `write_jsonl_line` to `utils/io.py`.
    - Move `markdown_escape`, `extract_urls` to `utils/text.py`.
    - Move `setup_logging` to `utils/logging.py`.
- [ ] **Phase 2: Database Layer**
    - Move `CREATE_TABLES_SQL` strings to `db/schema.py`.
    - Move `SQLiteManager` class to `db/manager.py`.
    - *Check:* Ensure `SQLiteManager` imports logging and config correctly.
- [ ] **Phase 3: Core Logic**
    - Move `process_conversation` and related helpers to `core/parser.py`.
    - Move `export_conversation_to_markdown` and `run_export_*` logic to `core/exporter.py`.
- [ ] **Phase 4: CLI & Entry Point**
    - Move `main()` and `argparse` definitions to `cli/main.py`.
    - Move `run_parse`, `run_ingest` etc. to `cli/commands.py`.
    - Create a `ChatGPT_Export_parser.py` shim that simply does `from chatgpt_parser.cli.main import main; main()`.
- [ ] **Phase 5: Test Updates**
    - Update `tests/*.py` to import from the new module paths (e.g., `from chatgpt_parser.core.parser import process_conversation`).
    - Verify all tests pass with `python3 -m unittest discover -s tests`.

**3. Future Considerations (Post-Refactor)**
- **Type Hinting**: Add strict MyPy checking once files are smaller.
- **Dependency Management**: Add `pyproject.toml` for proper packaging if we decide to publish to PyPI.

---

## Completed

### Schema v3: Branch-Aware Graph & Foreign Keys (Implemented)
*Status: Live in `ChatGPT_Export_parser.py` (Schema v3).*

**Summary of Changes:**
1.  **Explicit Branches**: Added `node_children` table (and JSONL output) to allow fast, recursive tree traversal.
2.  **Data Integrity**: Enforced `FOREIGN KEY` constraints across `messages`, `nodes`, `conversations`, etc.
3.  **Migration**: Added automatic migration to Schema v3 with backfill for existing databases.

---

# Archived Design Note: Schema v3 Implementation
*(Preserved for historical context on the v3 design decisions)*

This section records the design and implementation steps taken for the Schema v3 upgrade.

## Goals (What “Done” Looked Like)

- `parse` emits `normalized_runs/<run_id>/node_children.jsonl` where each line is one edge:
  - `run_id`, `conversation_id`, `parent_node_id`, `child_node_id`, `child_index`
- `ingest` loads `node_children.jsonl` into SQLite and keeps it in sync with `nodes`.
- SQLite can enforce (at least) the critical relationships:
  - `messages(run_id, node_id)` must exist in `nodes(run_id, id)`
  - `nodes(run_id, conversation_id)` must exist in `conversations(run_id, id)`
  - `messages(run_id, conversation_id)` must exist in `conversations(run_id, id)`
  - `node_children` edges must point at real nodes + a real conversation
- `migrate` upgrades older DBs and backfills `node_children` if missing.
- Tests verify `node_children.jsonl` emission + DB ingestion.



---

## Design Decisions (Professional/Pragmatic)

### A) Keep JSONL portable; make SQLite query-friendly

- JSONL remains the “canonical” export artifact.
- SQLite gets extra normalized structure (`node_children`) for performance + simple queries.

### B) Minimize FK cycles

Your current schema has potential cycles:
- `messages.node_id -> nodes.id`
- `nodes.message_id -> messages.id`

To avoid circular FK headaches, **do not** add an FK on `nodes.message_id` initially.
Instead, enforce the direction that matters most for integrity and queries:
- `messages.node_id` must reference `nodes.id`

Similarly, adding an FK on `conversations.current_node_id -> nodes.id` is nice-to-have but can
complicate ingestion order. Treat it as optional.

### C) Composite keys mean composite FKs

All real identities are `(run_id, id)`. Any FK should include `run_id` to avoid cross-run ambiguity.

---

## Schema v3 (Target State)

Update `CURRENT_SCHEMA_VERSION` from `2` to `3`.

### 1) Add `node_children` table (new)

Add a table like:

```sql
CREATE TABLE IF NOT EXISTS node_children (
  run_id TEXT NOT NULL,
  conversation_id TEXT NOT NULL,
  parent_node_id TEXT NOT NULL,
  child_node_id TEXT NOT NULL,
  child_index INTEGER NOT NULL,
  PRIMARY KEY (run_id, parent_node_id, child_index),
  UNIQUE (run_id, parent_node_id, child_node_id),
  FOREIGN KEY (run_id, conversation_id)
    REFERENCES conversations(run_id, id)
    ON DELETE CASCADE,
  FOREIGN KEY (run_id, parent_node_id)
    REFERENCES nodes(run_id, id)
    ON DELETE CASCADE,
  FOREIGN KEY (run_id, child_node_id)
    REFERENCES nodes(run_id, id)
    ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_node_children_parent
  ON node_children(run_id, parent_node_id);
CREATE INDEX IF NOT EXISTS idx_node_children_child
  ON node_children(run_id, child_node_id);
CREATE INDEX IF NOT EXISTS idx_node_children_conv
  ON node_children(run_id, conversation_id);
```

### 2) Add FKs to existing tables (requires rebuild migration)

Add these FKs (minimum set):

**`nodes`**
- `FOREIGN KEY (run_id, conversation_id) REFERENCES conversations(run_id, id)`
- Optional: `FOREIGN KEY (run_id, parent_id) REFERENCES nodes(run_id, id)`

**`messages`**
- `FOREIGN KEY (run_id, conversation_id) REFERENCES conversations(run_id, id)`
- `FOREIGN KEY (run_id, node_id) REFERENCES nodes(run_id, id)`

**`links`, `attachments`, `tool_calls`, `tool_results`**
- At least enforce conversation existence:
  - `FOREIGN KEY (run_id, conversation_id) REFERENCES conversations(run_id, id)`
- Optionally enforce `message_id` existence:
  - `FOREIGN KEY (run_id, message_id) REFERENCES messages(run_id, id)`
  - Note: you may have some rows where `message_id` is `NULL` (that’s fine).

**Important SQLite note**
- SQLite can’t reliably “ALTER TABLE … ADD FOREIGN KEY …” for existing tables.
- To add FKs, you typically rebuild the tables:
  - create `*_new` with FKs → copy data → drop old → rename.

---

## Parsing Changes (Emit `node_children.jsonl`)

File: `ChatGPT_Export_parser.py`, function `process_conversation()` (~`ChatGPT_Export_parser.py:609`).

### 1) JSONL writer list

In `run_parse()`, extend the `files` list to include `node_children`:
- Current: `["conversations", "nodes", "messages", ...]`
- Target: `["conversations", "nodes", "node_children", "messages", ...]`

Also update:
- `writers = {name: open(...)}`
- `manifest["files"]` generation
- `stats` keys to include `node_children` count

### 2) Emit edge rows during parse

You already build:
- `children: Dict[str, List[str]]` from export mapping.

Add after building `children` (and after `conv_id` is known):

Pseudo-code:

```py
for parent_node_id, child_list in children.items():
    for child_index, child_node_id in enumerate(child_list):
        row = {
            "run_id": run_id,
            "conversation_id": conv_id,
            "parent_node_id": parent_node_id,
            "child_node_id": child_node_id,
            "child_index": child_index,
        }
        write_jsonl_line(writers["node_children"], row)
        stats["node_children"] += 1
```

Notes:
- Preserve the child ordering given by the export (important for deterministic UI).
- Do not rely on JSON-in-TEXT for branch edges in SQLite; this JSONL is now the canonical edge log.

---

## Ingest Changes (Load `node_children`)

File: `ChatGPT_Export_parser.py`, class `SQLiteManager`, method `ingest_run()` (~`ChatGPT_Export_parser.py:469`).

### 1) Ingest order

Order matters once FKs exist. Recommended order:
1) `conversations`
2) `nodes`
3) `node_children`
4) `messages` (and `message_fts`)
5) `links`
6) `attachments`
7) `tool_calls`
8) `tool_results`

Update the `tables = [...]` list accordingly.

### 2) PRAGMA foreign_keys

Enable enforcement on the connection immediately after `sqlite3.connect`:

```py
self.conn.execute("PRAGMA foreign_keys = ON")
```

Also do this for every connection created outside `SQLiteManager` (see section below).

### 3) Batch insert details

No special casing needed for `node_children` other than:
- ensuring `run_id` is present
- indexes exist

---

## Enabling Foreign Keys Everywhere (Critical)

SQLite does not enforce FKs unless you enable it on each connection.

Add:
```py
conn.execute("PRAGMA foreign_keys = ON")
```

In:
- `SQLiteManager.__init__` (the main ingestion connection)
- `run_query` (creates a new connection)
- `run_search`
- `run_export_conversation`
- `run_export_conversations` (it opens a connection just to fetch IDs)
- `run_check`
- `run_list_runs`
- `run_diff_runs`
- `run_dump_db` / `run_restore_db`
- `run_migrate`
- `run_export_bundle`

Tip: add a helper:
```py
def connect_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn
```
Then replace direct `sqlite3.connect(...)` calls.

---

## Migration Plan (Schema v3)

File: `ChatGPT_Export_parser.py`, function `run_migrate()` (~`ChatGPT_Export_parser.py:1413`).

### Step 0: Bump version constant

- Set `CURRENT_SCHEMA_VERSION = 3`.

### Step 1: Ensure `meta` exists; read version

- You already do this.

### Step 2: Create/Backfill `node_children`

If upgrading from v2:
- Create the `node_children` table if missing.
- Backfill from existing `nodes.children_ids`.

Backfill algorithm (DB-only):
1) Read rows:
   - `SELECT run_id, conversation_id, id, children_ids FROM nodes`
2) Parse `children_ids`:
   - It may be `NULL`, `'[]'`, or a JSON string list.
3) For each child in list, insert:
   - `(run_id, conversation_id, parent_node_id=id, child_node_id=child, child_index=i)`

Important: for performance, do this in a transaction with `executemany`.

### Step 3: Rebuild tables to add FKs (recommended)

To add FKs to existing tables, do a rebuild:

1) `BEGIN;`
2) `PRAGMA foreign_keys = OFF;` (during the rebuild only)
3) Create `conversations_new`, `nodes_new`, `messages_new`, etc with FK clauses.
4) Copy:
   - `INSERT INTO conversations_new SELECT ... FROM conversations;`
   - `INSERT INTO nodes_new SELECT ... FROM nodes;`
   - ...
5) Drop old tables and rename `_new` → original names.
6) Recreate indexes (if not included).
7) Recreate FTS table and re-backfill:
   - easiest: drop `message_fts` and rebuild from `messages.text`.
8) `PRAGMA foreign_keys = ON;`
9) Set `meta.schema_version = 3`.
10) `COMMIT;`

If you want a softer migration (less invasive), you can:
- add only `node_children` + backfill, bump version, and defer FK enforcement to a later release.
But if “high quality app” is the goal, the rebuild is the right move.

---

## JSONL Changes (Do We Change Anything?)

### Raw export JSON (input)
- No changes.

### Normalized JSONL (output)
- Add a new file: `node_children.jsonl`.
- Keep `nodes.children_ids` in JSONL as a list for readability (it already is during parse).
- SQLite will still store JSON-ish columns as TEXT (due to batch serialization), but edges are now query-native via `node_children`.

Versioning tip:
- Add a `schema_version` field in `run.json` (or reuse `version`) if you want consumers to detect the presence of `node_children.jsonl`.

---

## Query / App Enablement (Branch Rendering)

Once `node_children` exists, branch queries become simple.

Branch points (nodes with >1 child):
```sql
SELECT parent_node_id, COUNT(*) AS child_count
FROM node_children
WHERE run_id = ? AND conversation_id = ?
GROUP BY parent_node_id
HAVING COUNT(*) > 1;
```

Children of a node (ordered):
```sql
SELECT child_node_id
FROM node_children
WHERE run_id = ? AND parent_node_id = ?
ORDER BY child_index ASC;
```

Walk a path to root using `nodes.parent_id`:
- In Python (simple loop) or SQLite recursive CTE if desired.

---

## Tests to Add/Update

Files: `tests/test_streaming_parse.py`, `tests/test_search_and_check.py`

- Update parse test to assert `node_children.jsonl` exists and has expected rows.
- Add a new fixture conversation with a branch:
  - root -> user -> assistantA and assistantB
  - assert 2 edges from the branch point and correct `child_index` ordering.
- Update ingest test to confirm `node_children` table row count matches JSONL rows.
- Optional: add a test that FK enforcement rejects bad data (e.g., manually insert a message referencing a missing node and assert it fails).

---

## Rollout Checklist

- [ ] Add `node_children.jsonl` emission in `parse`
- [ ] Add `node_children` table + indexes
- [ ] Ingest `node_children` in correct order
- [ ] Enable `PRAGMA foreign_keys=ON` on all connections
- [ ] Bump schema version to 3
- [ ] Implement `migrate`:
  - [ ] create/backfill `node_children`
  - [ ] rebuild tables for FKs (or explicitly defer with a note)
  - [ ] rebuild `message_fts`
- [ ] Update tests and run `python3 -m unittest discover -s tests`
- [ ] Update docs (`SCHEMA_AND_SPEC.md`, `GEMINI.md`) to mention `node_children`

---

## Notes / Known Related Fixes (Not Required, But High Value)

- `parse` zip streaming path references `stream_json_array_from_file(...)` which is currently undefined; fix by implementing it or reusing `stream_json_array` on a temp file.
- `search --run-id` currently uses an alias `f.run_id` that doesn’t exist in the SQL; should filter on `message_fts.run_id` or joined `messages.run_id`.
- Many queries join on `id` without `run_id` scoping; once multi-run is real, prefer scoping reads to a run (`--run-id` or “latest run”).
