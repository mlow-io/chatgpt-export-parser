import argparse
import json
import logging
import os
import sqlite3
import time
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from typing import List, Optional

from ..db.manager import SQLiteManager, connect_db
from ..core.parser import process_conversation
from ..core.exporter import run_export_conversation, format_messages_markdown
from ..utils.io import stream_json_array, stream_json_array_from_file
from ..utils.logging import attach_file_handler
from ..utils.date import iso_from_timestamp
from ..config import DEFAULT_CSS

def run_parse(args, logger: logging.Logger):
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


def run_ingest(args, logger: logging.Logger):
    if not args.db:
        logger.error("--db is required for ingest.")
        return

    db_mgr = SQLiteManager(args.db, args.mode)
    try:
        if args.jsonl_dir:
            run_id = getattr(args, "run_id", None)
            if not run_id:
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


def run_query(args, logger: logging.Logger):
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
        
        cur.execute("SELECT * FROM conversations WHERE id = ?", (cid,))
        conv = cur.fetchone()
        if not conv:
            logger.error("Conversation not found")
            return
            
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


def run_search(args, logger: logging.Logger):
    if not os.path.exists(args.db):
        logger.error(f"DB {args.db} not found.")
        return

    conn = connect_db(args.db)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

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
        WHERE created_at IS NOT NULL
          AND created_at >= datetime('now', ?)
        ORDER BY created_at DESC
        """,
        (f"-{args.since_days} days",),
    )
    conversations = cur.fetchall()
    
    # Simple bundle implementation
    bundle_lines = ["# ChatGPT Conversation Bundle", ""]
    for conv in conversations:
        cur.execute(
            "SELECT * FROM messages WHERE conversation_id = ? ORDER BY time_index ASC",
            (conv["id"],),
        )
        msgs = [dict(r) for r in cur.fetchall()]
        bundle_lines.append(format_messages_markdown(dict(conv), msgs, anchor=conv["id"]))
        bundle_lines.append("\n\n---\n\n")

    with open(args.output_markdown, "w", encoding="utf-8") as f:
        f.write("\n".join(bundle_lines))
    
    logger.info(f"Wrote bundle to {args.output_markdown}")
    conn.close()

    # Pandoc logic omitted for brevity in this initial refactor, 
    # but could be added back if needed.
