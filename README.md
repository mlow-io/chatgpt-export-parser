# ChatGPT Export Parser & SQLite Ingester

**Liberate your data.** A robust, local-first CLI tool to parse, normalize, and ingest your ChatGPT data export into a structured, relational SQLite database.

[![Python](https://img.shields.io/badge/Python-3.8%2B-blue)](https://www.python.org/) [![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT) [![Dependencies: None](https://img.shields.io/badge/Dependencies-Standard%20Lib%20Only-brightgreen)]()

## Why Use This?

The raw `conversations.json` from OpenAI is a deeply nested tree structure that is difficult to query or analyze. This tool transforms it into a **relational database** and **normalized JSONL files**, giving you:

*   **Full-Text Search:** Sub-second search across your entire history using SQLite's FTS5 engine.
*   **Data Ownership:** Keep a local, queryable archive of your chats that doesn't depend on OpenAI's servers.
*   **Analysis Ready:** SQL tables for `conversations`, `messages`, `tool_calls`, and `attachments` make data science easy.
*   **Readable Exports:** Reconstruct readable Markdown threads (with frontmatter) from your database.
*   **Diffing:** Track changes over time by ingesting multiple exports as distinct "runs".

---

## Quick Start

This repository includes a **synthetic demo export** so you can test the pipeline immediately without using your own data.

```bash
# 1. Parse & Ingest the demo data
python3 ChatGPT_Export_parser.py parse-and-ingest \
  demo/demo_conversations.json \
  --db demo/demo_chatgpt_export.db \
  --output-dir demo/normalized_runs/demo_run \
  --run-id demo_run \
  --force

# 2. Search it
python3 ChatGPT_Export_parser.py search --db demo/demo_chatgpt_export.db --q "Branch"

# 3. Export a conversation to Markdown
python3 ChatGPT_Export_parser.py export-conversation \
  --db demo/demo_chatgpt_export.db \
  --conversation-id <UUID_FROM_ABOVE> \
  --output my_chat.md
```

---

## Installation

No `pip install` required. The entire logic is contained in a single file depending only on the Python Standard Library.

1.  Clone the repository:
    ```bash
    git clone https://github.com/matthewb-io/chatgpt-export-parser.git
    cd chatgpt-export-parser
    ```
2.  Ensure you have Python 3.8+ installed:
    ```bash
    python3 --version
    ```

---

## Detailed Usage

The CLI is split into subcommands. Use `--help` on any command to see more options.

### 1. Parse & Ingest (Recommended)

The easiest way to import your data. It reads your export (JSON or ZIP), normalizes it to JSONL files (saved in `./normalized_runs/`), and loads it into SQLite.

```bash
# Process a raw JSON file
python3 ChatGPT_Export_parser.py parse-and-ingest /path/to/conversations.json --db my_chats.db

# Process directly from the downloaded ZIP
python3 ChatGPT_Export_parser.py parse-and-ingest /path/to/export.zip --db my_chats.db
```

### 2. Search & Query

**Full-Text Search (FTS):**
Search across all message content efficiently.
```bash
python3 ChatGPT_Export_parser.py search --db my_chats.db --q "quantum computing"
```

**Structured Query:**
Get metadata about conversations.
```bash
# List most recent 10 conversations
python3 ChatGPT_Export_parser.py query --db my_chats.db --type conversations --limit 10

# Get full details of a specific conversation as JSON
python3 ChatGPT_Export_parser.py query \
    --db my_chats.db \
    --type conversation_detail \
    --conversation-id <UUID> \
    --format json
```

### 3. Export to Markdown

Turn your database entries back into readable files.

**Single Conversation:**
```bash
python3 ChatGPT_Export_parser.py export-conversation \
    --db my_chats.db \
    --conversation-id <UUID> \
    --output interview_prep.md \
    --frontmatter
```

**Bulk Export (via Search):**
Export all conversations matching a search query.
```bash
python3 ChatGPT_Export_parser.py export-conversations \
    --db my_chats.db \
    --query "project alpha" \
    --output-dir ./project_alpha_chats \
    --frontmatter
```

### 4. Advanced: Run Management

The tool tracks every ingestion as a "run". This allows you to import data over time and see what changed.

```bash
# List all ingested runs
python3 ChatGPT_Export_parser.py list-runs --db my_chats.db

# Diff two runs to see what was added/removed/changed
python3 ChatGPT_Export_parser.py diff-runs --db my_chats.db --run-a <OLD_RUN_ID> --run-b <NEW_RUN_ID>
```

---

## Data Model

The data is normalized into a relational schema (Schema v3). Key tables include:

*   **`conversations`**: Metadata (title, create time, UUID).
*   **`messages`**: The actual content. Includes `role` (user/assistant) and `message_kind`.
*   **`nodes`**: Represents the tree structure of the conversation.
*   **`node_children`**: Explicit graph edges for fast traversal of branching conversations (edited messages).
*   **`tool_calls` & `tool_results`**: Structured data for Code Interpreter, DALL-E, etc.

**Message Kinds:**
*   `user_visible_user`: Standard user prompts.
*   `user_visible_assistant`: Standard GPT responses.
*   `system_context`: Hidden system prompts.
*   `tool_call` / `tool_result`: Function execution logs.
*   `internal_reasoning`: "Thought" chains (e.g., from o1 models).

---

## Data Safety

*   **Local First:** Your data never leaves your machine.
*   **Git Ignore:** The repository is configured to ignore `conversations.json`, `*.db`, and `normalized_runs/` to prevent accidental commits of personal data.
*   **Demo Data:** Only the synthetic data in `demo/` is tracked.

---

## Development & Testing

Run the test suite to ensure everything is working correctly:

```bash
python3 -m unittest discover -s tests
```

See `GEMINI.md` for deep architectural details and `TODOS.md` for the roadmap.