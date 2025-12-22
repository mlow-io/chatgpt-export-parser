#!/usr/bin/env python3
"""
Parse ChatGPT conversation export JSON files into a normalized JSONL schema and/or SQLite database.

Schema (each file is JSON Lines):
- conversations.jsonl
- nodes.jsonl
- messages.jsonl
- links.jsonl
- attachments.jsonl
- tool_calls.jsonl
- tool_results.jsonl

Subcommands:
    parse             Normalize JSON to JSONL
    ingest            Ingest existing JSONL to SQLite
    parse-and-ingest  Normalize and then ingest
    query             Run basic queries against the DB
"""

import argparse
import json
import logging
import os
import re
import shutil
import subprocess
import sqlite3
import sys
import time
import uuid
import zipfile
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union
from urllib.parse import urlparse


URL_REGEX = re.compile(r'https?://\S+')
CURRENT_SCHEMA_VERSION = 3
DEFAULT_CSS = """\
:root {
  font-family: "Inter", "Helvetica Neue", Arial, sans-serif;
  color: #0f172a;
  background: #f8fafc;
}
body {
  max-width: 960px;
  margin: 0 auto;
  padding: 32px 18px 48px;
  line-height: 1.6;
}
h1, h2, h3, h4 {
  color: #0f172a;
  margin: 1.25em 0 0.35em;
  line-height: 1.25;
}
a { color: #2563eb; }
code {
  font-family: "JetBrains Mono", "SFMono-Regular", Menlo, Consolas, monospace;
  background: #eef2ff;
  padding: 0 4px;
  border-radius: 4px;
}
blockquote {
  background: #eef2ff;
  border-left: 4px solid #6366f1;
  padding: 0.85rem 1.1rem;
  margin: 0.35rem 0 1.25rem;
}
hr {
  border: 0;
  border-top: 1px solid #e2e8f0;
  margin: 1.5rem 0;
}
ul {
  padding-left: 1.15rem;
}
.toc {
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 1rem;
  box-shadow: 0 1px 2px rgba(15,23,42,0.04);
}
"""


# --- Logging & Utils ---

