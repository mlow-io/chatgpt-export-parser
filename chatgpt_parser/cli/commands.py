import argparse
import io
import json
import logging
import os
import re
import sqlite3
import time
import zipfile
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List

from ..core.exporter import format_messages_markdown, run_export_conversation
from ..db.canonical_manager import CanonicalManager
from ..db.common import connect_db
from ..utils.io import stream_json_array, stream_json_array_from_file


CONVERSATION_FILE_RE = re.compile(r"^conversations(?:-\d+)?\.json$")


def _is_conversation_json_name(name: str) -> bool:
    return bool(CONVERSATION_FILE_RE.fullmatch(os.path.basename(name)))


def _inspect_chat_html(path: str) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "path": path,
        "kind": "chat_html",
        "status": "unsupported_for_canonical_ingest",
        "reason": "chat.html embeds rendered export data, but canonical ingest uses conversations JSON to preserve IDs, graph structure, metadata, and provenance.",
    }
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            text = handle.read()
        prefix = "var jsonData = "
        index = text.find(prefix)
        result["size_bytes"] = len(text.encode("utf-8", errors="ignore"))
        result["has_embedded_json_data"] = index >= 0
        if index >= 0:
            data, _ = json.JSONDecoder().raw_decode(text, index + len(prefix))
            if isinstance(data, list):
                result["embedded_conversation_count"] = len(data)
                times = [
                    item.get("create_time")
                    for item in data
                    if isinstance(item, dict) and item.get("create_time") is not None
                ]
                if times:
                    result["embedded_min_create_time"] = min(times)
                    result["embedded_max_create_time"] = max(times)
    except Exception as exc:
        result["inspection_error"] = str(exc)
    return result


def _chat_html_observed(path: str, reason: str) -> Dict[str, Any]:
    result = {
        "path": path,
        "kind": "chat_html",
        "status": "observed_not_ingested",
        "reason": reason,
    }
    try:
        result["size_bytes"] = os.path.getsize(path)
    except OSError:
        pass
    return result


def _discover_input_sources(input_paths: List[str], *, include_diagnostics: bool = False) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    sources: List[Dict[str, Any]] = []
    diagnostics: List[Dict[str, Any]] = []

    for input_path in input_paths:
        if os.path.isdir(input_path):
            entries = sorted(os.path.join(input_path, name) for name in os.listdir(input_path))
            conversation_files = [path for path in entries if os.path.isfile(path) and _is_conversation_json_name(path)]
            for path in conversation_files:
                sources.append({"kind": "json_file", "path": path, "origin": input_path})
            chat_html = os.path.join(input_path, "chat.html")
            if os.path.exists(chat_html):
                diagnostics.append(_chat_html_observed(
                    chat_html,
                    "folder contains canonical JSON source files; chat.html is not used for canonical ingest",
                ))
            if not conversation_files:
                diagnostics.append({
                    "path": input_path,
                    "kind": "directory",
                    "status": "no_conversation_json_files",
                    "reason": "expected conversations.json or conversations-###.json",
                })
            continue

        lower_path = input_path.lower()
        if lower_path.endswith(".zip"):
            try:
                with zipfile.ZipFile(input_path, "r") as archive:
                    members = sorted(
                        name for name in archive.namelist()
                        if not name.endswith("/") and _is_conversation_json_name(name)
                    )
                    for member in members:
                        sources.append({"kind": "zip_member", "path": input_path, "member": member, "origin": input_path})
                    html_members = sorted(
                        name for name in archive.namelist()
                        if os.path.basename(name).lower() == "chat.html"
                    )
                    for member in html_members:
                        diagnostics.append({
                            "path": input_path,
                            "member": member,
                            "kind": "chat_html",
                            "status": "observed_not_ingested",
                            "reason": "ZIP contains canonical JSON source files; chat.html is not used for canonical ingest",
                        })
                    if not members:
                        diagnostics.append({
                            "path": input_path,
                            "kind": "zip",
                            "status": "no_conversation_json_files",
                            "reason": "expected conversations.json or conversations-###.json in ZIP",
                        })
            except Exception as exc:
                diagnostics.append({"path": input_path, "kind": "zip", "status": "discovery_error", "error": str(exc)})
            continue

        if lower_path.endswith(".html") and os.path.basename(lower_path) == "chat.html":
            diagnostics.append(_inspect_chat_html(input_path))
            continue

        if lower_path.endswith(".json"):
            sources.append({"kind": "json_file", "path": input_path, "origin": input_path})
            continue

        diagnostics.append({
            "path": input_path,
            "kind": "unknown",
            "status": "unsupported_input",
            "reason": "expected JSON file, export folder, ZIP file, or chat.html diagnostic target",
        })

    return sources, diagnostics


def _iter_source_conversations(source: Dict[str, Any], *, streaming: bool) -> Iterable[Dict[str, Any]]:
    if source["kind"] == "zip_member":
        with zipfile.ZipFile(source["path"], "r") as archive:
            with archive.open(source["member"]) as handle:
                text_handle = io.TextIOWrapper(handle, encoding="utf-8")
                if streaming:
                    yield from stream_json_array_from_file(text_handle)
                else:
                    data = json.load(text_handle)
                    if isinstance(data, list):
                        yield from data
        return

    path = source["path"]
    if streaming:
        yield from stream_json_array(path)
    else:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, list):
            yield from data


