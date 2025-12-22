import json
import logging
import os
import sqlite3
import time
from typing import Any, Dict, List, Optional, Tuple

from .schema import CREATE_TABLES_SQL
from ..config import CURRENT_SCHEMA_VERSION
from ..utils.date import iso_from_timestamp


def connect_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


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
