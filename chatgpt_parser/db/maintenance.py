import json
import logging
import os
import sqlite3
from typing import Any, Dict, List, Optional

from .manager import connect_db, SQLiteManager
from .schema import CREATE_TABLES_SQL
from ..config import CURRENT_SCHEMA_VERSION


def run_check(args, logger: logging.Logger):
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


def run_list_runs(args, logger: logging.Logger):
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


def run_diff_runs(args, logger: logging.Logger):
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


def run_dump_db(args, logger: logging.Logger):
    if not os.path.exists(args.db):
        logger.error(f"DB {args.db} not found.")
        return
    with connect_db(args.db) as conn, open(args.output, "w", encoding="utf-8") as f:
        for line in conn.iterdump():
            f.write(f"{line}\n")
    logger.info(f"Dumped DB to {args.output}")


def run_restore_db(args, logger: logging.Logger):
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


def run_migrate(args, logger: logging.Logger):
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
                "run_id", "id", "source_id", "title", "created_at", "updated_at",
                "default_model", "models_used", "is_archived", "is_starred",
                "current_node_id", "message_count", "safe_url_count", "blocked_url_count",
                "metadata", "source_file",
            ],
            "nodes": [
                "run_id", "id", "conversation_id", "parent_id", "children_ids",
                "message_id", "is_root", "is_in_main_path", "depth", "main_path_index",
            ],
            "messages": [
                "run_id", "id", "node_id", "conversation_id", "role", "author_name",
                "recipient", "channel", "content_type", "text", "raw_content",
                "created_at", "updated_at", "is_hidden", "hidden_reason",
                "is_in_main_path", "main_path_index", "depth", "model", "metadata",
                "time_index", "message_kind",
            ],
            "links": [
                "run_id", "id", "conversation_id", "message_id", "source", "url",
                "display_text", "position_start", "position_end", "scheme", "domain",
                "path", "query", "kind", "metadata",
            ],
            "attachments": [
                "run_id", "id", "conversation_id", "message_id", "type", "filename",
                "mime_type", "filesize_bytes", "source_ref", "metadata",
            ],
            "tool_calls": [
                "run_id", "id", "conversation_id", "message_id", "tool_name",
                "call_index", "arguments_json", "raw_arguments", "metadata",
            ],
            "tool_results": [
                "run_id", "id", "conversation_id", "message_id", "tool_call_id",
                "result_json", "raw_result", "metadata",
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
        
        cur.execute("UPDATE meta SET value = ? WHERE key = 'schema_version'", (str(CURRENT_SCHEMA_VERSION),))
        conn.commit()
        logger.info(f"Migration to version {CURRENT_SCHEMA_VERSION} complete.")
    except Exception:
        conn.rollback()
        logger.exception("Migration failed")
    finally:
        cur.execute("PRAGMA foreign_keys = ON")
        conn.close()