def _source_label(source: Dict[str, Any]) -> str:
    if source["kind"] == "zip_member":
        return f"{source['path']}::{source['member']}"
    return source["path"]


def _write_trace(path: str, trace: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(trace, handle, indent=2, sort_keys=True)


def _safe_conversation_order_by(order_by: str | None) -> str | None:
    if not order_by:
        return None
    allowed_columns = {
        "id",
        "run_id",
        "title",
        "created_at",
        "updated_at",
        "earliest_message_at",
        "latest_message_at",
        "default_model",
        "current_node_id",
        "message_count",
        "message_count_main_path",
        "user_message_count",
        "assistant_message_count",
        "system_message_count",
        "tool_message_count",
        "safe_url_count",
        "blocked_url_count",
    }
    parts = order_by.split()
    if len(parts) not in {1, 2}:
        return None
    column = parts[0]
    if column not in allowed_columns:
        return None
    direction = "DESC"
    if len(parts) == 2:
        direction = parts[1].upper()
        if direction not in {"ASC", "DESC"}:
            return None
    return f"{column} {direction}"


def run_canonical_ingest(args, logger: logging.Logger):
    input_paths = args.inputs
    streaming = getattr(args, "streaming", True)
    run_id = args.run_id or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    trace_path = getattr(args, "trace_run", None)
    sources, diagnostics = _discover_input_sources(input_paths, include_diagnostics=bool(trace_path))
    trace: Dict[str, Any] = {
        "run_id": run_id,
        "db": args.db,
        "streaming": streaming,
        "original_inputs": input_paths,
        "discovered_sources": sources,
        "diagnostics": diagnostics,
        "source_results": [],
        "started_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    if not sources:
        logger.error("No canonical conversation JSON sources discovered.")
        trace["failed"] = True
        trace["finished_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        if trace_path:
            _write_trace(trace_path, trace)
        return {
            "run_id": run_id,
            "stats": {},
            "elapsed_sec": 0.0,
            "skipped": False,
            "failed": True,
            "diagnostics": diagnostics,
            "trace_path": trace_path,
        }

    mgr = CanonicalManager(db_path=args.db, mode=args.mode)
    mgr.auto_commit = False
    try:
        if not mgr.begin_run(run_id, input_paths):
            trace["skipped"] = True
            trace["finished_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            if trace_path:
                _write_trace(trace_path, trace)
            return {"run_id": run_id, "stats": dict(mgr.stats), "skipped": True}

        start_time = time.time()
        source_errors = 0
        conversation_errors = 0

        for source in sources:
            label = _source_label(source)
            source_result = {"source": source, "label": label, "conversations_seen": 0, "conversation_errors": 0}
            try:
                logger.info(f"Reading {label}...")
                for conv in _iter_source_conversations(source, streaming=streaming):
                    source_result["conversations_seen"] += 1
                    try:
                        mgr.ingest_conversation(conv, label, run_id=run_id)
                    except Exception:
                        source_result["conversation_errors"] += 1
                        conversation_errors += 1
                        logger.exception(f"Error processing conversation in {label}")
                if source_result["conversation_errors"]:
                    source_errors += 1
                    source_result["status"] = "failed"
                    source_result["error"] = "failed_to_process_conversation"
                else:
                    source_result["status"] = "ingested"
            except Exception:
                source_errors += 1
                source_result["status"] = "failed"
                source_result["error"] = "failed_to_read_source"
                logger.exception(f"Failed to read source {label}")
            trace["source_results"].append(source_result)

        failed = source_errors > 0 or conversation_errors > 0
        if failed:
            mgr.conn.rollback()
        else:
            mgr.finalize_run()
            mgr.conn.commit()
        elapsed = time.time() - start_time
        stats = {} if failed else dict(mgr.stats)
        trace["stats"] = stats
        trace["elapsed_sec"] = elapsed
        trace["source_errors"] = source_errors
        trace["conversation_errors"] = conversation_errors
        trace["partial"] = failed and any(row.get("conversations_seen", 0) > 0 for row in trace["source_results"])
        trace["finished_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        if trace_path:
            _write_trace(trace_path, trace)
        if failed:
            logger.error(
                "Canonical ingest rolled back: %s source errors and %s conversation errors.",
                source_errors,
                conversation_errors,
            )
        else:
            logger.info(
                f"Canonical ingest complete: {stats.get('conversations', 0)} conversations, "
                f"{stats.get('messages', 0)} messages, {stats.get('links', 0)} links in {elapsed:.1f}s"
            )
        return {
            "run_id": run_id,
            "stats": stats,
            "elapsed_sec": elapsed,
            "skipped": False,
            "failed": failed,
            "partial": trace["partial"],
            "source_errors": source_errors,
            "conversation_errors": conversation_errors,
            "source_results": trace["source_results"],
            "diagnostics": diagnostics,
            "trace_path": trace_path,
        }
    finally:
        mgr.close()


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
        order_by = _safe_conversation_order_by(args.order_by)
        if args.order_by and not order_by:
            logger.error("Invalid --order-by value")
            conn.close()
            return
        order_by = order_by or "COALESCE(updated_at, latest_message_at, created_at) DESC"
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
