import json
import logging
import os
import sqlite3

from .common import connect_db
from .canonical_schema import CANONICAL_TABLES_SQL


def _message_fts_create_sql() -> str:
    for stmt in CANONICAL_TABLES_SQL:
        if "CREATE VIRTUAL TABLE IF NOT EXISTS message_fts USING fts5" in stmt:
            return stmt.strip()
    raise RuntimeError("message_fts schema definition not found")


def _portable_restore_script(script: str) -> str:
    """
    Normalize SQLite iterdump output so FTS5 virtual tables restore reliably.

    Raw iterdump output serializes FTS shadow tables and writable_schema edits,
    which is brittle to replay. For this repo we restore the logical virtual
    table definition plus its row inserts and skip the shadow-table internals.
    """
    restored_lines = []
    fts_create_sql = _message_fts_create_sql()
    inserted_fts_schema = False
    skipping_fts_sqlite_master = False

    for raw_line in script.splitlines():
        line = raw_line.strip()
        if skipping_fts_sqlite_master:
            if line.endswith(")');"):
                skipping_fts_sqlite_master = False
            continue
        if line in {"PRAGMA writable_schema=ON;", "PRAGMA writable_schema=OFF;"}:
            continue
        if "INSERT INTO sqlite_master" in raw_line and "'message_fts'" in raw_line:
            if not inserted_fts_schema:
                restored_lines.append(fts_create_sql)
                inserted_fts_schema = True
            skipping_fts_sqlite_master = True
            continue
        if "message_fts_" in raw_line:
            continue
        if line.startswith('INSERT INTO "message_fts"') or line.startswith("INSERT INTO 'message_fts'") or line.startswith("INSERT INTO message_fts"):
            if not inserted_fts_schema:
                restored_lines.append(fts_create_sql)
                inserted_fts_schema = True
            restored_lines.append(raw_line)
            continue
        restored_lines.append(raw_line)

    return "\n".join(restored_lines)


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
        LEFT JOIN nodes n
          ON m.conversation_id = n.conversation_id
         AND m.node_id = n.id
        WHERE m.node_id IS NOT NULL AND n.id IS NULL
        """
    )
    for row in cur.fetchall():
        errors.append({"type": "orphan_message_node", **dict(row)})

    cur.execute(
        """
        SELECT n.id AS node_id, n.conversation_id, n.message_id
        FROM nodes n
        LEFT JOIN messages m
          ON n.conversation_id = m.conversation_id
         AND n.message_id = m.id
        WHERE n.message_id IS NOT NULL AND m.id IS NULL
        """
    )
    for row in cur.fetchall():
        errors.append({"type": "orphan_node_message", **dict(row)})

    cur.execute(
        """
        SELECT c.id AS conversation_id, c.current_node_id
        FROM conversations c
        LEFT JOIN nodes n
          ON c.id = n.conversation_id
         AND c.current_node_id = n.id
        WHERE c.current_node_id IS NOT NULL AND n.id IS NULL
        """
    )
    for row in cur.fetchall():
        errors.append({"type": "current_node_missing", **dict(row)})

    conn.close()
    result = {"ok": len(errors) == 0, "errors": errors}
    if args.format == "json":
        print(json.dumps(result, indent=2))
    else:
        if result["ok"]:
            print("ok")
        else:
            print(f"errors found: {len(errors)}")
            for error in errors[:20]:
                print(error)


def run_list_runs(args, logger: logging.Logger):
    if not os.path.exists(args.db):
        logger.error(f"DB {args.db} not found.")
        return
    conn = connect_db(args.db)
    conn.row_factory = sqlite3.Row
    rows = [dict(row) for row in conn.execute("SELECT * FROM runs ORDER BY started_at DESC").fetchall()]
    conn.close()
    if args.format == "json":
        print(json.dumps(rows, indent=2))
    else:
        for row in rows:
            print(f"{row.get('run_id')} ({row.get('started_at')})")


def run_dump_db(args, logger: logging.Logger):
    if not os.path.exists(args.db):
        logger.error(f"DB {args.db} not found.")
        return
    conn = connect_db(args.db)
    try:
        with open(args.output, "w", encoding="utf-8") as handle:
            for line in conn.iterdump():
                handle.write(f"{line}\n")
    finally:
        conn.close()
    logger.info(f"Dumped DB to {args.output}")


def run_restore_db(args, logger: logging.Logger):
    if os.path.exists(args.db) and not args.force:
        logger.error(f"DB {args.db} already exists. Use --force to overwrite.")
        return
    if os.path.exists(args.db):
        os.remove(args.db)
    conn = connect_db(args.db)
    try:
        with open(args.input, "r", encoding="utf-8") as handle:
            conn.execute("PRAGMA foreign_keys = OFF")
            conn.executescript(_portable_restore_script(handle.read()))
            conn.execute("PRAGMA foreign_keys = ON")
            conn.commit()
    finally:
        conn.close()
    logger.info(f"Restored DB to {args.db}")