def setup_logging(output_dir: Optional[str], verbose: bool = True) -> logging.Logger:
    logger = logging.getLogger("chatgpt_export_parser")
    logger.setLevel(logging.DEBUG)
    if logger.handlers:
        for h in logger.handlers:
            try:
                h.close()
            except Exception:
                pass
        logger.handlers.clear()

    # Console handler
    if verbose:
        ch = logging.StreamHandler(sys.stdout)
        ch.setLevel(logging.INFO)
        ch_formatter = logging.Formatter("%(levelname)s: %(message)s")
        ch.setFormatter(ch_formatter)
        logger.addHandler(ch)
    else:
        # If not verbose, we might still want errors on stderr?
        # For now, follow logic: verbose=False -> silent stdout
        pass

    # File handler (if we have an output dir)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        log_path = os.path.join(output_dir, "parser.log")
        fh = logging.FileHandler(log_path, encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh_formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        fh.setFormatter(fh_formatter)
        logger.addHandler(fh)

    return logger


def attach_file_handler(logger: logging.Logger, output_dir: Optional[str]) -> None:
    """Add a file handler for parser.log in the given output_dir if not already present."""
    if not output_dir:
        return
    os.makedirs(output_dir, exist_ok=True)
    log_path = os.path.join(output_dir, "parser.log")
    for h in logger.handlers:
        if isinstance(h, logging.FileHandler) and getattr(h, "baseFilename", None) == os.path.abspath(log_path):
            return
    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh_formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    fh.setFormatter(fh_formatter)
    logger.addHandler(fh)


def escape_markdown_text(text: Optional[str]) -> str:
    if text is None:
        return ""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def iso_from_timestamp(ts: Optional[float]) -> Optional[str]:
    if ts is None:
        return None
    try:
        return (
            datetime.fromtimestamp(ts, tz=timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
        )
    except Exception:
        return None


def connect_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def write_jsonl_line(f, obj: Dict[str, Any]) -> None:
    f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def extract_urls_from_text(text: str) -> Iterable[Tuple[str, int, int]]:
    if not text:
        return []
    for m in URL_REGEX.finditer(text):
        url = m.group(0).rstrip(").,]>\"'")
        start = m.start()
        end = start + len(url)
        yield url, start, end


def parse_url(url: str) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    try:
        parsed = urlparse(url)
        return parsed.scheme or None, parsed.netloc or None, parsed.path or None, parsed.query or None
    except Exception:
        return None, None, None, None


def stream_json_array(path: str, chunk_size: int = 65536) -> Iterable[Dict[str, Any]]:
    """
    Stream a top-level JSON array from disk without loading the whole file.
    Uses the standard library JSONDecoder to incrementally parse objects.
    """
    decoder = json.JSONDecoder()
    with open(path, "r", encoding="utf-8") as f:
        buffer = ""
        idx = 0

        # Seek to the opening bracket
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                raise ValueError(f"File {path} does not contain a JSON array.")
            buffer += chunk
            while idx < len(buffer) and buffer[idx].isspace():
                idx += 1
            if idx < len(buffer):
                if buffer[idx] != "[":
                    raise ValueError(f"File {path} must start with a JSON array.")
                idx += 1
                buffer = buffer[idx:]
                idx = 0
                break

        while True:
            while idx < len(buffer) and buffer[idx].isspace():
                idx += 1

            # If buffer is exhausted, read more
            if idx >= len(buffer):
                chunk = f.read(chunk_size)
                if not chunk:
                    return
                buffer = buffer[idx:] + chunk
                idx = 0
                continue

            # End of array
            if buffer[idx] == "]":
                return

            try:
                obj, next_idx = decoder.raw_decode(buffer, idx)
            except json.JSONDecodeError:
                chunk = f.read(chunk_size)
                if not chunk:
                    raise
                buffer = buffer[idx:] + chunk
                idx = 0
                continue

            yield obj
            idx = next_idx

            # Compact buffer occasionally to keep memory bounded
            if idx > 1024:
                buffer = buffer[idx:]
                idx = 0

            # Consume trailing whitespace and comma between elements
            while True:
                while idx < len(buffer) and buffer[idx].isspace():
                    idx += 1
                if idx < len(buffer) and buffer[idx] == ",":
                    idx += 1
                    break
                if idx < len(buffer) and buffer[idx] == "]":
                    return
                if idx >= len(buffer):
                    chunk = f.read(chunk_size)
                    if not chunk:
                        return
                    buffer = buffer[idx:] + chunk
                    idx = 0
                    continue
                # Unexpected character; try reading more
                chunk = f.read(chunk_size)
                if not chunk:
                    raise json.JSONDecodeError(
                        "Unexpected character while parsing JSON array", buffer, idx
                    )
                buffer = buffer[idx:] + chunk
                idx = 0
                break


def stream_json_array_from_file(f, chunk_size: int = 65536) -> Iterable[Dict[str, Any]]:
    """
    Stream a top-level JSON array from a file-like object without loading the whole file.
    Uses the standard library JSONDecoder to incrementally parse objects.
    """
    decoder = json.JSONDecoder()
    buffer = ""
    idx = 0

    # Seek to the opening bracket
    while True:
        chunk = f.read(chunk_size)
        if not chunk:
            raise ValueError("File does not contain a JSON array.")
        buffer += chunk
        while idx < len(buffer) and buffer[idx].isspace():
            idx += 1
        if idx < len(buffer):
            if buffer[idx] != "[":
                raise ValueError("File must start with a JSON array.")
            idx += 1
            buffer = buffer[idx:]
            idx = 0
            break

    while True:
        while idx < len(buffer) and buffer[idx].isspace():
            idx += 1

        if idx >= len(buffer):
            chunk = f.read(chunk_size)
            if not chunk:
                return
            buffer = buffer[idx:] + chunk
            idx = 0
            continue

        if buffer[idx] == "]":
            return

        try:
            obj, next_idx = decoder.raw_decode(buffer, idx)
        except json.JSONDecodeError:
            chunk = f.read(chunk_size)
            if not chunk:
                raise
            buffer = buffer[idx:] + chunk
            idx = 0
            continue

        yield obj
        idx = next_idx

        if idx > 1024:
            buffer = buffer[idx:]
            idx = 0

        while True:
            while idx < len(buffer) and buffer[idx].isspace():
                idx += 1
            if idx < len(buffer) and buffer[idx] == ",":
                idx += 1
                break
            if idx < len(buffer) and buffer[idx] == "]":
                return
            if idx >= len(buffer):
                chunk = f.read(chunk_size)
                if not chunk:
                    return
                buffer = buffer[idx:] + chunk
                idx = 0
                continue
            chunk = f.read(chunk_size)
            if not chunk:
                raise json.JSONDecodeError(
                    "Unexpected character while parsing JSON array", buffer, idx
                )
            buffer = buffer[idx:] + chunk
            idx = 0
            break

# --- SQL Schema & Manager ---

CREATE_TABLES_SQL = [
    """
    CREATE TABLE IF NOT EXISTS runs (
        run_id TEXT PRIMARY KEY,
        jsonl_dir TEXT NOT NULL,
        started_at TEXT NOT NULL,
        finished_at TEXT,
        input_files TEXT, -- JSON list
        stats TEXT        -- JSON object
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS conversations (
        run_id TEXT NOT NULL,
        id TEXT NOT NULL,
        source_id TEXT,
        title TEXT,
        created_at TEXT,
        updated_at TEXT,
        default_model TEXT,
        models_used TEXT, -- JSON list
        is_archived BOOLEAN,
        is_starred BOOLEAN,
        current_node_id TEXT,
        message_count INTEGER,
        safe_url_count INTEGER,
        blocked_url_count INTEGER,
        metadata TEXT,    -- JSON object
        source_file TEXT,
        PRIMARY KEY (run_id, id)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS nodes (
        run_id TEXT NOT NULL,
        id TEXT NOT NULL,
        conversation_id TEXT NOT NULL,
        parent_id TEXT,
        children_ids TEXT, -- JSON list
        message_id TEXT,
        is_root BOOLEAN,
        is_in_main_path BOOLEAN,
        depth INTEGER,
        main_path_index INTEGER,
        PRIMARY KEY (run_id, id),
        FOREIGN KEY (run_id, conversation_id)
            REFERENCES conversations(run_id, id)
            ON DELETE CASCADE
    );
    """,
    """
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
    """,
    """
    CREATE TABLE IF NOT EXISTS messages (
        run_id TEXT NOT NULL,
        id TEXT NOT NULL,
        node_id TEXT,
        conversation_id TEXT NOT NULL,
        role TEXT,
        author_name TEXT,
        recipient TEXT,
        channel TEXT,
        content_type TEXT,
        text TEXT,
        raw_content TEXT, -- JSON object
        created_at TEXT,
        updated_at TEXT,
        is_hidden BOOLEAN,
        hidden_reason TEXT,
        is_in_main_path BOOLEAN,
        main_path_index INTEGER,
        depth INTEGER,
        model TEXT,
        metadata TEXT,    -- JSON object
        time_index INTEGER,
        message_kind TEXT,
        PRIMARY KEY (run_id, id),
        FOREIGN KEY (run_id, conversation_id)
            REFERENCES conversations(run_id, id)
            ON DELETE CASCADE,
        FOREIGN KEY (run_id, node_id)
            REFERENCES nodes(run_id, id)
            ON DELETE CASCADE
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS links (
        run_id TEXT NOT NULL,
        id TEXT NOT NULL,
        conversation_id TEXT NOT NULL,
        message_id TEXT,
        source TEXT,
        url TEXT,
        display_text TEXT,
        position_start INTEGER,
        position_end INTEGER,
        scheme TEXT,
        domain TEXT,
        path TEXT,
        query TEXT,
        kind TEXT,
        metadata TEXT,
        PRIMARY KEY (run_id, id),
        FOREIGN KEY (run_id, conversation_id)
            REFERENCES conversations(run_id, id)
            ON DELETE CASCADE,
        FOREIGN KEY (run_id, message_id)
            REFERENCES messages(run_id, id)
            ON DELETE CASCADE
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS attachments (
        run_id TEXT NOT NULL,
        id TEXT NOT NULL,
        conversation_id TEXT NOT NULL,
        message_id TEXT,
        type TEXT,
        filename TEXT,
        mime_type TEXT,
        filesize_bytes INTEGER,
        source_ref TEXT,
        metadata TEXT,
        PRIMARY KEY (run_id, id),
        FOREIGN KEY (run_id, conversation_id)
            REFERENCES conversations(run_id, id)
            ON DELETE CASCADE,
        FOREIGN KEY (run_id, message_id)
            REFERENCES messages(run_id, id)
            ON DELETE CASCADE
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS tool_calls (
        run_id TEXT NOT NULL,
        id TEXT NOT NULL,
        conversation_id TEXT NOT NULL,
        message_id TEXT,
        tool_name TEXT,
        call_index INTEGER,
        arguments_json TEXT, -- JSON object
        raw_arguments TEXT,
        metadata TEXT,
        PRIMARY KEY (run_id, id),
        FOREIGN KEY (run_id, conversation_id)
            REFERENCES conversations(run_id, id)
            ON DELETE CASCADE,
        FOREIGN KEY (run_id, message_id)
            REFERENCES messages(run_id, id)
            ON DELETE CASCADE
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS tool_results (
        run_id TEXT NOT NULL,
        id TEXT NOT NULL,
        conversation_id TEXT NOT NULL,
        message_id TEXT,
        tool_call_id TEXT,
        result_json TEXT, -- JSON object
        raw_result TEXT,
        metadata TEXT,
        PRIMARY KEY (run_id, id),
        FOREIGN KEY (run_id, conversation_id)
            REFERENCES conversations(run_id, id)
            ON DELETE CASCADE,
        FOREIGN KEY (run_id, message_id)
            REFERENCES messages(run_id, id)
            ON DELETE CASCADE,
        FOREIGN KEY (run_id, tool_call_id)
            REFERENCES tool_calls(run_id, id)
            ON DELETE CASCADE
    );
    """,
    """
    CREATE VIRTUAL TABLE IF NOT EXISTS message_fts USING fts5(
        message_id UNINDEXED,
        conversation_id UNINDEXED,
        run_id UNINDEXED,
        role,
        text,
        tokenize='unicode61'
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS meta (
        key TEXT PRIMARY KEY,
        value TEXT
    );
    """,
    # Indices for performance
    "CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(run_id, conversation_id);",
    "CREATE INDEX IF NOT EXISTS idx_nodes_conv ON nodes(run_id, conversation_id);",
    "CREATE INDEX IF NOT EXISTS idx_messages_kind ON messages(run_id, message_kind);",
    "CREATE INDEX IF NOT EXISTS idx_messages_time ON messages(run_id, conversation_id, time_index);",
    "CREATE INDEX IF NOT EXISTS idx_node_children_parent ON node_children(run_id, parent_node_id);",
    "CREATE INDEX IF NOT EXISTS idx_node_children_child ON node_children(run_id, child_node_id);",
    "CREATE INDEX IF NOT EXISTS idx_node_children_conv ON node_children(run_id, conversation_id);",
]

class SQLiteManager:
    def __init__(self, db_path: str, mode: str = "skip_existing"):
        self.db_path = db_path
        self.mode = mode
        self.conn = connect_db(db_path)
        self.conn.text_factory = str  # Ensure strings
        self._init_schema()

    def _init_schema(self):
        cur = self.conn.cursor()
        for stmt in CREATE_TABLES_SQL:
            cur.execute(stmt)
        cur.execute(
            "INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', ?)",
            (str(CURRENT_SCHEMA_VERSION),),
        )
        cur.execute(
            "INSERT OR IGNORE INTO meta(key, value) VALUES ('created_at', datetime('now'))"
        )
        self.conn.commit()

    def check_run_exists(self, run_id: str) -> bool:
        cur = self.conn.cursor()
        cur.execute("SELECT 1 FROM runs WHERE run_id = ?", (run_id,))
        return cur.fetchone() is not None

    def ingest_run(self, run_dir: str, run_id: str):
        if self.mode == "skip_existing" and self.check_run_exists(run_id):
            logging.info(f"Run {run_id} already exists in DB. Skipping.")
            return

        # If overwrite, delete existing entries for this run_id
        if self.mode == "overwrite":
            self._delete_run(run_id)

        logging.info(f"Ingesting run {run_id} from {run_dir} into {self.db_path}...")
        
        # Read run.json
        run_meta_path = os.path.join(run_dir, "run.json")
        run_meta = {}
        if os.path.exists(run_meta_path):
            with open(run_meta_path, "r", encoding="utf-8") as f:
                run_meta = json.load(f)
        
        # Insert run row
        self.conn.execute(
            """
            INSERT OR REPLACE INTO runs 
            (run_id, jsonl_dir, started_at, finished_at, input_files, stats)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                run_dir,
                run_meta.get("created_at", iso_from_timestamp(time.time())),
                None, # finished_at (could be now)
                json.dumps(run_meta.get("input_files", [])),
                json.dumps(run_meta.get("stats", {}))
            )
        )

        # Ingest each table
        tables = [
            "conversations",
            "nodes",
            "node_children",
            "messages",
            "links",
            "attachments",
            "tool_calls",
            "tool_results",
        ]
        
        for table in tables:
            file_path = os.path.join(run_dir, f"{table}.jsonl")
            if not os.path.exists(file_path):
                if table == "node_children":
                    self._backfill_node_children_from_nodes_jsonl(run_dir, run_id)
                continue
            
            rows_batch = []
            fts_batch = []
            with open(file_path, "r", encoding="utf-8") as f:
                for line in f:
                    row = json.loads(line)
                    # Ensure run_id is present (parser adds it, but just in case)
                    row["run_id"] = run_id
                    rows_batch.append(row)
                    if table == "messages":
                        text_val = row.get("text")
                        if text_val:
                            fts_batch.append(
                                (
                                    row.get("id"),
                                    row.get("conversation_id"),
                                    run_id,
                                    row.get("role"),
                                    text_val,
                                )
                            )
                    if len(rows_batch) >= 1000:
                        self._insert_batch(table, rows_batch)
                        if table == "messages" and fts_batch:
                            self._insert_message_fts(fts_batch)
                        rows_batch = []
                        fts_batch = []
            if rows_batch:
                self._insert_batch(table, rows_batch)
                if table == "messages" and fts_batch:
                    self._insert_message_fts(fts_batch)
        
        self.conn.commit()
        logging.info(f"Ingestion of run {run_id} complete.")

    def _delete_run(self, run_id: str):
        tables = [
            "runs",
            "conversations",
            "nodes",
            "node_children",
            "messages",
            "links",
            "attachments",
            "tool_calls",
            "tool_results",
        ]
        for t in tables:
            self.conn.execute(f"DELETE FROM {t} WHERE run_id = ?", (run_id,))
        self.conn.commit()

    def _insert_batch(self, table: str, rows: List[Dict[str, Any]]):
        if not rows:
            return
        
        # Get columns from first row
        columns = list(rows[0].keys())
        placeholders = ", ".join(["?"] * len(columns))
        col_names = ", ".join(columns)
        
        # Prepare data
        values = []
        for row in rows:
            # Serialize lists/dicts to JSON strings for SQLite
            row_vals = []
            for k in columns:
                v = row.get(k)
                if isinstance(v, (dict, list)):
                    v = json.dumps(v, ensure_ascii=False)
                row_vals.append(v)
            values.append(row_vals)
            
        sql = f"INSERT OR REPLACE INTO {table} ({col_names}) VALUES ({placeholders})"
        self.conn.executemany(sql, values)

    def _insert_message_fts(self, rows: List[Tuple[Any, Any, Any, Any, Any]]):
        if not rows:
            return
        self.conn.executemany(
            "INSERT INTO message_fts(message_id, conversation_id, run_id, role, text) VALUES (?, ?, ?, ?, ?)",
            rows,
        )

    def _backfill_node_children_from_nodes_jsonl(self, run_dir: str, run_id: str) -> None:
        nodes_path = os.path.join(run_dir, "nodes.jsonl")
        if not os.path.exists(nodes_path):
            return

        rows_batch = []
        with open(nodes_path, "r", encoding="utf-8") as f:
            for line in f:
                node = json.loads(line)
                children = node.get("children_ids") or []
                if not isinstance(children, list):
                    continue
                parent_node_id = node.get("id")
                conversation_id = node.get("conversation_id")
                for child_index, child_node_id in enumerate(children):
                    rows_batch.append(
                        {
                            "run_id": run_id,
                            "conversation_id": conversation_id,
                            "parent_node_id": parent_node_id,
                            "child_node_id": child_node_id,
                            "child_index": child_index,
                        }
                    )
                if len(rows_batch) >= 1000:
                    self._insert_batch("node_children", rows_batch)
                    rows_batch = []
        if rows_batch:
            self._insert_batch("node_children", rows_batch)


# --- Parsing Logic ---

def determine_message_kind(role: str, ctype: str, recipient: str, content: Dict[str, Any]) -> str:
    if role == "user":
        return "user_visible_user"
    
    if role == "system":
        return "system_context"
        
    if role == "tool":
        return "tool_result"
        
    if role == "assistant":
        if ctype == "code" and recipient != "all":
            return "tool_call"
        if ctype in ("reasoning_recap", "thoughts", "model_thoughts"):
            return "internal_reasoning"
        return "user_visible_assistant"
        
    return "unknown"
def process_conversation(conv: Dict[str, Any],
                         writers: Dict[str, Any],
                         stats: Dict[str, Any],
                         run_id: str,
                         source_file: str) -> None:
    conv_id = conv.get("id") or conv.get("conversation_id")
    mapping = conv.get("mapping") or {}
    current_node_id = conv.get("current_node")

    # 1. Build Graph
    parents: Dict[str, Optional[str]] = {}
    children: Dict[str, List[str]] = defaultdict(list)
    for node_id, node in mapping.items():
        parent_id = node.get("parent")
        parents[node_id] = parent_id
        for child_id in node.get("children") or []:
            children[node_id].append(child_id)
            
    roots = [nid for nid, pid in parents.items() if pid is None]
    depth: Dict[str, int] = {}
    queue = deque(roots)
    for r in roots:
        depth[r] = 0
    
    while queue:
        nid = queue.popleft()
        d = depth[nid]
        for child_id in children.get(nid, []):
            if child_id not in depth:
                depth[child_id] = d + 1
                queue.append(child_id)

    # 2. Main Path
    main_path_index: Dict[str, int] = {}
    if current_node_id and current_node_id in mapping:
        path = []
        curr = current_node_id
        while curr and curr in mapping:
            path.append(curr)
            curr = parents.get(curr)
        path.reverse()
        main_path_index = {nid: idx for idx, nid in enumerate(path)}

    # 3. Time Index Calculation
    # Collect all messages, sort by created_at, assign index
    all_msgs = []
    for node_id, node in mapping.items():
        msg = node.get("message")
        if msg:
            create_time = msg.get("create_time") or 0
            all_msgs.append((create_time, node_id))
    
    all_msgs.sort(key=lambda x: x[0]) # stable sort by time
    time_indices = {nid: i for i, (ct, nid) in enumerate(all_msgs)}

    # 3b. Emit node_children edges for branch reconstruction
    for parent_node_id, child_list in children.items():
        for child_index, child_node_id in enumerate(child_list):
            edge_row = {
                "run_id": run_id,
                "conversation_id": conv_id,
                "parent_node_id": parent_node_id,
                "child_node_id": child_node_id,
                "child_index": child_index,
            }
            write_jsonl_line(writers["node_children"], edge_row)
            stats["node_children"] += 1

    # 4. Models Used
    models_used = set()
    message_count = 0
    
    # emit nodes & messages
    for node_id, node in mapping.items():
        if node is None:
            continue  # skip null mapping entries

        msg_obj = node.get("message") or {}

        # NODE
        node_row = {
            "run_id": run_id,
            "id": node_id,
            "conversation_id": conv_id,
            "parent_id": parents.get(node_id),
            "children_ids": children.get(node_id, []),
            "message_id": msg_obj.get("id") if isinstance(msg_obj, dict) else None,
            "is_root": parents.get(node_id) is None,
            "is_in_main_path": node_id in main_path_index,
            "depth": depth.get(node_id),
            "main_path_index": main_path_index.get(node_id),
        }
        write_jsonl_line(writers["nodes"], node_row)
        stats["nodes"] += 1

        # MESSAGE
        message = msg_obj if isinstance(msg_obj, dict) else None
        if message:
            message_count += 1
            msg_id = message.get("id")
            author = message.get("author") or {}
            role = author.get("role")
            content = message.get("content") or {}
            ctype = content.get("content_type")
            recipient = message.get("recipient")
            
            # Normalize text
            text = None
            if ctype == "text":
                parts = content.get("parts") or []
                text = "\n\n".join(str(p) for p in parts)
            elif ctype in ("code", "execution_output", "reasoning_recap"):
                text = content.get("text") or content.get("content")
            
            md = message.get("metadata") or {}
            if md.get("model_slug"): models_used.add(md["model_slug"])
            if md.get("default_model_slug"): models_used.add(md["default_model_slug"])

            m_kind = determine_message_kind(role, ctype, recipient, content)

            msg_row = {
                "run_id": run_id,
                "id": msg_id,
                "node_id": node_id,
                "conversation_id": conv_id,
                "role": role,
                "author_name": author.get("name"),
                "recipient": recipient,
                "channel": message.get("channel"),
                "content_type": ctype,
                "text": text,
                "raw_content": content,
                "created_at": iso_from_timestamp(message.get("create_time")),
                "updated_at": iso_from_timestamp(message.get("update_time")),
                "is_hidden": bool(md.get("is_visually_hidden_from_conversation")),
                "hidden_reason": "visually_hidden" if md.get("is_visually_hidden_from_conversation") else None,
                "is_in_main_path": node_id in main_path_index,
                "main_path_index": main_path_index.get(node_id),
                "depth": depth.get(node_id),
                "model": md.get("model_slug") or md.get("default_model_slug"),
                "metadata": md,
                "time_index": time_indices.get(node_id),
                "message_kind": m_kind,
            }
            write_jsonl_line(writers["messages"], msg_row)
            stats["messages"] += 1

            # Links (from text)
            for idx, (url, start, end) in enumerate(extract_urls_from_text(text or "")):
                scheme, domain, path, query = parse_url(url)
                link_row = {
                    "run_id": run_id,
                    "id": f"msg_{msg_id}_{idx}",
                    "conversation_id": conv_id,
                    "message_id": msg_id,
                    "source": "message_text",
                    "url": url,
                    "display_text": url,
                    "position_start": start,
                    "position_end": end,
                    "scheme": scheme,
                    "domain": domain,
                    "path": path,
                    "query": query,
                    "kind": None,
                    "metadata": {}
                }
                write_jsonl_line(writers["links"], link_row)
                stats["links"] += 1

            # Attachments (multimodal)
            if ctype == "multimodal_text":
                parts = content.get("parts") or []
                for idx, part in enumerate(parts):
                    if isinstance(part, dict) and part.get("content_type") == "image_asset_pointer":
                        att_row = {
                            "run_id": run_id,
                            "id": str(uuid.uuid4()),
                            "conversation_id": conv_id,
                            "message_id": msg_id,
                            "type": "image",
                            "filename": None,
                            "mime_type": None,
                            "filesize_bytes": part.get("size_bytes"),
                            "source_ref": part.get("asset_pointer"),
                            "metadata": {
                                "width": part.get("width"),
                                "height": part.get("height"),
                                **(part.get("metadata") or {})
                            }
                        }
                        write_jsonl_line(writers["attachments"], att_row)
                        stats["attachments"] += 1

            # Tools (Calls & Results)
            if m_kind == "tool_call":
                 # Try to parse arguments
                raw_args = content.get("text")
                args_json = None
                try:
                    if raw_args: args_json = json.loads(raw_args)
                except:
                    pass
                
                tc_row = {
                    "run_id": run_id,
                    "id": str(uuid.uuid4()),
                    "conversation_id": conv_id,
                    "message_id": msg_id,
                    "tool_name": recipient,
                    "call_index": 0,
                    "arguments_json": args_json,
                    "raw_arguments": raw_args,
                    "metadata": {}
                }
                write_jsonl_line(writers["tool_calls"], tc_row)
                stats["tool_calls"] += 1

            if m_kind == "tool_result":
                raw_res = content
                if content.get("content_type") == "execution_output":
                    raw_res = content.get("text")
                
                tr_row = {
                    "run_id": run_id,
                    "id": str(uuid.uuid4()),
                    "conversation_id": conv_id,
                    "message_id": msg_id,
                    "tool_call_id": None, # Hard to link without more context
                    "result_json": None,
                    "raw_result": raw_res,
                    "metadata": {}
                }
                write_jsonl_line(writers["tool_results"], tr_row)
                stats["tool_results"] += 1

    # Conversation Row
    safe_urls = conv.get("safe_urls") or []
    blocked_urls = conv.get("blocked_urls") or []
    
    conv_row = {
        "run_id": run_id,
        "id": conv_id,
        "source_id": conv.get("conversation_id") or conv_id,
        "title": conv.get("title"),
        "created_at": iso_from_timestamp(conv.get("create_time")),
        "updated_at": iso_from_timestamp(conv.get("update_time")),
        "default_model": conv.get("default_model_slug"),
        "models_used": sorted(list(models_used)),
        "is_archived": conv.get("is_archived"),
        "is_starred": conv.get("is_starred"),
        "current_node_id": conv.get("current_node"),
        "message_count": message_count,
        "safe_url_count": len(safe_urls),
        "blocked_url_count": len(blocked_urls),
        "metadata": {
            "conversation_origin": conv.get("conversation_origin"),
            "is_do_not_remember": conv.get("is_do_not_remember"),
             # ... add other fields if needed
        },
        "source_file": source_file
    }
    write_jsonl_line(writers["conversations"], conv_row)
    stats["conversations"] += 1

    # Conv-level links
    for idx, url in enumerate(safe_urls):
        scheme, domain, path, query = parse_url(url)
        link_row = {
            "run_id": run_id,
            "id": f"safe_{conv_id}_{idx}",
            "conversation_id": conv_id,
            "message_id": None,
            "source": "safe_url",
            "url": url,
            "display_text": url,
            "position_start": None,
            "position_end": None,
            "scheme": scheme,
            "domain": domain,
            "path": path,
            "query": query,
            "kind": None,
            "metadata": {}
        }
        write_jsonl_line(writers["links"], link_row)
        stats["links"] += 1


def run_parse(args, logger):
    run_id = args.run_id or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    streaming = getattr(args, "streaming", False)
    stream_chunk_size = getattr(args, "stream_chunk_size", 65536)
    input_paths: List[str] = args.inputs
    
    # Determine output directory
    if args.output_dir:
        # If explicit output dir, use it (must be empty or forced)
        out_dir = args.output_dir
        if os.path.exists(out_dir) and os.listdir(out_dir) and not args.force:
            logger.error(f"Output directory {out_dir} is not empty. Use --force.")
            return None
    else:
        # Use output root
        root = args.output_root or "normalized_runs"
        out_dir = os.path.join(root, run_id)
    
    os.makedirs(out_dir, exist_ok=True)
    attach_file_handler(logger, out_dir)
    
    # Open writers
    files = [
        "conversations",
        "nodes",
        "node_children",
        "messages",
        "links",
        "attachments",
        "tool_calls",
        "tool_results",
    ]
    writers = {name: open(os.path.join(out_dir, f"{name}.jsonl"), "w", encoding="utf-8") for name in files}
    
    stats = defaultdict(int)
    stats["start_time"] = time.time()
    
    # Helper to yield conversations from a path (json or zip)
    def iter_conversations(path: str):
        if path.lower().endswith(".zip"):
            if streaming:
                with zipfile.ZipFile(path, "r") as z:
                    if "conversations.json" not in z.namelist():
                        raise FileNotFoundError("Zip does not contain conversations.json")
                    with z.open("conversations.json") as f:
                        # zip returns bytes; wrap in TextIO
                        import io
                        text_file = io.TextIOWrapper(f, encoding="utf-8")
                        for conv in stream_json_array_from_file(text_file, chunk_size=stream_chunk_size):
                            yield conv
            else:
                with zipfile.ZipFile(path, "r") as z:
                    if "conversations.json" not in z.namelist():
                        raise FileNotFoundError("Zip does not contain conversations.json")
                    with z.open("conversations.json") as f:
                        import io
                        data = json.load(io.TextIOWrapper(f, encoding="utf-8"))
                        if isinstance(data, list):
                            for conv in data:
                                yield conv
                        else:
                            logger.error(f"Zip {path} conversations.json is not a list.")
        else:
            if streaming:
                for conv in stream_json_array(path, chunk_size=stream_chunk_size):
                    yield conv
            else:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    for conv in data:
                        yield conv
                else:
                    logger.error(f"File {path} does not contain a list.")

    # Parse
    for path in input_paths:
        try:
            logger.info(f"Reading {path}...")
            for conv in iter_conversations(path):
                try:
                    process_conversation(conv, writers, stats, run_id, path)
                except Exception:
                    stats["errors"] += 1
                    logger.exception(f"Error processing conversation in {path}")
        except Exception:
            stats["file_errors"] += 1
            logger.exception(f"Failed to read file {path}")

    # Close
    for f in writers.values():
        f.close()
        
    stats["end_time"] = time.time()
    stats["elapsed"] = stats["end_time"] - stats["start_time"]
    
    # Write run.json
    run_meta = {
        "run_id": run_id,
        "created_at": iso_from_timestamp(time.time()),
        "input_files": args.inputs,
        "stats": dict(stats),
        "version": "0.2.0"
    }
    with open(os.path.join(out_dir, "run.json"), "w", encoding="utf-8") as f:
        json.dump(run_meta, f, indent=2)

    # Write a manifest.json describing outputs (top-level JSON summary)
    manifest = {
        "run_id": run_id,
        "output_dir": out_dir,
        "created_at": run_meta["created_at"],
        "log_file": os.path.join(out_dir, "parser.log"),
        "run_json": os.path.join(out_dir, "run.json"),
        "files": {},
        "stats": {
            "conversations": stats.get("conversations", 0),
            "nodes": stats.get("nodes", 0),
            "messages": stats.get("messages", 0),
            "links": stats.get("links", 0),
            "attachments": stats.get("attachments", 0),
            "tool_calls": stats.get("tool_calls", 0),
            "tool_results": stats.get("tool_results", 0),
            "errors": stats.get("errors", 0),
            "file_errors": stats.get("file_errors", 0),
            "elapsed": stats.get("elapsed"),
        },
    }
    for name in files:
        path = os.path.join(out_dir, f"{name}.jsonl")
        manifest["files"][name + ".jsonl"] = {
            "path": path,
            "size_bytes": os.path.getsize(path) if os.path.exists(path) else 0,
            "records": stats.get(name, 0),
        }
    with open(os.path.join(out_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
        
    logger.info(f"Run {run_id} finished. Output: {out_dir}")
    return out_dir, run_id


def run_ingest(args, logger):
    if not args.db:
        logger.error("--db is required for ingest.")
        return

    db_mgr = SQLiteManager(args.db, args.mode)
    try:
        # If jsonl_dir is specified, ingest that
        if args.jsonl_dir:
            # We need a run_id. If not provided, try to guess from folder name or run.json
            run_id = args.run_id
            if not run_id:
                # check run.json
                run_json_path = os.path.join(args.jsonl_dir, "run.json")
                if os.path.exists(run_json_path):
                    with open(run_json_path) as f:
                        run_id = json.load(f).get("run_id")

            if not run_id:
                run_id = os.path.basename(args.jsonl_dir.rstrip("/\\"))

            db_mgr.ingest_run(args.jsonl_dir, run_id)
        else:
            logger.error("Must specify --jsonl-dir for ingest.")
    finally:
        db_mgr.conn.close()

def run_query(args, logger):
    if not os.path.exists(args.db):
        logger.error(f"DB {args.db} not found.")
        return

    conn = connect_db(args.db)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    res = []
    if args.type == "conversations":
        limit = args.limit or 10
        cur.execute(f"SELECT * FROM conversations ORDER BY created_at DESC LIMIT ?", (limit,))
        res = [dict(r) for r in cur.fetchall()]
    
    elif args.type == "conversation_detail":
        cid = args.conversation_id
        if not cid:
            logger.error("--conversation-id required")
            return
        
        # Fetch conv
        cur.execute("SELECT * FROM conversations WHERE id = ?", (cid,))
        conv = cur.fetchone()
        if not conv:
            logger.error("Conversation not found")
            return
            
        # Fetch messages
        # optionally include hidden
        sql = "SELECT * FROM messages WHERE conversation_id = ? "
        if str(args.include_hidden).lower() == "false":
            sql += " AND is_hidden = 0 "
        sql += " ORDER BY time_index ASC"
        
        cur.execute(sql, (cid,))
        msgs = [dict(r) for r in cur.fetchall()]
        
        res = {"conversation": dict(conv), "messages": msgs}
    
    conn.close()
    
    if args.format == "json":
        print(json.dumps(res, default=str, indent=2))
    else:
        print(res)


def run_search(args, logger):
    if not os.path.exists(args.db):
        logger.error(f"DB {args.db} not found.")
        return

    conn = connect_db(args.db)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Ensure FTS exists
    cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='message_fts'"
    )
    if not cur.fetchone():
        logger.error("message_fts not found. Run migrate first.")
        return

    sql = """
    SELECT m.conversation_id, m.id AS message_id, m.created_at, m.role, m.message_kind, m.text
    FROM message_fts
    JOIN messages m
      ON m.id = message_fts.message_id
     AND m.run_id = message_fts.run_id
    WHERE message_fts MATCH ?
    """
    params = [args.q]
    if args.role:
        sql += " AND m.role = ?"
        params.append(args.role)
    if args.kind:
        sql += " AND m.message_kind = ?"
        params.append(args.kind)
    if args.conversation_id:
        sql += " AND m.conversation_id = ?"
        params.append(args.conversation_id)
    if args.run_id:
        sql += " AND message_fts.run_id = ?"
        params.append(args.run_id)

    sql += " ORDER BY m.created_at DESC LIMIT ? OFFSET ?"
    params.extend([args.limit, args.offset])

    cur.execute(sql, params)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()

    if args.format == "json":
        print(json.dumps(rows, default=str, indent=2))
    else:
        for r in rows:
            print(f"[{r.get('created_at')}] {r.get('conversation_id')} #{r.get('message_id')}: {r.get('text')}")


def format_messages_markdown(conv: Dict[str, Any],
                             messages: List[Dict[str, Any]],
                             anchor: Optional[str] = None,
                             frontmatter: bool = False) -> str:
    """Render a conversation + messages into reasonably readable Markdown."""
    title = conv.get("title") or conv.get("id") or "Conversation"
    fm_lines = []
    if frontmatter:
        safe_title = (title or "").replace('"', '\\"')
        fm_lines.append("---")
        fm_lines.append(f'title: "{safe_title}"')
        fm_lines.append(f'conversation_id: "{conv.get("id")}"')
        if conv.get("created_at"):
            fm_lines.append(f'created_at: "{conv.get("created_at")}"')
        fm_lines.append("tags: [chatgpt_export]")
        fm_lines.append("---")
        fm_lines.append("")

    lines = []
    if anchor:
        lines.append(f"<a id=\"{anchor}\"></a>")
    lines.append(f"# {title}")
    lines.append("")
    lines.append(f"- Conversation ID: `{conv.get('id')}`")
    if conv.get("created_at"):
        lines.append(f"- Created at: {conv.get('created_at')}")
    lines.append("")

    for idx, msg in enumerate(messages, start=1):
        role = msg.get("role") or "unknown"
        header = f"## {idx}. {role}"
        if msg.get("created_at"):
            header += f" @ {msg['created_at']}"
        lines.append(header)
        if msg.get("message_kind"):
            lines.append(f"*kind:* `{msg['message_kind']}`")
        if msg.get("model"):
            lines.append(f"*model:* `{msg['model']}`")
        lines.append("")

        text = msg.get("text") or ""
        lines.append("```")
        lines.append(text)
        lines.append("```")
        lines.append("")
        lines.append("---")
        lines.append("")
    return "\n".join(fm_lines + lines)


def run_export_conversation(args, logger):
    if not os.path.exists(args.db):
        logger.error(f"DB {args.db} not found.")
        return
    conn = connect_db(args.db)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("SELECT * FROM conversations WHERE id = ?", (args.conversation_id,))
    conv = cur.fetchone()
    if not conv:
        logger.error("Conversation not found")
        return

    include_hidden = str(getattr(args, "include_hidden", "false")).lower() == "true"
    sql = "SELECT * FROM messages WHERE conversation_id = ?"
    params = [args.conversation_id]
    if not include_hidden:
        sql += " AND (is_hidden IS NULL OR is_hidden = 0)"
    sql += " ORDER BY time_index ASC"
    cur.execute(sql, params)
    messages = [dict(r) for r in cur.fetchall()]
    conv_dict = dict(conv)
    conn.close()

    if args.format == "json":
        content = json.dumps({"conversation": conv_dict, "messages": messages}, indent=2, default=str)
    else:
        fm = getattr(args, "frontmatter", False)
        content = format_messages_markdown(conv_dict, messages, frontmatter=fm)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(content)
        logger.info(f"Wrote conversation to {args.output}")
    else:
        print(content)


def run_export_conversations(args, logger):
    if not os.path.exists(args.db):
        logger.error(f"DB {args.db} not found.")
        return
    os.makedirs(args.output_dir, exist_ok=True)

    conn = connect_db(args.db)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    if args.query:
        cur.execute(
            """
            SELECT DISTINCT conversation_id FROM message_fts
            WHERE message_fts MATCH ?
            LIMIT ?
            """,
            (args.query, args.limit),
        )
    else:
        cur.execute(
            "SELECT id as conversation_id FROM conversations ORDER BY created_at DESC LIMIT ?",
            (args.limit,),
        )
    conv_ids = [r["conversation_id"] for r in cur.fetchall()]
    conn.close()

    for cid in conv_ids:
        out_name = f"{cid}.{ 'md' if args.format == 'markdown' else 'txt'}"
        out_path = os.path.join(args.output_dir, out_name)
        conv_args = argparse.Namespace(
            db=args.db,
            conversation_id=cid,
            format=args.format,
            output=out_path,
            include_hidden=args.include_hidden,
            frontmatter=getattr(args, "frontmatter", False),
        )
        run_export_conversation(conv_args, logger)


def run_check(args, logger):
    if not os.path.exists(args.db):
        logger.error(f"DB {args.db} not found.")
        return
    conn = connect_db(args.db)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    errors = []

    cur.execute(
        """
        SELECT m.id AS message_id, m.conversation_id, m.node_id
        FROM messages m
        LEFT JOIN nodes n ON m.node_id = n.id
        WHERE m.node_id IS NOT NULL AND n.id IS NULL
        """
    )
    for row in cur.fetchall():
        errors.append({"type": "orphan_message_node", **dict(row)})

    cur.execute(
        """
        SELECT n.id AS node_id, n.conversation_id, n.message_id
        FROM nodes n
        LEFT JOIN messages m ON n.message_id = m.id
        WHERE n.message_id IS NOT NULL AND m.id IS NULL
        """
    )
    for row in cur.fetchall():
        errors.append({"type": "orphan_node_message", **dict(row)})

    cur.execute(
        """
        SELECT c.id AS conversation_id, c.current_node_id
        FROM conversations c
        LEFT JOIN nodes n ON c.current_node_id = n.id
        WHERE c.current_node_id IS NOT NULL AND n.id IS NULL
        """
    )
    for row in cur.fetchall():
        errors.append({"type": "current_node_missing", **dict(row)})

    conn.close()
    ok = len(errors) == 0
    result = {"ok": ok, "errors": errors}
    if args.format == "json":
        print(json.dumps(result, indent=2))
    else:
        if ok:
            print("ok")
        else:
            print(f"errors found: {len(errors)}")
            for e in errors[:20]:
                print(e)


def run_list_runs(args, logger):
    if not os.path.exists(args.db):
        logger.error(f"DB {args.db} not found.")
        return
    conn = connect_db(args.db)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM runs ORDER BY started_at DESC")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    if args.format == "json":
        print(json.dumps(rows, indent=2))
    else:
        for r in rows:
            print(f"{r.get('run_id')} -> {r.get('jsonl_dir')} ({r.get('started_at')})")


def run_diff_runs(args, logger):
    if not os.path.exists(args.db):
        logger.error(f"DB {args.db} not found.")
        return
    conn = connect_db(args.db)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    def _fetch(run_id):
        cur.execute(
            "SELECT id, message_count FROM conversations WHERE run_id = ?",
            (run_id,),
        )
        return {row["id"]: row["message_count"] for row in cur.fetchall()}

    a = _fetch(args.run_a)
    b = _fetch(args.run_b)
    only_in_a = sorted(list(set(a.keys()) - set(b.keys())))
    only_in_b = sorted(list(set(b.keys()) - set(a.keys())))
    changed = []
    for cid in set(a.keys()) & set(b.keys()):
        if a[cid] != b[cid]:
            changed.append(
                {"conversation_id": cid, "message_count_a": a[cid], "message_count_b": b[cid]}
            )
    result = {"only_in_a": only_in_a, "only_in_b": only_in_b, "changed": changed}
    conn.close()
    if args.format == "json":
        print(json.dumps(result, indent=2))
    else:
        print(result)


def run_dump_db(args, logger):
    if not os.path.exists(args.db):
        logger.error(f"DB {args.db} not found.")
        return
    with connect_db(args.db) as conn, open(args.output, "w", encoding="utf-8") as f:
        for line in conn.iterdump():
            f.write(f"{line}\n")
    logger.info(f"Dumped DB to {args.output}")


def run_restore_db(args, logger):
    if os.path.exists(args.db) and not args.force:
        logger.error(f"DB {args.db} already exists. Use --force to overwrite.")
        return
    if os.path.exists(args.db):
        os.remove(args.db)
    with connect_db(args.db) as conn, open(args.input, "r", encoding="utf-8") as f:
        conn.execute("PRAGMA foreign_keys = OFF")
        sql_script = f.read()
        conn.executescript(sql_script)
        conn.execute("PRAGMA foreign_keys = ON")
    logger.info(f"Restored DB to {args.db}")


def get_schema_version(conn: sqlite3.Connection) -> int:
    try:
        cur = conn.execute(
            "SELECT value FROM meta WHERE key='schema_version'"
        )
        row = cur.fetchone()
        if row:
            return int(row[0])
    except Exception:
        return 0
    return 0


def table_exists(cur: sqlite3.Cursor, name: str) -> bool:
    cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name = ?",
        (name,),
    )
    return cur.fetchone() is not None


def rebuild_message_fts(cur: sqlite3.Cursor) -> None:
    cur.execute("DROP TABLE IF EXISTS message_fts;")
    cur.execute(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS message_fts USING fts5(
            message_id UNINDEXED,
            conversation_id UNINDEXED,
            run_id UNINDEXED,
            role,
            text,
            tokenize='unicode61'
        );
        """
    )
    cur.execute(
        "SELECT id, conversation_id, run_id, role, text FROM messages WHERE text IS NOT NULL"
    )
    rows = cur.fetchall()
    if rows:
        cur.executemany(
            "INSERT INTO message_fts(message_id, conversation_id, run_id, role, text) VALUES (?, ?, ?, ?, ?)",
            rows,
        )


def backfill_node_children(cur: sqlite3.Cursor, logger: logging.Logger) -> None:
    if not table_exists(cur, "node_children"):
        return
    cur.execute("SELECT 1 FROM node_children LIMIT 1")
    if cur.fetchone():
        return

    cur.execute(
        "SELECT run_id, conversation_id, id, children_ids FROM nodes"
    )
    rows = cur.fetchall()
    to_insert = []
    for run_id, conversation_id, parent_node_id, children_json in rows:
        if not children_json:
            continue
        if isinstance(children_json, list):
            children = children_json
        else:
            try:
                children = json.loads(children_json)
            except Exception:
                logger.warning("Failed to parse children_ids JSON; skipping row.")
                continue
        if not isinstance(children, list):
            continue
        for child_index, child_node_id in enumerate(children):
            to_insert.append(
                (run_id, conversation_id, parent_node_id, child_node_id, child_index)
            )
    if to_insert:
        cur.executemany(
            """
            INSERT OR IGNORE INTO node_children
            (run_id, conversation_id, parent_node_id, child_node_id, child_index)
            VALUES (?, ?, ?, ?, ?)
            """,
            to_insert,
        )


def run_migrate(args, logger):
    if not os.path.exists(args.db):
        logger.error(f"DB {args.db} not found.")
        return
    conn = connect_db(args.db)
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
    version = get_schema_version(conn)

    if version >= CURRENT_SCHEMA_VERSION:
        logger.info("Schema already up to date.")
        conn.close()
        return

    logger.info(f"Migrating schema from {version} to {CURRENT_SCHEMA_VERSION}...")
    cur.execute("PRAGMA foreign_keys = OFF")
    try:
        tables_to_rebuild = [
            "conversations",
            "nodes",
            "messages",
            "links",
            "attachments",
            "tool_calls",
            "tool_results",
        ]
        for table in tables_to_rebuild:
            if table_exists(cur, table):
                cur.execute(f"ALTER TABLE {table} RENAME TO {table}_old")

        cur.execute("DROP TABLE IF EXISTS message_fts;")
        cur.execute("DROP TABLE IF EXISTS node_children;")

        for stmt in CREATE_TABLES_SQL:
            cur.execute(stmt)

        table_columns = {
            "conversations": [
                "run_id",
                "id",
                "source_id",
                "title",
                "created_at",
                "updated_at",
                "default_model",
                "models_used",
                "is_archived",
                "is_starred",
                "current_node_id",
                "message_count",
                "safe_url_count",
                "blocked_url_count",
                "metadata",
                "source_file",
            ],
            "nodes": [
                "run_id",
                "id",
                "conversation_id",
                "parent_id",
                "children_ids",
                "message_id",
                "is_root",
                "is_in_main_path",
                "depth",
                "main_path_index",
            ],
            "messages": [
                "run_id",
                "id",
                "node_id",
                "conversation_id",
                "role",
                "author_name",
                "recipient",
                "channel",
                "content_type",
                "text",
                "raw_content",
                "created_at",
                "updated_at",
                "is_hidden",
                "hidden_reason",
                "is_in_main_path",
                "main_path_index",
                "depth",
                "model",
                "metadata",
                "time_index",
                "message_kind",
            ],
            "links": [
                "run_id",
                "id",
                "conversation_id",
                "message_id",
                "source",
                "url",
                "display_text",
                "position_start",
                "position_end",
                "scheme",
                "domain",
                "path",
                "query",
                "kind",
                "metadata",
            ],
            "attachments": [
                "run_id",
                "id",
                "conversation_id",
                "message_id",
                "type",
                "filename",
                "mime_type",
                "filesize_bytes",
                "source_ref",
                "metadata",
            ],
            "tool_calls": [
                "run_id",
                "id",
                "conversation_id",
                "message_id",
                "tool_name",
                "call_index",
                "arguments_json",
                "raw_arguments",
                "metadata",
            ],
            "tool_results": [
                "run_id",
                "id",
                "conversation_id",
                "message_id",
                "tool_call_id",
                "result_json",
                "raw_result",
                "metadata",
            ],
        }

        for table, columns in table_columns.items():
            old_table = f"{table}_old"
            if not table_exists(cur, old_table):
                continue
            cols = ", ".join(columns)
            cur.execute(
                f"INSERT INTO {table} ({cols}) SELECT {cols} FROM {old_table}"
            )
            cur.execute(f"DROP TABLE {old_table}")

        backfill_node_children(cur, logger)
        rebuild_message_fts(cur)

        cur.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES ('schema_version', ?)",
            (str(CURRENT_SCHEMA_VERSION),),
        )
        cur.execute(
            "INSERT OR IGNORE INTO meta(key, value) VALUES ('created_at', datetime('now'))"
        )
        conn.commit()
    except Exception:
        conn.rollback()
        logger.exception("Migration failed.")
        return
    finally:
        cur.execute("PRAGMA foreign_keys = ON")

    cur.execute("PRAGMA foreign_key_check")
    violations = cur.fetchall()
    if violations:
        logger.warning("Foreign key check found %d issues.", len(violations))
    else:
        logger.info("Foreign key check passed.")
    conn.close()


def markdown_escape(text: str) -> str:
    return text.replace("\n", " ").strip()


def run_export_bundle(args, logger):
    if not os.path.exists(args.db):
        logger.error(f"DB {args.db} not found.")
        return
    os.makedirs(os.path.dirname(args.output_markdown) or ".", exist_ok=True)

    conn = connect_db(args.db)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute(
        """
        SELECT id, title, created_at FROM conversations
        WHERE created_at IS NOT NULL
          AND created_at >= datetime('now', ?)
        ORDER BY created_at DESC
        """,
        (f"-{args.since_days} days",),
    )
    conversations = cur.fetchall()

    include_hidden = str(getattr(args, "include_hidden", "false")).lower() == "true"

    sections = []
    toc = []
    for idx, conv in enumerate(conversations, start=1):
        cid = conv["id"]
        anchor = f"conv-{idx}"
        title = conv["title"] or cid
        toc.append(f"- [{markdown_escape(title)} — {conv['created_at']}](#{anchor})")

        cur.execute(
            "SELECT * FROM messages WHERE conversation_id = ?"
            + ("" if include_hidden else " AND (is_hidden IS NULL OR is_hidden = 0)")
            + " ORDER BY time_index ASC",
            (cid,),
        )
        messages = [dict(r) for r in cur.fetchall()]

        conv_dict = {"id": cid, "title": title, "created_at": conv["created_at"]}
        sections.append(format_messages_markdown(conv_dict, messages, anchor=anchor, frontmatter=getattr(args, "frontmatter", False)))

    conn.close()

    content_parts = ["# Conversations (last {} days)".format(args.since_days), "", "## Table of Contents", ""]
    content_parts.append('<div class="toc">')
    content_parts.extend(toc)
    content_parts.append("</div>")
    content_parts.append("")
    content_parts.extend(sections)
    content = "\n".join(content_parts)

    with open(args.output_markdown, "w", encoding="utf-8") as f:
        f.write(content)
    logger.info(f"Wrote bundled markdown to {args.output_markdown}")

    pandoc = shutil.which("pandoc")
    css_path = args.css
    if not css_path:
        css_path = os.path.join(os.path.dirname(args.output_markdown) or ".", "bundle.css")
    if not os.path.exists(css_path):
        try:
            with open(css_path, "w", encoding="utf-8") as cssf:
                cssf.write(DEFAULT_CSS)
        except Exception as e:
            logger.warning(f"Could not write default CSS: {e}")

    if args.output_html:
        if pandoc:
            cmd = [pandoc, args.output_markdown, "-o", args.output_html, "--toc", "--self-contained"]
            if css_path and os.path.exists(css_path):
                cmd += ["--css", css_path]
            try:
                subprocess.run(cmd, check=True)
                logger.info(f"Wrote HTML via pandoc to {args.output_html}")
            except subprocess.CalledProcessError:
                logger.error("pandoc failed to generate HTML.")
        else:
            logger.warning("pandoc not found; skipping HTML export.")

    if args.output_pdf:
        if pandoc:
            pdf_engine = args.pdf_engine
            if not pdf_engine:
                for candidate in ["wkhtmltopdf", "weasyprint", "prince", "chromium", "google-chrome", "msedge"]:
                    if shutil.which(candidate):
                        pdf_engine = candidate
                        break
            if not pdf_engine:
                logger.warning("No PDF engine found (wkhtmltopdf/weasyprint/etc). Skipping PDF export.")
            else:
                cmd = [pandoc, args.output_markdown, "-o", args.output_pdf, "--toc", "--pdf-engine", pdf_engine]
                if css_path and os.path.exists(css_path):
                    cmd += ["--css", css_path]
                try:
                    subprocess.run(cmd, check=True)
                    logger.info(f"Wrote PDF via pandoc to {args.output_pdf}")
                except subprocess.CalledProcessError:
                    logger.error("pandoc failed to generate PDF.")
        else:
            logger.warning("pandoc not found; skipping PDF export.")

# --- Main ---

def main():
    parser = argparse.ArgumentParser(description="ChatGPT Export Parser & SQLite Ingester")
    parser.add_argument("--json", action="store_true", help="Output machine-readable JSON summary to stdout")
    parser.add_argument("--verbose", action="store_true", default=True, help="Verbose logging")
    parser.add_argument("--quiet", action="store_true", help="Suppress stdout logging")

    subparsers = parser.add_subparsers(dest="command", required=True)

    # PARSE
    p_parse = subparsers.add_parser("parse", help="Normalize JSON to JSONL")
    p_parse.add_argument("inputs", nargs="+", help="Input JSON files")
    p_parse.add_argument("--output-dir", help="Specific output directory (must be empty)")
    p_parse.add_argument("--output-root", help="Root directory for runs (default: ./normalized_runs)")
    p_parse.add_argument("--run-id", help="Manual run ID")
    p_parse.add_argument("--force", action="store_true", help="Overwrite existing output-dir")
    p_parse.add_argument("--no-streaming", dest="streaming", action="store_false", help="Disable streaming parser (default: on)")
    p_parse.set_defaults(streaming=True)

    # INGEST
    p_ingest = subparsers.add_parser("ingest", help="Ingest JSONL to SQLite")
    p_ingest.add_argument("--jsonl-dir", required=True, help="Directory containing JSONL files")
    p_ingest.add_argument("--db", required=True, help="Path to SQLite DB")
    p_ingest.add_argument("--mode", choices=["skip_existing", "overwrite"], default="skip_existing")
    p_ingest.add_argument("--run-id", help="Override run ID")

    # PARSE-AND-INGEST
    p_both = subparsers.add_parser("parse-and-ingest", help="Parse then Ingest")
    p_both.add_argument("inputs", nargs="+", help="Input JSON files")
    p_both.add_argument("--output-dir", help="Specific output directory")
    p_both.add_argument("--output-root", help="Root directory for runs")
    p_both.add_argument("--run-id", help="Manual run ID")
    p_both.add_argument("--force", action="store_true")
    p_both.add_argument("--db", required=True, help="Path to SQLite DB")
    p_both.add_argument("--mode", choices=["skip_existing", "overwrite"], default="skip_existing")
    p_both.add_argument("--no-streaming", dest="streaming", action="store_false", help="Disable streaming parser (default: on)")
    p_both.set_defaults(streaming=True)

    # QUERY
    p_query = subparsers.add_parser("query", help="Query DB")
    p_query.add_argument("--db", required=True)
    p_query.add_argument("--type", choices=["conversations", "conversation_detail"], required=True)
    p_query.add_argument("--limit", type=int, default=10)
    p_query.add_argument("--conversation-id")
    p_query.add_argument("--include-hidden", default="false")
    p_query.add_argument("--format", choices=["json", "text"], default="text")
    p_query.add_argument("--order-by") # Not fully impl yet but in args

    # SEARCH (FTS)
    p_search = subparsers.add_parser("search", help="Full-text search over messages")
    p_search.add_argument("--db", required=True)
    p_search.add_argument("--q", required=True, help="FTS query string")
    p_search.add_argument("--role")
    p_search.add_argument("--kind")
    p_search.add_argument("--conversation-id")
    p_search.add_argument("--run-id")
    p_search.add_argument("--limit", type=int, default=50)
    p_search.add_argument("--offset", type=int, default=0)
    p_search.add_argument("--format", choices=["json", "text"], default="json")

    # EXPORT (single)
    p_export = subparsers.add_parser("export-conversation", help="Export a conversation to markdown/text")
    p_export.add_argument("--db", required=True)
    p_export.add_argument("--conversation-id", required=True)
    p_export.add_argument("--format", choices=["markdown", "text", "json"], default="markdown")
    p_export.add_argument("--output", help="Output file (default: stdout)")
    p_export.add_argument("--include-hidden", default="false")
    p_export.add_argument("--frontmatter", action="store_true", help="Include YAML frontmatter in markdown export")

    # EXPORT (batch)
    p_exports = subparsers.add_parser("export-conversations", help="Export multiple conversations")
    p_exports.add_argument("--db", required=True)
    p_exports.add_argument("--query", help="FTS query to select conversations")
    p_exports.add_argument("--limit", type=int, default=20)
    p_exports.add_argument("--output-dir", required=True)
    p_exports.add_argument("--format", choices=["markdown", "text"], default="markdown")
    p_exports.add_argument("--include-hidden", default="false")
    p_exports.add_argument("--frontmatter", action="store_true", help="Include YAML frontmatter in markdown export")

    # EXPORT BUNDLE
    p_bundle = subparsers.add_parser("export-bundle", help="Export multiple conversations into one markdown with TOC")
    p_bundle.add_argument("--db", required=True)
    p_bundle.add_argument("--since-days", type=int, default=9, help="Lookback window in days (default: 9)")
    p_bundle.add_argument("--output-markdown", default="./exports/recent_bundle.md")
    p_bundle.add_argument("--output-html", help="Optional HTML output (requires pandoc)")
    p_bundle.add_argument("--output-pdf", help="Optional PDF output (requires pandoc)")
    p_bundle.add_argument("--css", help="Optional CSS file for HTML/PDF styling")
    p_bundle.add_argument("--pdf-engine", help="Override pandoc PDF engine (e.g., wkhtmltopdf, weasyprint, pdflatex)")
    p_bundle.add_argument("--include-hidden", default="false")
    p_bundle.add_argument("--frontmatter", action="store_true", help="Include YAML frontmatter in markdown export")

    # CHECK
    p_check = subparsers.add_parser("check", help="Integrity checks")
    p_check.add_argument("--db", required=True)
    p_check.add_argument("--format", choices=["json", "text"], default="json")

    # LIST RUNS
    p_runs = subparsers.add_parser("list-runs", help="List runs in DB")
    p_runs.add_argument("--db", required=True)
    p_runs.add_argument("--format", choices=["json", "text"], default="text")

    # DIFF RUNS
    p_diff = subparsers.add_parser("diff-runs", help="Diff two runs")
    p_diff.add_argument("--db", required=True)
    p_diff.add_argument("--run-a", required=True)
    p_diff.add_argument("--run-b", required=True)
    p_diff.add_argument("--format", choices=["json", "text"], default="json")

    # DUMP DB
    p_dump = subparsers.add_parser("dump-db", help="Dump SQLite DB to SQL file")
    p_dump.add_argument("--db", required=True)
    p_dump.add_argument("--output", required=True)

    # RESTORE DB
    p_restore = subparsers.add_parser("restore-db", help="Restore SQLite DB from SQL file")
    p_restore.add_argument("--input", required=True)
    p_restore.add_argument("--db", required=True)
    p_restore.add_argument("--force", action="store_true")

    # MIGRATE
    p_migrate = subparsers.add_parser("migrate", help="Apply schema migrations")
    p_migrate.add_argument("--db", required=True)

    args = parser.parse_args()
    
    logger_verbose = args.verbose and not args.quiet and not args.json
    logger = setup_logging(None, verbose=logger_verbose)

    summary = {}

    if args.command == "parse":
        res = run_parse(args, logger)
        if res:
            out_dir, run_id = res
            summary = {"run_id": run_id, "output_dir": out_dir}

    elif args.command == "ingest":
        run_ingest(args, logger)
        summary = {"status": "ingested", "db": args.db}

    elif args.command == "parse-and-ingest":
        res = run_parse(args, logger)
        if res:
            out_dir, run_id = res
            # Inject jsonl_dir for ingest
            args.jsonl_dir = out_dir
            run_ingest(args, logger)
            summary = {"run_id": run_id, "output_dir": out_dir, "db": args.db, "status": "completed"}
            
    elif args.command == "query":
        run_query(args, logger)
        return # Query handles its own output
    
    elif args.command == "search":
        run_search(args, logger)
        return

    elif args.command == "export-conversation":
        run_export_conversation(args, logger)
        return

    elif args.command == "export-conversations":
        run_export_conversations(args, logger)
        return

    elif args.command == "export-bundle":
        run_export_bundle(args, logger)
        return

    elif args.command == "check":
        run_check(args, logger)
        return

    elif args.command == "list-runs":
        run_list_runs(args, logger)
        return

    elif args.command == "diff-runs":
        run_diff_runs(args, logger)
        return

    elif args.command == "dump-db":
        run_dump_db(args, logger)
        summary = {"status": "dumped", "output": args.output}

    elif args.command == "restore-db":
        run_restore_db(args, logger)
        summary = {"status": "restored", "db": args.db}

    elif args.command == "migrate":
        run_migrate(args, logger)
        summary = {"status": "migrated", "db": args.db}

    if args.json:
        print(json.dumps(summary, indent=2))

if __name__ == "__main__":
    main()
