import argparse
import json
import logging
import os
import sqlite3
import time
import zipfile
from datetime import datetime, timezone
from typing import List

from ..core.exporter import format_messages_markdown, run_export_conversation
from ..db.canonical_manager import CanonicalManager
from ..db.common import connect_db
from ..utils.io import stream_json_array, stream_json_array_from_file


def run_canonical_ingest(args, logger: logging.Logger):
    input_paths = args.inputs
    streaming = getattr(args, "streaming", True)
    run_id = args.run_id or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    mgr = CanonicalManager(db_path=args.db, mode=args.mode)
    if not mgr.begin_run(run_id, input_paths):
        return {"run_id": run_id, "stats": dict(mgr.stats), "skipped": True}

    start_time = time.time()

    def iter_conversations(path: str):
        if path.lower().endswith(".zip"):
            with zipfile.ZipFile(path, "r") as archive:
                if "conversations.json" not in archive.namelist():
                    raise FileNotFoundError("Zip does not contain conversations.json")
                with archive.open("conversations.json") as handle:
                    import io
                    text_handle = io.TextIOWrapper(handle, encoding="utf-8")
                    if streaming:
                        yield from stream_json_array_from_file(text_handle)
                    else:
                        data = json.load(text_handle)
                        if isinstance(data, list):
                            yield from data
        else:
            if streaming:
                yield from stream_json_array(path)
            else:
                with open(path, "r", encoding="utf-8") as handle:
                    data = json.load(handle)
                if isinstance(data, list):
                    yield from data

    for path in input_paths:
        try:
            logger.info(f"Reading {path}...")
            for conv in iter_conversations(path):
                try:
                    mgr.ingest_conversation(conv, path, run_id=run_id)
                except Exception:
                    logger.exception(f"Error processing conversation in {path}")
        except Exception:
            logger.exception(f"Failed to read file {path}")

    mgr.finalize_run()
    elapsed = time.time() - start_time
    stats = dict(mgr.stats)
    logger.info(
        f"Canonical ingest complete: {stats.get('conversations', 0)} conversations, "
        f"{stats.get('messages', 0)} messages, {stats.get('links', 0)} links in {elapsed:.1f}s"
    )
    mgr.close()
    return {"run_id": run_id, "stats": stats, "elapsed_sec": elapsed, "skipped": False}


def run_query(args, logger: logging.Logger):
    if not os.path.exists(args.db):
        logger.error(f"DB {args.db} not found.")
        return

    conn = connect_db(args.db)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    result = []

    if args.type == "conversations":
        limit = args.limit or 10
        order_by = args.order_by or "COALESCE(updated_at, latest_message_at, created_at) DESC"
        cur.execute(f"SELECT * FROM conversations ORDER BY {order_by} LIMIT ?", (limit,))
        result = [dict(row) for row in cur.fetchall()]
    elif args.type == "conversation_detail":
        if not args.conversation_id:
            logger.error("--conversation-id required")
            return
        cur.execute("SELECT * FROM conversations WHERE id = ?", (args.conversation_id,))
        conversation = cur.fetchone()
        if not conversation:
            logger.error("Conversation not found")
            return
        sql = "SELECT * FROM messages WHERE conversation_id = ?"
        params = [args.conversation_id]
        if str(args.include_hidden).lower() == "false":
            sql += " AND (is_hidden IS NULL OR is_hidden = 0)"
        sql += " ORDER BY time_index ASC"
        cur.execute(sql, params)
        result = {"conversation": dict(conversation), "messages": [dict(row) for row in cur.fetchall()]}

    conn.close()

    if args.format == "json":
        print(json.dumps(result, default=str, indent=2))
    else:
        print(result)


def run_search(args, logger: logging.Logger):
    if not os.path.exists(args.db):
        logger.error(f"DB {args.db} not found.")
        return

    conn = connect_db(args.db)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='message_fts'")
    if not cur.fetchone():
        logger.error("message_fts not found.")
        return

    sql = """
    SELECT m.conversation_id, m.id AS message_id, m.created_at, m.role, m.message_kind, m.text
    FROM message_fts
    JOIN messages m
      ON m.id = message_fts.message_id
     AND m.conversation_id = message_fts.conversation_id
     AND (m.run_id = message_fts.run_id OR message_fts.run_id IS NULL)
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
    rows = [dict(row) for row in cur.fetchall()]
    conn.close()

    if args.format == "json":
        print(json.dumps(rows, default=str, indent=2))
    else:
        for row in rows:
            print(f"[{row.get('created_at')}] {row.get('conversation_id')} #{row.get('message_id')}: {row.get('text')}")


def run_export_conversations(args, logger: logging.Logger):
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
            "SELECT id AS conversation_id FROM conversations ORDER BY COALESCE(updated_at, latest_message_at, created_at) DESC LIMIT ?",
            (args.limit,),
        )

    conversation_ids = [row["conversation_id"] for row in cur.fetchall()]
    conn.close()

    for conversation_id in conversation_ids:
        output_name = f"{conversation_id}.{ 'md' if args.format == 'markdown' else 'txt'}"
        output_path = os.path.join(args.output_dir, output_name)
        conv_args = argparse.Namespace(
            db=args.db,
            conversation_id=conversation_id,
            format=args.format,
            output=output_path,
            include_hidden=args.include_hidden,
            frontmatter=getattr(args, "frontmatter", False),
        )
        run_export_conversation(conv_args, logger)


def run_export_bundle(args, logger: logging.Logger):
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
        WHERE COALESCE(created_at, updated_at, latest_message_at) IS NOT NULL
          AND COALESCE(created_at, updated_at, latest_message_at) >= datetime('now', ?)
        ORDER BY COALESCE(updated_at, latest_message_at, created_at) DESC
        """,
        (f"-{args.since_days} days",),
    )
    conversations = cur.fetchall()

    bundle_lines = ["# ChatGPT Conversation Bundle", ""]
    for conversation in conversations:
        cur.execute(
            "SELECT * FROM messages WHERE conversation_id = ? ORDER BY time_index ASC",
            (conversation["id"],),
        )
        messages = [dict(row) for row in cur.fetchall()]
        bundle_lines.append(format_messages_markdown(dict(conversation), messages, anchor=conversation["id"]))
        bundle_lines.append("\n\n---\n\n")

    with open(args.output_markdown, "w", encoding="utf-8") as handle:
        handle.write("\n".join(bundle_lines))
    logger.info(f"Wrote bundle to {args.output_markdown}")
    conn.close()
