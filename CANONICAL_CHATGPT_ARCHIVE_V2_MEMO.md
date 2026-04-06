# ChatGPT Canonical Archive V2 Memo

## Why this exists

The original full SQLite DB in this repo is good at one thing: preserving each ingest as a distinct run. That is useful for debugging and diffing, but it is the wrong primary storage model for AtlasBench GPT, which wants one cumulative ChatGPT history browser.

The recent `catalog` and old AtlasWorkbench-flavored `canonical` paths were both solving adjacent problems:

- `catalog`: discovery, indexing, summary search across many exports
- old `canonical`: generic documents/chunks abstraction

Neither is the right primary backing store for a faithful ChatGPT thread browser.

## What AtlasBench actually expects

AtlasBench expects a ChatGPT-native relational DB with:

- `conversations`
- `messages`
- `nodes`
- `node_children`
- `message_fts`

And conversation/detail rows shaped around:

- `id`
- `title`
- `created_at`, `updated_at`
- `default_model`, `models_used`
- `is_archived`, `is_starred`
- `current_node_id`
- `message_count`
- `source_file`
- message-level `role`, `text`, `message_kind`, `model`, `is_hidden`, `time_index`

So V2 keeps those tables and columns, instead of inventing `documents`/`chunks`.

## V2 design

The new canonical archive is a forked evolution of the original full DB:

- canonical identity for conversations/messages across exports
- branch structure preserved exactly inside each conversation graph
- `run_id` retained for provenance, but no longer part of the primary keys
- provenance moved into separate tables:
  - `runs`
  - `conversation_runs`
  - `message_runs`

This means:

- October export + October/November export no longer produce two logical copies of the same conversation
- later exports can supersede earlier truncated snapshots
- AtlasBench can read the canonical DB like the original full DB, with much less adapter complexity

## What we kept from the catalog path

The canonical archive also carries a few useful derived fields that the original run-scoped DB did not have:

- `earliest_message_at`
- `latest_message_at`
- `message_count_main_path`
- role counts (`user_message_count`, `assistant_message_count`, `system_message_count`, `tool_message_count`)
- `keyword_text`
- `summary_text`

These are optional denormalized helpers. They do not replace full message storage.

## What is not the standard

- The AtlasWorkbench-style `documents` / `chunks` canonical schema is not the standard ChatGPT DB path.
- The catalog DB is not the primary thread-reading source of truth.

Those can remain as secondary tooling if still useful, but the primary data model for AtlasBench-style reading should now be the canonical ChatGPT archive DB written by `canonical-ingest`.
