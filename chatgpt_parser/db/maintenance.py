import json
import logging
import os
import sqlite3

from .common import connect_db


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
    with connect_db(args.db) as conn, open(args.output, "w", encoding="utf-8") as handle:
        for line in conn.iterdump():
            handle.write(f"{line}\n")
    logger.info(f"Dumped DB to {args.output}")


def run_restore_db(args, logger: logging.Logger):
    if os.path.exists(args.db) and not args.force:
        logger.error(f"DB {args.db} already exists. Use --force to overwrite.")
        return
    if os.path.exists(args.db):
        os.remove(args.db)
    with connect_db(args.db) as conn, open(args.input, "r", encoding="utf-8") as handle:
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.executescript(handle.read())
        conn.execute("PRAGMA foreign_keys = ON")
    logger.info(f"Restored DB to {args.db}")
