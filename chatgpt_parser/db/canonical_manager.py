"""
CanonicalManager: ingest ChatGPT exports into a canonical archive DB.

The canonical archive keeps the ChatGPT-native relational shape AtlasBench
expects, but canonicalizes conversations/messages across successive runs.
Run provenance is preserved in dedicated tables instead of primary keys.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import time
import zipfile
from collections import Counter, defaultdict, deque
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .canonical_schema import CANONICAL_SCHEMA_VERSION, CANONICAL_TABLES_SQL
from ..core.parser import determine_message_kind
from ..utils.date import iso_from_timestamp
from ..utils.text import extract_urls_from_text, parse_url


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _json(value: Any) -> Optional[str]:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _stable_id(*parts: object) -> str:
    payload = "||".join("" if part is None else str(part) for part in parts)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _source_fingerprint(value: Dict[str, Any]) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def _clean_text(value: Optional[str], max_chars: int = 400) -> Optional[str]:
    if not value:
        return None
    collapsed = " ".join(value.split()).strip()
    if not collapsed:
        return None
    if len(collapsed) <= max_chars:
        return collapsed
    clipped = collapsed[: max_chars - 1].rsplit(" ", 1)[0].strip()
    return (clipped or collapsed[: max_chars - 1]) + "…"


def _extract_message_text(message: Dict[str, Any]) -> Optional[str]:
    content = _dict(message.get("content"))
    if not content:
        return None
    content_type = content.get("content_type")
    if content_type == "text":
        return "\n\n".join(str(part) for part in content.get("parts") or [])
    if content_type == "multimodal_text":
        parts = []
        for part in _list(content.get("parts")):
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict) and isinstance(part.get("text"), str):
                parts.append(part["text"])
        return "\n\n".join(parts) if parts else None
    if content_type in {"code", "execution_output", "reasoning_recap", "thoughts", "model_thoughts"}:
        return content.get("text") or content.get("content")
    return None


def _extract_keywords(texts: Iterable[Optional[str]], limit: int = 6) -> str:
    stopwords = {
        "a", "an", "and", "are", "as", "at", "be", "been", "but", "by", "can",
        "could", "did", "do", "does", "for", "from", "had", "has", "have", "how",
        "i", "if", "in", "into", "is", "it", "its", "just", "me", "more", "my",
        "of", "on", "or", "our", "please", "so", "some", "that", "the", "their",
        "them", "then", "there", "these", "they", "this", "to", "up", "us", "use",
        "using", "was", "we", "what", "when", "where", "which", "who", "why",
        "with", "would", "you", "your",
    }
    counts: Counter[str] = Counter()
    for text in texts:
        if not text:
            continue
        for token in __import__("re").findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", text.lower()):
            if token in stopwords:
                continue
            counts[token] += 1
    return ", ".join(token for token, _ in counts.most_common(limit))


def _build_summary(
    title: Optional[str],
    first_user_text: Optional[str],
    last_user_text: Optional[str],
    last_assistant_text: Optional[str],
    keyword_text: str,
) -> str:
    sentences: List[str] = []
    if title:
        sentences.append(f"Conversation about {_clean_text(title, max_chars=120)}.")
    elif keyword_text:
        sentences.append(f"Conversation focused on {', '.join(keyword_text.split(', ')[:3])}.")
    else:
        sentences.append("General conversation.")

    first_user = _clean_text(first_user_text, max_chars=180)
    if first_user:
        sentences.append(f"It starts with the user asking about {first_user}.")

    latest_assistant = _clean_text(last_assistant_text, max_chars=180)
    latest_user = _clean_text(last_user_text, max_chars=180)
    if latest_assistant:
        sentences.append(f"The latest assistant response covers {latest_assistant}.")
    elif latest_user and latest_user != first_user:
        sentences.append(f"Later the user returns to {latest_user}.")

    if keyword_text:
        sentences.append(f"Keywords: {', '.join(keyword_text.split(', ')[:5])}.")

    return " ".join(sentences[:4])


def _graph(mapping: Dict[str, Dict[str, Any]]) -> Tuple[Dict[str, Optional[str]], Dict[str, List[str]], Dict[str, int]]:
    parents: Dict[str, Optional[str]] = {}
    children: Dict[str, List[str]] = defaultdict(list)
    for node_id, node in mapping.items():
        if not isinstance(node, dict):
            continue
        parent_id = node.get("parent")
        parents[node_id] = parent_id
        for child_id in node.get("children") or []:
            children[node_id].append(child_id)

    roots = [node_id for node_id, parent_id in parents.items() if parent_id is None]
    depth: Dict[str, int] = {}
    queue = deque(roots)
    for node_id in roots:
        depth[node_id] = 0

    while queue:
        node_id = queue.popleft()
        for child_id in children.get(node_id, []):
            if child_id not in depth:
                depth[child_id] = depth[node_id] + 1
                queue.append(child_id)

    return parents, children, depth


def _main_path_index(mapping: Dict[str, Dict[str, Any]], parents: Dict[str, Optional[str]], current_node_id: Optional[str]) -> Dict[str, int]:
    if not current_node_id or current_node_id not in mapping:
        return {}
    path: List[str] = []
    cursor = current_node_id
    while cursor and cursor in mapping:
        path.append(cursor)
        cursor = parents.get(cursor)
    path.reverse()
    return {node_id: index for index, node_id in enumerate(path)}


class CanonicalManager:
    def __init__(self, db_path: str, mode: str = "skip_existing"):
        self.db_path = db_path
        self.mode = mode
        self.conn = sqlite3.connect(db_path)
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.text_factory = str
        self.auto_commit = True
        try:
            self._init_schema()
        except Exception:
            self.conn.close()
            raise
        self.logger = logging.getLogger(__name__)
        self.stats = defaultdict(int)
        self._active_run_id: Optional[str] = None

    def _init_schema(self) -> None:
        has_meta = self.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'meta'"
        ).fetchone()
        if has_meta:
            row = self.conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
            if row:
                try:
                    existing_version = int(row[0])
                except (TypeError, ValueError) as error:
                    raise RuntimeError("Canonical archive has an invalid schema_version.") from error
                if existing_version != CANONICAL_SCHEMA_VERSION:
                    raise RuntimeError(
                        f"Unsupported canonical schema version {existing_version}; "
                        f"this parser supports version {CANONICAL_SCHEMA_VERSION}."
                    )
        cur = self.conn.cursor()
        for stmt in CANONICAL_TABLES_SQL:
            cur.execute(stmt)
        cur.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES ('schema_version', ?)",
            (str(CANONICAL_SCHEMA_VERSION),),
        )
        cur.execute(
            "INSERT OR IGNORE INTO meta(key, value) VALUES ('created_at', ?)",
            (_iso_now(),),
        )
        if self.auto_commit:
            self.conn.commit()

    def check_run_exists(self, run_id: str) -> bool:
        row = self.conn.execute("SELECT 1 FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        return row is not None

    def begin_run(self, run_id: str, input_files: List[str]) -> bool:
        if self.mode == "skip_existing" and self.check_run_exists(run_id):
            self.logger.info("Run %s already exists in canonical archive. Skipping.", run_id)
            return False
        self.stats.clear()
        self._active_run_id = run_id
        self.conn.execute(
            """
            INSERT OR REPLACE INTO runs (run_id, started_at, finished_at, input_files, stats)
            VALUES (?, ?, NULL, ?, ?)
            """,
            (run_id, _iso_now(), _json(input_files), _json({})),
        )
        if self.auto_commit:
            self.conn.commit()
        return True

    def finalize_run(self) -> None:
        if not self._active_run_id:
            return
        stats = {
            "conversations": self.stats.get("conversations", 0),
            "messages": self.stats.get("messages", 0),
            "links": self.stats.get("links", 0),
            "attachments": self.stats.get("attachments", 0),
            "tool_calls": self.stats.get("tool_calls", 0),
            "tool_results": self.stats.get("tool_results", 0),
        }
        self.conn.execute(
            """
            UPDATE runs
            SET finished_at = ?, stats = ?
            WHERE run_id = ?
            """,
            (_iso_now(), _json(stats), self._active_run_id),
        )
        if self.auto_commit:
            self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def ingest_conversation(self, conv: Dict[str, Any], source_file: str, run_id: Optional[str] = None) -> None:
        active_run_id = run_id or self._active_run_id
        if not active_run_id:
            raise RuntimeError("begin_run() must be called before ingesting conversations.")

        conv_id = conv.get("id") or conv.get("conversation_id")
        if not conv_id:
            self.logger.warning("Skipping conversation without an ID")
            return

        mapping = conv.get("mapping") or {}
        if not isinstance(mapping, dict):
            mapping = {}
        source_fingerprint = _source_fingerprint(conv)

        parents, children, depth = _graph(mapping)
        main_path = _main_path_index(mapping, parents, conv.get("current_node"))
        main_path_ids = set(main_path)
        all_messages, models_used = self._collect_message_rows(
            conv_id=conv_id,
            mapping=mapping,
            main_path_ids=main_path_ids,
            main_path=main_path,
            depth=depth,
            active_run_id=active_run_id,
        )
        conversation_row = self._build_conversation_row(
            conv=conv,
            conv_id=conv_id,
            source_file=source_file,
            active_run_id=active_run_id,
            all_messages=all_messages,
            main_path_ids=main_path_ids,
            models_used=models_used,
            source_fingerprint=source_fingerprint,
        )

        if self._matches_existing_source_fingerprint(conv_id, source_fingerprint):
            self._upsert_conversation_run(active_run_id, conversation_row, canonical_snapshot=False)
            self._record_message_runs(
                conv_id=conv_id,
                active_run_id=active_run_id,
                message_ids=[row["id"] for row in all_messages],
            )
            self._ingest_links(conv, conv_id, active_run_id, all_messages, persist=False)
            self._ingest_attachments(conv_id, active_run_id, mapping, persist=False)
            self._ingest_tool_rows(conv_id, active_run_id, mapping, persist=False)
            self.stats["conversations"] += 1
            self.stats["messages"] += len(all_messages)
            if self.auto_commit:
                self.conn.commit()
            return

        canonical_snapshot = self._should_replace_conversation_snapshot(conv_id, conversation_row)
        if canonical_snapshot or not self._conversation_exists(conv_id):
            self._upsert_conversation(conversation_row)
        self._upsert_conversation_run(active_run_id, conversation_row, canonical_snapshot)
        self._upsert_nodes(
            conv_id=conv_id,
            mapping=mapping,
            parents=parents,
            children=children,
            depth=depth,
            main_path=main_path,
            main_path_ids=main_path_ids,
            active_run_id=active_run_id,
            canonical_snapshot=canonical_snapshot,
        )
        self._upsert_node_children(
            conv_id=conv_id,
            children=children,
            active_run_id=active_run_id,
            canonical_snapshot=canonical_snapshot,
        )
        self._upsert_messages(
            conv_id=conv_id,
            active_run_id=active_run_id,
            all_messages=all_messages,
            canonical_snapshot=canonical_snapshot,
        )

        self._ingest_links(conv, conv_id, active_run_id, all_messages)
        self._ingest_attachments(conv_id, active_run_id, mapping)
        self._ingest_tool_rows(conv_id, active_run_id, mapping)

        self.stats["conversations"] += 1
        self.stats["messages"] += len(all_messages)
        if self.auto_commit:
            self.conn.commit()

    def _collect_message_rows(
        self,
        *,
        conv_id: str,
        mapping: Dict[str, Dict[str, Any]],
        main_path_ids: set[str],
        main_path: Dict[str, int],
        depth: Dict[str, int],
        active_run_id: str,
    ) -> Tuple[List[Dict[str, Any]], set[str]]:
        all_messages: List[Dict[str, Any]] = []
        models_used: set[str] = set()

        for node_id, node in mapping.items():
            if node is None:
                continue
            message = node.get("message")
            if not isinstance(message, dict):
                continue
            author = _dict(message.get("author"))
            role = author.get("role")
            content = _dict(message.get("content"))
            content_type = content.get("content_type")
            recipient = message.get("recipient")
            metadata = _dict(message.get("metadata"))
            if metadata.get("model_slug"):
                models_used.add(metadata["model_slug"])
            if metadata.get("default_model_slug"):
                models_used.add(metadata["default_model_slug"])

            row = {
                "conversation_id": conv_id,
                "id": message.get("id"),
                "run_id": active_run_id,
                "node_id": node_id,
                "role": role,
                "author_name": author.get("name"),
                "recipient": recipient,
                "channel": message.get("channel"),
                "content_type": content_type,
                "text": _extract_message_text(message),
                "raw_content": _json(content),
                "created_at": iso_from_timestamp(message.get("create_time")),
                "updated_at": iso_from_timestamp(message.get("update_time")),
                "is_hidden": 1 if metadata.get("is_visually_hidden_from_conversation") else 0,
                "hidden_reason": "visually_hidden" if metadata.get("is_visually_hidden_from_conversation") else None,
                "is_in_main_path": 1 if node_id in main_path_ids else 0,
                "main_path_index": main_path.get(node_id),
                "depth": depth.get(node_id),
                "model": metadata.get("model_slug") or metadata.get("default_model_slug"),
                "metadata": _json(metadata),
                "time_index": None,
                "message_kind": determine_message_kind(
                    role or "",
                    content_type or "",
                    recipient or "",
                    content if isinstance(content, dict) else {},
                ),
            }
            if row["id"]:
                all_messages.append(row)

        all_messages.sort(key=lambda item: ((item["created_at"] or ""), item["node_id"] or "", item["id"] or ""))
        for index, row in enumerate(all_messages):
            row["time_index"] = index

        return all_messages, models_used

    def _build_conversation_row(
        self,
        *,
        conv: Dict[str, Any],
        conv_id: str,
        source_file: str,
        active_run_id: str,
        all_messages: List[Dict[str, Any]],
        main_path_ids: set[str],
        models_used: set[str],
        source_fingerprint: str,
    ) -> Dict[str, Any]:
        ordered_messages = [row for row in all_messages if row["node_id"] in main_path_ids] or list(all_messages)
        role_counts: Counter[str] = Counter()
        for row in ordered_messages:
            role_counts[row.get("role") or "unknown"] += 1

        first_user = next((row["text"] for row in ordered_messages if row.get("role") == "user" and row.get("text")), None)
        last_user = next((row["text"] for row in reversed(ordered_messages) if row.get("role") == "user" and row.get("text")), None)
        last_assistant = next((row["text"] for row in reversed(ordered_messages) if row.get("role") == "assistant" and row.get("text")), None)
        keyword_text = _extract_keywords(row.get("text") for row in ordered_messages)
        timestamps = [row["created_at"] for row in all_messages if row.get("created_at")]
        safe_urls = _list(conv.get("safe_urls"))
        blocked_urls = _list(conv.get("blocked_urls"))

        return {
            "id": conv_id,
            "run_id": active_run_id,
            "source_id": conv.get("conversation_id") or conv_id,
            "title": conv.get("title"),
            "created_at": iso_from_timestamp(conv.get("create_time")),
            "updated_at": iso_from_timestamp(conv.get("update_time")),
            "earliest_message_at": min(timestamps) if timestamps else None,
            "latest_message_at": max(timestamps) if timestamps else None,
            "default_model": conv.get("default_model_slug"),
            "models_used": _json(sorted(models_used)),
            "is_archived": conv.get("is_archived"),
            "is_starred": conv.get("is_starred"),
            "current_node_id": conv.get("current_node"),
            "message_count": len(all_messages),
            "message_count_main_path": len([row for row in all_messages if row["node_id"] in main_path_ids]),
            "user_message_count": role_counts.get("user", 0),
            "assistant_message_count": role_counts.get("assistant", 0),
            "system_message_count": role_counts.get("system", 0),
            "tool_message_count": role_counts.get("tool", 0),
            "safe_url_count": len(safe_urls),
            "blocked_url_count": len(blocked_urls),
            "keyword_text": keyword_text,
            "summary_text": _build_summary(conv.get("title"), first_user, last_user, last_assistant, keyword_text),
            "metadata": _json(
                {
                    "conversation_origin": conv.get("conversation_origin"),
                    "is_do_not_remember": conv.get("is_do_not_remember"),
                    "source_fingerprint": source_fingerprint,
                }
            ),
            "source_file": source_file,
        }

    def _upsert_nodes(
        self,
        *,
        conv_id: str,
        mapping: Dict[str, Dict[str, Any]],
        parents: Dict[str, Optional[str]],
        children: Dict[str, List[str]],
        depth: Dict[str, int],
        main_path: Dict[str, int],
        main_path_ids: set[str],
        active_run_id: str,
        canonical_snapshot: bool,
    ) -> None:
        for node_id, node in mapping.items():
            if not isinstance(node, dict):
                continue
            message = node.get("message") if isinstance(node.get("message"), dict) else None
            node_row = {
                "conversation_id": conv_id,
                "id": node_id,
                "run_id": active_run_id if canonical_snapshot else self._existing_run_id("nodes", conv_id, node_id),
                "parent_id": parents.get(node_id),
                "children_ids": _json(children.get(node_id, [])),
                "message_id": message.get("id") if message else None,
                "is_root": 1 if parents.get(node_id) is None else 0,
                "is_in_main_path": 1 if node_id in main_path_ids else 0,
                "depth": depth.get(node_id),
                "main_path_index": main_path.get(node_id),
            }
            if canonical_snapshot or not self._row_exists("nodes", conv_id, node_id):
                self._upsert_row(
                    "nodes",
                    [
                        "conversation_id", "id", "run_id", "parent_id", "children_ids",
                        "message_id", "is_root", "is_in_main_path", "depth", "main_path_index",
                    ],
                    node_row,
                )

    def _upsert_node_children(
        self,
        *,
        conv_id: str,
        children: Dict[str, List[str]],
        active_run_id: str,
        canonical_snapshot: bool,
    ) -> None:
        for parent_node_id, child_list in children.items():
            for child_index, child_node_id in enumerate(child_list):
                edge_row = {
                    "conversation_id": conv_id,
                    "parent_node_id": parent_node_id,
                    "child_node_id": child_node_id,
                    "child_index": child_index,
                    "run_id": active_run_id if canonical_snapshot else self._existing_edge_run_id(conv_id, parent_node_id, child_index),
                }
                if canonical_snapshot or not self._edge_exists(conv_id, parent_node_id, child_index):
                    self._upsert_row(
                        "node_children",
                        ["conversation_id", "parent_node_id", "child_node_id", "child_index", "run_id"],
                        edge_row,
                    )

    def _upsert_messages(
        self,
        *,
        conv_id: str,
        active_run_id: str,
        all_messages: List[Dict[str, Any]],
        canonical_snapshot: bool,
    ) -> None:
        for message_row in all_messages:
            existing = self._row_exists("messages", conv_id, message_row["id"])
            if canonical_snapshot or not existing:
                self._upsert_row(
                    "messages",
                    [
                        "conversation_id", "id", "run_id", "node_id", "role", "author_name",
                        "recipient", "channel", "content_type", "text", "raw_content", "created_at",
                        "updated_at", "is_hidden", "hidden_reason", "is_in_main_path", "main_path_index",
                        "depth", "model", "metadata", "time_index", "message_kind",
                    ],
                    message_row,
                )
                self._refresh_message_fts(
                    conversation_id=conv_id,
                    message_id=message_row["id"],
                    run_id=message_row["run_id"],
                    role=message_row["role"],
                    text=message_row["text"] or "",
                )
        self._record_message_runs(
            conv_id=conv_id,
            active_run_id=active_run_id,
            message_ids=[row["id"] for row in all_messages],
        )

    def _record_message_runs(
        self,
        *,
        conv_id: str,
        active_run_id: str,
        message_ids: List[str],
    ) -> None:
        imported_at = _iso_now()
        self.conn.executemany(
            """
            INSERT OR REPLACE INTO message_runs (run_id, conversation_id, message_id, imported_at)
            VALUES (?, ?, ?, ?)
            """,
            [
                (active_run_id, conv_id, message_id, imported_at)
                for message_id in message_ids
            ],
        )

    def _matches_existing_source_fingerprint(
        self,
        conversation_id: str,
        source_fingerprint: str,
    ) -> bool:
        row = self.conn.execute(
            "SELECT metadata FROM conversations WHERE id = ?",
            (conversation_id,),
        ).fetchone()
        if row is None or not row[0]:
            return False
        try:
            metadata = json.loads(row[0])
        except (TypeError, ValueError):
            return False
        return _dict(metadata).get("source_fingerprint") == source_fingerprint

    def _existing_run_id(self, table: str, conversation_id: str, entity_id: str) -> Optional[str]:
        row = self.conn.execute(
            f"SELECT run_id FROM {table} WHERE conversation_id = ? AND id = ?",
            (conversation_id, entity_id),
        ).fetchone()
        return row[0] if row else None

    def _conversation_exists(self, conversation_id: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM conversations WHERE id = ?",
            (conversation_id,),
        ).fetchone()
        return row is not None

    def _existing_edge_run_id(self, conversation_id: str, parent_node_id: str, child_index: int) -> Optional[str]:
        row = self.conn.execute(
            """
            SELECT run_id FROM node_children
            WHERE conversation_id = ? AND parent_node_id = ? AND child_index = ?
            """,
            (conversation_id, parent_node_id, child_index),
        ).fetchone()
        return row[0] if row else None

    def _row_exists(self, table: str, conversation_id: str, entity_id: str) -> bool:
        row = self.conn.execute(
            f"SELECT 1 FROM {table} WHERE conversation_id = ? AND id = ?",
            (conversation_id, entity_id),
        ).fetchone()
        return row is not None

    def _edge_exists(self, conversation_id: str, parent_node_id: str, child_index: int) -> bool:
        row = self.conn.execute(
            """
            SELECT 1 FROM node_children
            WHERE conversation_id = ? AND parent_node_id = ? AND child_index = ?
            """,
            (conversation_id, parent_node_id, child_index),
        ).fetchone()
        return row is not None

    def _should_replace_conversation_snapshot(self, conversation_id: str, candidate: Dict[str, Any]) -> bool:
        row = self.conn.execute(
            """
            SELECT updated_at, latest_message_at, message_count
            FROM conversations
            WHERE id = ?
            """,
            (conversation_id,),
        ).fetchone()
        if row is None:
            return True

        existing_updated = row[0] or row[1] or ""
        candidate_updated = candidate.get("updated_at") or candidate.get("latest_message_at") or ""
        existing_count = row[2] or 0
        candidate_count = candidate.get("message_count") or 0

        if candidate_updated and existing_updated:
            if candidate_updated > existing_updated:
                return True
            if candidate_updated < existing_updated:
                return False

        return candidate_count >= existing_count

    def _upsert_conversation(self, row: Dict[str, Any]) -> None:
        self._upsert_row(
            "conversations",
            [
                "id", "run_id", "source_id", "title", "created_at", "updated_at",
                "earliest_message_at", "latest_message_at", "default_model", "models_used",
                "is_archived", "is_starred", "current_node_id", "message_count",
                "message_count_main_path", "user_message_count", "assistant_message_count",
                "system_message_count", "tool_message_count", "safe_url_count",
                "blocked_url_count", "keyword_text", "summary_text", "metadata", "source_file",
            ],
            row,
        )

    def _upsert_conversation_run(self, run_id: str, row: Dict[str, Any], canonical_snapshot: bool) -> None:
        if canonical_snapshot:
            self.conn.execute(
                "UPDATE conversation_runs SET is_canonical_snapshot = 0 WHERE conversation_id = ?",
                (row["id"],),
            )
        self._upsert_row(
            "conversation_runs",
            [
                "run_id", "conversation_id", "title", "created_at", "updated_at",
                "earliest_message_at", "latest_message_at", "default_model", "models_used",
                "is_archived", "is_starred", "current_node_id", "message_count",
                "message_count_main_path", "user_message_count", "assistant_message_count",
                "system_message_count", "tool_message_count", "safe_url_count",
                "blocked_url_count", "keyword_text", "summary_text", "metadata", "source_file",
                "imported_at", "is_canonical_snapshot",
            ],
            {
                "run_id": run_id,
                "conversation_id": row["id"],
                "title": row["title"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "earliest_message_at": row["earliest_message_at"],
                "latest_message_at": row["latest_message_at"],
                "default_model": row["default_model"],
                "models_used": row["models_used"],
                "is_archived": row["is_archived"],
                "is_starred": row["is_starred"],
                "current_node_id": row["current_node_id"],
                "message_count": row["message_count"],
                "message_count_main_path": row["message_count_main_path"],
                "user_message_count": row["user_message_count"],
                "assistant_message_count": row["assistant_message_count"],
                "system_message_count": row["system_message_count"],
                "tool_message_count": row["tool_message_count"],
                "safe_url_count": row["safe_url_count"],
                "blocked_url_count": row["blocked_url_count"],
                "keyword_text": row["keyword_text"],
                "summary_text": row["summary_text"],
                "metadata": row["metadata"],
                "source_file": row["source_file"],
                "imported_at": _iso_now(),
                "is_canonical_snapshot": 1 if canonical_snapshot else 0,
            },
        )

    def _upsert_row(self, table: str, columns: List[str], row: Dict[str, Any]) -> None:
        placeholders = ", ".join(["?"] * len(columns))
        column_list = ", ".join(columns)
        values = [row.get(column) for column in columns]
        conflict_targets = {
            "conversations": ["id"],
            "conversation_runs": ["run_id", "conversation_id"],
            "nodes": ["conversation_id", "id"],
            "node_children": ["conversation_id", "parent_node_id", "child_index"],
            "messages": ["conversation_id", "id"],
            "message_runs": ["run_id", "conversation_id", "message_id"],
            "links": ["conversation_id", "id"],
            "attachments": ["conversation_id", "id"],
            "tool_calls": ["conversation_id", "id"],
            "tool_results": ["conversation_id", "id"],
        }
        conflict_target = ", ".join(conflict_targets[table])
        update_columns = [column for column in columns if column not in conflict_targets[table]]
        update_clause = ", ".join(f"{column}=excluded.{column}" for column in update_columns)
        self.conn.execute(
            f"""
            INSERT INTO {table} ({column_list}) VALUES ({placeholders})
            ON CONFLICT({conflict_target}) DO UPDATE SET {update_clause}
            """,
            values,
        )

    def _refresh_message_fts(self, *, conversation_id: str, message_id: str, run_id: Optional[str], role: Optional[str], text: str) -> None:
        self.conn.execute(
            "DELETE FROM message_fts WHERE conversation_id = ? AND message_id = ?",
            (conversation_id, message_id),
        )
        if text:
            self.conn.execute(
                """
                INSERT INTO message_fts (message_id, conversation_id, run_id, role, text)
                VALUES (?, ?, ?, ?, ?)
                """,
                (message_id, conversation_id, run_id, role, text),
            )

    def _ingest_links(
        self,
        conv: Dict[str, Any],
        conversation_id: str,
        run_id: str,
        messages: List[Dict[str, Any]],
        *,
        persist: bool = True,
    ) -> None:
        safe_urls = _list(conv.get("safe_urls"))
        for index, url in enumerate(safe_urls):
            scheme, domain, path, query = parse_url(url)
            row = {
                "conversation_id": conversation_id,
                "id": f"safe_{conversation_id}_{index}",
                "run_id": run_id,
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
                "metadata": _json({}),
            }
            if persist:
                self._upsert_row(
                    "links",
                    [
                        "conversation_id", "id", "run_id", "message_id", "source", "url",
                        "display_text", "position_start", "position_end", "scheme", "domain",
                        "path", "query", "kind", "metadata",
                    ],
                    row,
                )
            self.stats["links"] += 1

        for message in messages:
            for index, (url, start, end) in enumerate(extract_urls_from_text(message.get("text") or "")):
                scheme, domain, path, query = parse_url(url)
                row = {
                    "conversation_id": conversation_id,
                    "id": f"msg_{message['id']}_{index}",
                    "run_id": message["run_id"],
                    "message_id": message["id"],
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
                    "metadata": _json({}),
                }
                if persist:
                    self._upsert_row(
                        "links",
                        [
                            "conversation_id", "id", "run_id", "message_id", "source", "url",
                            "display_text", "position_start", "position_end", "scheme", "domain",
                            "path", "query", "kind", "metadata",
                        ],
                        row,
                    )
                self.stats["links"] += 1

            metadata = _dict(json.loads(message.get("metadata") or "{}"))
            references = [
                ("content_reference", reference)
                for reference in _list(metadata.get("content_references"))
            ] + [
                ("citation", reference)
                for reference in _list(metadata.get("citations"))
            ]
            for index, (source, reference) in enumerate(references):
                reference = _dict(reference)
                nested = _dict(reference.get("metadata"))
                url = reference.get("url") or nested.get("url")
                if not isinstance(url, str) or not url.strip():
                    continue
                url = url.strip()
                scheme, domain, path, query = parse_url(url)
                row = {
                    "conversation_id": conversation_id,
                    "id": _stable_id(conversation_id, message["id"], source, index, url),
                    "run_id": message["run_id"],
                    "message_id": message["id"],
                    "source": source,
                    "url": url,
                    "display_text": reference.get("title") or nested.get("title") or reference.get("text") or url,
                    "position_start": reference.get("start_idx", reference.get("start_ix")),
                    "position_end": reference.get("end_idx", reference.get("end_ix")),
                    "scheme": scheme,
                    "domain": domain,
                    "path": path,
                    "query": query,
                    "kind": reference.get("type") or nested.get("type") or "citation",
                    "metadata": _json(reference),
                }
                if persist:
                    self._upsert_row(
                        "links",
                        [
                            "conversation_id", "id", "run_id", "message_id", "source", "url",
                            "display_text", "position_start", "position_end", "scheme", "domain",
                            "path", "query", "kind", "metadata",
                        ],
                        row,
                    )
                self.stats["links"] += 1

    def _ingest_attachments(
        self,
        conversation_id: str,
        run_id: str,
        mapping: Dict[str, Dict[str, Any]],
        *,
        persist: bool = True,
    ) -> None:
        for node_key, node in mapping.items():
            if not isinstance(node, dict):
                continue
            message = node.get("message")
            if not isinstance(message, dict):
                continue
            content = _dict(message.get("content"))
            metadata = _dict(message.get("metadata"))
            candidates = [part for part in _list(content.get("parts")) if isinstance(part, dict)]
            candidates.extend(_dict(attachment) for attachment in _list(metadata.get("attachments")))
            for index, part in enumerate(candidates):
                content_type = str(part.get("content_type") or part.get("type") or "file")
                source_ref = part.get("asset_pointer") or part.get("source_ref") or part.get("id") or part.get("file_id")
                if not source_ref and not part.get("name") and not part.get("filename"):
                    continue
                attachment_type = "image" if "image" in content_type or str(part.get("mime_type") or "").startswith("image/") else "file"
                attachment_id = _stable_id(conversation_id, message.get("id"), "attachment", index, source_ref, part.get("name"))
                row = {
                    "conversation_id": conversation_id,
                    "id": attachment_id,
                    "run_id": run_id,
                    "message_id": message.get("id"),
                    "type": attachment_type,
                    "filename": part.get("name") or part.get("filename"),
                    "mime_type": part.get("mime_type") or part.get("content_type_mime_type"),
                    "filesize_bytes": part.get("size_bytes") or part.get("size"),
                    "source_ref": source_ref,
                    "metadata": _json(
                        {
                            "width": part.get("width"),
                            "height": part.get("height"),
                            "availability": "unresolved",
                            **_dict(part.get("metadata")),
                        }
                    ),
                }
                if persist:
                    self._upsert_row(
                        "attachments",
                        ["conversation_id", "id", "run_id", "message_id", "type", "filename", "mime_type", "filesize_bytes", "source_ref", "metadata"],
                        row,
                    )
                self.stats["attachments"] += 1

    def _ingest_tool_rows(
        self,
        conversation_id: str,
        run_id: str,
        mapping: Dict[str, Dict[str, Any]],
        *,
        persist: bool = True,
    ) -> None:
        call_id_by_node: Dict[str, str] = {}
        for node_key, node in mapping.items():
            if not isinstance(node, dict):
                continue
            message = node.get("message")
            if not isinstance(message, dict):
                continue
            author = _dict(message.get("author"))
            role = author.get("role")
            content = _dict(message.get("content"))
            content_type = content.get("content_type")
            recipient = message.get("recipient")
            message_kind = determine_message_kind(role or "", content_type or "", recipient or "", content if isinstance(content, dict) else {})
            message_id = message.get("id")

            if message_kind == "tool_call":
                raw_args = content.get("text")
                try:
                    arguments_json = json.loads(raw_args) if raw_args else None
                except Exception:
                    arguments_json = None
                tool_call_id = _stable_id(conversation_id, message_id, "tool_call", recipient, raw_args)
                call_id_by_node[str(node.get("id") or node_key)] = tool_call_id
                row = {
                    "conversation_id": conversation_id,
                    "id": tool_call_id,
                    "run_id": run_id,
                    "message_id": message_id,
                    "tool_name": recipient,
                    "call_index": 0,
                    "arguments_json": _json(arguments_json),
                    "raw_arguments": raw_args,
                    "metadata": _json(_dict(message.get("metadata"))),
                }
                if persist:
                    self._upsert_row(
                        "tool_calls",
                        ["conversation_id", "id", "run_id", "message_id", "tool_name", "call_index", "arguments_json", "raw_arguments", "metadata"],
                        row,
                    )
                self.stats["tool_calls"] += 1

        for node_key, node in mapping.items():
            if not isinstance(node, dict):
                continue
            message = node.get("message")
            if not isinstance(message, dict):
                continue
            author = _dict(message.get("author"))
            content = _dict(message.get("content"))
            message_kind = determine_message_kind(
                author.get("role") or "",
                content.get("content_type") or "",
                message.get("recipient") or "",
                content,
            )
            if message_kind == "tool_result":
                message_id = message.get("id")
                raw_result_value = content.get("text") if content.get("content_type") == "execution_output" else content
                raw_result = raw_result_value if isinstance(raw_result_value, str) else _json(raw_result_value)
                parsed_result = None
                if isinstance(raw_result, str):
                    try:
                        parsed_result = json.loads(raw_result)
                    except (TypeError, ValueError):
                        parsed_result = None
                parent_id = node.get("parent")
                tool_call_id = None
                visited = set()
                while parent_id and parent_id not in visited:
                    visited.add(parent_id)
                    if parent_id in call_id_by_node:
                        tool_call_id = call_id_by_node[parent_id]
                        break
                    parent_node = mapping.get(parent_id)
                    parent_id = parent_node.get("parent") if isinstance(parent_node, dict) else None
                tool_result_id = _stable_id(conversation_id, message_id, "tool_result", raw_result)
                row = {
                    "conversation_id": conversation_id,
                    "id": tool_result_id,
                    "run_id": run_id,
                    "message_id": message_id,
                    "tool_call_id": tool_call_id,
                    "result_json": _json(parsed_result),
                    "raw_result": raw_result,
                    "metadata": _json(_dict(message.get("metadata"))),
                }
                if persist:
                    self._upsert_row(
                        "tool_results",
                        ["conversation_id", "id", "run_id", "message_id", "tool_call_id", "result_json", "raw_result", "metadata"],
                        row,
                    )
                self.stats["tool_results"] += 1
