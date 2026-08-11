import copy
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from chatgpt_parser.db.canonical_manager import CanonicalManager
from chatgpt_parser.db.canonical_schema import CANONICAL_TABLES_SQL


def _make_single_turn(conv_id="conv1", title="Test Conv", ts=1700000000.0):
    node_id = f"node_{conv_id}"
    return {
        "id": conv_id,
        "title": title,
        "create_time": ts,
        "update_time": ts + 100,
        "default_model_slug": "gpt-4o",
        "current_node": node_id,
        "mapping": {
            node_id: {
                "id": node_id,
                "parent": None,
                "children": [],
                "message": {
                    "id": f"msg_{conv_id}",
                    "author": {"role": "user"},
                    "content": {"content_type": "text", "parts": ["Hello world"]},
                    "create_time": ts,
                    "metadata": {},
                },
            }
        },
    }


def _make_extended(conv_id="conv1"):
    root = f"node_{conv_id}_root"
    assistant = f"node_{conv_id}_assistant"
    followup = f"node_{conv_id}_followup"
    return {
        "id": conv_id,
        "title": "Extended Conversation",
        "create_time": 1000.0,
        "update_time": 1300.0,
        "default_model_slug": "gpt-4o",
        "current_node": followup,
        "mapping": {
            root: {
                "id": root,
                "parent": None,
                "children": [assistant],
                "message": {
                    "id": f"msg_{conv_id}",
                    "author": {"role": "user"},
                    "content": {"content_type": "text", "parts": ["Start thread"]},
                    "create_time": 1000.0,
                    "metadata": {},
                },
            },
            assistant: {
                "id": assistant,
                "parent": root,
                "children": [followup],
                "message": {
                    "id": f"msg_{conv_id}_2",
                    "author": {"role": "assistant"},
                    "content": {"content_type": "text", "parts": ["Intermediate answer"]},
                    "create_time": 1200.0,
                    "metadata": {"model_slug": "gpt-4o"},
                },
            },
            followup: {
                "id": followup,
                "parent": assistant,
                "children": [],
                "message": {
                    "id": f"msg_{conv_id}_3",
                    "author": {"role": "user"},
                    "content": {"content_type": "text", "parts": ["Continue thread"]},
                    "create_time": 1250.0,
                    "metadata": {},
                },
            },
        },
    }


def _make_branch(conv_id="branch_conv"):
    root = f"node_{conv_id}_root"
    main = f"node_{conv_id}_main"
    branch = f"node_{conv_id}_branch"
    return {
        "id": conv_id,
        "title": "Branching conv",
        "create_time": 1.0,
        "update_time": 3.0,
        "current_node": main,
        "mapping": {
            root: {
                "id": root,
                "parent": None,
                "children": [main, branch],
                "message": {
                    "id": f"msg_{conv_id}_root",
                    "author": {"role": "user"},
                    "content": {"content_type": "text", "parts": ["hello root"]},
                    "create_time": 1.0,
                    "metadata": {},
                },
            },
            main: {
                "id": main,
                "parent": root,
                "children": [],
                "message": {
                    "id": f"msg_{conv_id}_main",
                    "author": {"role": "assistant"},
                    "content": {"content_type": "text", "parts": ["main path response"]},
                    "create_time": 2.0,
                    "metadata": {"model_slug": "gpt-4o"},
                },
            },
            branch: {
                "id": branch,
                "parent": root,
                "children": [],
                "message": {
                    "id": f"msg_{conv_id}_branch",
                    "author": {"role": "assistant"},
                    "content": {"content_type": "text", "parts": ["branch response"]},
                    "create_time": 3.0,
                    "metadata": {"model_slug": "gpt-4o-mini"},
                },
            },
        },
    }


def _make_rich_conv(conv_id="rich_conv"):
    user_node = f"node_{conv_id}_user"
    tool_call_node = f"node_{conv_id}_tool_call"
    tool_result_node = f"node_{conv_id}_tool_result"
    image_node = f"node_{conv_id}_image"
    return {
        "id": conv_id,
        "title": "Rich Conversation",
        "create_time": 10.0,
        "update_time": 40.0,
        "default_model_slug": "gpt-4o",
        "current_node": image_node,
        "safe_urls": ["https://chat.openai.com/c/example"],
        "blocked_urls": ["https://example.invalid/blocked"],
        "mapping": {
            user_node: {
                "id": user_node,
                "parent": None,
                "children": [tool_call_node],
                "message": {
                    "id": f"msg_{conv_id}_user",
                    "author": {"role": "user"},
                    "content": {"content_type": "text", "parts": ["See https://example.com/docs"]},
                    "create_time": 10.0,
                    "update_time": 10.0,
                    "metadata": {},
                },
            },
            tool_call_node: {
                "id": tool_call_node,
                "parent": user_node,
                "children": [tool_result_node],
                "message": {
                    "id": f"msg_{conv_id}_tool_call",
                    "author": {"role": "assistant"},
                    "recipient": "python",
                    "content": {"content_type": "code", "text": "{\"city\": \"Austin\"}"},
                    "create_time": 20.0,
                    "update_time": 20.0,
                    "metadata": {"model_slug": "gpt-4o"},
                },
            },
            tool_result_node: {
                "id": tool_result_node,
                "parent": tool_call_node,
                "children": [image_node],
                "message": {
                    "id": f"msg_{conv_id}_tool_result",
                    "author": {"role": "tool"},
                    "content": {"content_type": "execution_output", "text": "72 and sunny"},
                    "create_time": 30.0,
                    "update_time": 30.0,
                    "metadata": {},
                },
            },
            image_node: {
                "id": image_node,
                "parent": tool_result_node,
                "children": [],
                "message": {
                    "id": f"msg_{conv_id}_image",
                    "author": {"role": "assistant"},
                    "content": {
                        "content_type": "multimodal_text",
                        "parts": [
                            "Here is the image",
                            {
                                "content_type": "image_asset_pointer",
                                "asset_pointer": "file-service://asset-123",
                                "size_bytes": 2048,
                                "width": 512,
                                "height": 512,
                                "metadata": {"variant": "thumbnail"},
                            },
                        ],
                    },
                    "create_time": 40.0,
                    "update_time": 40.0,
                    "metadata": {"model_slug": "gpt-4o-mini"},
                },
            },
        },
    }


def _make_rich_content(conv_id="rich_conv"):
    user = f"node_{conv_id}_user"
    answer = f"node_{conv_id}_answer"
    call = f"node_{conv_id}_call"
    result = f"node_{conv_id}_result"
    return {
        "id": conv_id,
        "title": "Rich content",
        "create_time": 1000.0,
        "update_time": 1400.0,
        "current_node": result,
        "mapping": {
            user: {
                "id": user,
                "parent": None,
                "children": [answer],
                "message": {
                    "id": f"msg_{conv_id}_user",
                    "author": {"role": "user"},
                    "content": {
                        "content_type": "multimodal_text",
                        "parts": [
                            "What is in this image and file?",
                            {
                                "content_type": "image_asset_pointer",
                                "asset_pointer": "file-service://missing-image",
                                "size_bytes": 1234,
                                "width": 640,
                                "height": 480,
                            },
                        ],
                    },
                    "create_time": 1000.0,
                    "metadata": {
                        "attachments": [
                            {
                                "id": "file-missing-pdf",
                                "name": "report.pdf",
                                "mime_type": "application/pdf",
                                "size": 4567,
                            }
                        ]
                    },
                },
            },
            answer: {
                "id": answer,
                "parent": user,
                "children": [call],
                "message": {
                    "id": f"msg_{conv_id}_answer",
                    "author": {"role": "assistant"},
                    "content": {"content_type": "text", "parts": ["See https://example.com/direct"]},
                    "create_time": 1100.0,
                    "metadata": {
                        "content_references": [
                            {"type": "webpage", "url": "https://example.com/reference", "title": "Reference"}
                        ],
                        "citations": [
                            {
                                "start_ix": 0,
                                "end_ix": 8,
                                "metadata": {"type": "webpage", "url": "https://example.org/citation", "title": "Citation"},
                            }
                        ],
                    },
                },
            },
            call: {
                "id": call,
                "parent": answer,
                "children": [result],
                "message": {
                    "id": f"msg_{conv_id}_call",
                    "author": {"role": "assistant"},
                    "recipient": "browser.search",
                    "content": {"content_type": "code", "text": "{\"query\": \"atlas\"}"},
                    "create_time": 1200.0,
                    "metadata": {"request_id": "request-1"},
                },
            },
            result: {
                "id": result,
                "parent": call,
                "children": [],
                "message": {
                    "id": f"msg_{conv_id}_result",
                    "author": {"role": "tool", "name": "browser.search"},
                    "content": {"content_type": "execution_output", "text": "{\"ok\": true}"},
                    "create_time": 1300.0,
                    "metadata": ["malformed", "metadata"],
                },
            },
        },
    }


class CanonicalArchiveSchemaTests(unittest.TestCase):
    def test_schema_creates_chatgpt_native_tables(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as handle:
            db_path = handle.name
        try:
            conn = sqlite3.connect(db_path)
            for stmt in CANONICAL_TABLES_SQL:
                conn.execute(stmt)
            conn.commit()
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            expected = {
                "meta", "runs", "conversations", "conversation_runs", "nodes",
                "node_children", "messages", "message_runs", "links",
                "attachments", "tool_calls", "tool_results", "message_fts",
            }
            self.assertTrue(expected.issubset(tables), f"Missing: {expected - tables}")
            conn.close()
        finally:
            os.unlink(db_path)


class CanonicalArchiveIngestTests(unittest.TestCase):
    def _open(self, db_path):
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return closing(conn)

    def _ingest_runs(self, runs):
        handle = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        db_path = handle.name
        handle.close()

        mgr = CanonicalManager(db_path)
        for run_id, conversations in runs:
            started = mgr.begin_run(run_id, [f"{run_id}.json"])
            self.assertTrue(started)
            for conversation in conversations:
                mgr.ingest_conversation(conversation, f"{run_id}.json", run_id=run_id)
            mgr.finalize_run()
        mgr.close()
        return db_path

    def test_single_ingest_populates_atlas_compatible_tables(self):
        db_path = self._ingest_runs([("run_a", [_make_single_turn("conv_a")])])
        try:
            with self._open(db_path) as conn:
                conversation = dict(conn.execute("SELECT * FROM conversations WHERE id = 'conv_a'").fetchone())
                self.assertEqual(conversation["run_id"], "run_a")
                self.assertEqual(conversation["message_count"], 1)
                self.assertEqual(conversation["message_count_main_path"], 1)
                self.assertEqual(conversation["default_model"], "gpt-4o")

                message = dict(conn.execute("SELECT * FROM messages WHERE conversation_id = 'conv_a'").fetchone())
                self.assertEqual(message["id"], "msg_conv_a")
                self.assertEqual(message["role"], "user")

                fts = conn.execute(
                    "SELECT conversation_id FROM message_fts WHERE message_fts MATCH 'hello'"
                ).fetchall()
                self.assertEqual([tuple(row) for row in fts], [("conv_a",)])
        finally:
            os.unlink(db_path)

    def test_successive_runs_dedupe_and_extend_conversation(self):
        run_a = ("run_a", [_make_single_turn("conv1", title="Base Conv", ts=1000.0)])
        run_b = ("run_b", [_make_extended("conv1")])
        db_path = self._ingest_runs([run_a, run_b])
        try:
            with self._open(db_path) as conn:
                conversations = conn.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
                self.assertEqual(conversations, 1)

                conv = dict(conn.execute("SELECT * FROM conversations WHERE id = 'conv1'").fetchone())
                self.assertEqual(conv["run_id"], "run_b")
                self.assertEqual(conv["message_count"], 3)
                self.assertEqual(conv["message_count_main_path"], 3)

                messages = conn.execute(
                    "SELECT id FROM messages WHERE conversation_id = 'conv1' ORDER BY time_index ASC"
                ).fetchall()
                self.assertEqual([row[0] for row in messages], ["msg_conv1", "msg_conv1_2", "msg_conv1_3"])

                run_rows = conn.execute(
                    "SELECT run_id, message_count, is_canonical_snapshot FROM conversation_runs WHERE conversation_id = 'conv1' ORDER BY run_id ASC"
                ).fetchall()
                self.assertEqual([tuple(row) for row in run_rows], [("run_a", 1, 0), ("run_b", 3, 1)])
        finally:
            os.unlink(db_path)

    def test_same_timestamp_and_count_with_changed_content_replaces_snapshot(self):
        original = _make_single_turn("conv_edit", ts=1000.0)
        edited = _make_single_turn("conv_edit", ts=1000.0)
        edited["mapping"]["node_conv_edit"]["message"]["content"]["parts"] = [
            "Edited content"
        ]
        db_path = self._ingest_runs([
            ("run_original", [original]),
            ("run_edited", [edited]),
        ])
        try:
            with self._open(db_path) as conn:
                conversation = conn.execute(
                    "SELECT run_id FROM conversations WHERE id = 'conv_edit'"
                ).fetchone()
                self.assertEqual(conversation[0], "run_edited")
                message = conn.execute(
                    "SELECT run_id, text FROM messages WHERE conversation_id = 'conv_edit'"
                ).fetchone()
                self.assertEqual(tuple(message), ("run_edited", "Edited content"))
                self.assertEqual(
                    conn.execute(
                        "SELECT COUNT(*) FROM message_fts WHERE message_fts MATCH 'edited'"
                    ).fetchone()[0],
                    1,
                )
                self.assertEqual(
                    conn.execute(
                        "SELECT COUNT(*) FROM message_fts WHERE message_fts MATCH 'hello'"
                    ).fetchone()[0],
                    0,
                )
        finally:
            os.unlink(db_path)

    def test_newer_snapshot_prunes_removed_messages_and_resources(self):
        original = _make_rich_conv("conv_prune")
        replacement = copy.deepcopy(original)
        user_node = "node_conv_prune_user"
        tool_call_node = "node_conv_prune_tool_call"
        tool_result_node = "node_conv_prune_tool_result"
        image_node = "node_conv_prune_image"
        replacement["update_time"] = 50.0
        replacement["safe_urls"] = []
        replacement["blocked_urls"] = []
        replacement["mapping"].pop(tool_call_node)
        replacement["mapping"].pop(tool_result_node)
        replacement["mapping"][user_node]["children"] = [image_node]
        replacement["mapping"][image_node]["parent"] = user_node

        db_path = self._ingest_runs([
            ("run_original", [original]),
            ("run_replacement", [replacement]),
        ])
        try:
            with self._open(db_path) as conn:
                self.assertEqual(
                    conn.execute(
                        "SELECT COUNT(*) FROM messages WHERE conversation_id = 'conv_prune'"
                    ).fetchone()[0],
                    2,
                )
                self.assertEqual(
                    conn.execute(
                        "SELECT COUNT(*) FROM nodes WHERE conversation_id = 'conv_prune'"
                    ).fetchone()[0],
                    2,
                )
                self.assertEqual(
                    conn.execute(
                        "SELECT COUNT(*) FROM tool_calls WHERE conversation_id = 'conv_prune'"
                    ).fetchone()[0],
                    0,
                )
                self.assertEqual(
                    conn.execute(
                        "SELECT COUNT(*) FROM tool_results WHERE conversation_id = 'conv_prune'"
                    ).fetchone()[0],
                    0,
                )
                link_sources = {
                    row[0]
                    for row in conn.execute(
                        "SELECT source FROM links WHERE conversation_id = 'conv_prune'"
                    )
                }
                self.assertEqual(link_sources, {"message_text"})
                self.assertEqual(
                    conn.execute(
                        "SELECT COUNT(*) FROM attachments WHERE conversation_id = 'conv_prune'"
                    ).fetchone()[0],
                    1,
                )
                metadata = json.loads(
                    conn.execute(
                        """
                        SELECT metadata FROM conversation_runs
                        WHERE run_id = 'run_replacement' AND conversation_id = 'conv_prune'
                        """
                    ).fetchone()[0]
                )
                self.assertEqual(
                    metadata["removed_message_ids"],
                    ["msg_conv_prune_tool_call", "msg_conv_prune_tool_result"],
                )
        finally:
            os.unlink(db_path)

    def test_conversation_status_metadata_is_preserved(self):
        conversation = _make_single_turn("conv_status")
        conversation["async_status"] = 3
        conversation["is_read_only"] = True
        db_path = self._ingest_runs([("run_status", [conversation])])
        try:
            with self._open(db_path) as conn:
                metadata = json.loads(
                    conn.execute(
                        "SELECT metadata FROM conversations WHERE id = 'conv_status'"
                    ).fetchone()[0]
                )
                self.assertEqual(metadata["async_status"], 3)
                self.assertTrue(metadata["is_read_only"])
        finally:
            os.unlink(db_path)

    def test_partial_conversation_without_mapping_is_preserved(self):
        conversation = {
            "id": "conv_partial",
            "title": "Partial conversation",
            "create_time": 1000.0,
            "update_time": 1001.0,
            "current_node": None,
            "mapping": {},
            "async_status": 3,
        }
        db_path = self._ingest_runs([("run_partial", [conversation])])
        try:
            with self._open(db_path) as conn:
                row = conn.execute(
                    """
                    SELECT message_count, message_count_main_path, current_node_id, metadata
                    FROM conversations WHERE id = 'conv_partial'
                    """
                ).fetchone()
                self.assertEqual(tuple(row[:3]), (0, 0, None))
                self.assertEqual(json.loads(row[3])["async_status"], 3)
                self.assertEqual(
                    conn.execute(
                        "SELECT COUNT(*) FROM nodes WHERE conversation_id = 'conv_partial'"
                    ).fetchone()[0],
                    0,
                )
        finally:
            os.unlink(db_path)

    def test_branch_structure_is_preserved_without_cross_run_dedupe_of_branch_nodes(self):
        db_path = self._ingest_runs([("run_branch", [_make_branch()])])
        try:
            with self._open(db_path) as conn:
                nodes = conn.execute(
                    "SELECT id, is_in_main_path, main_path_index FROM nodes WHERE conversation_id = 'branch_conv' ORDER BY id"
                ).fetchall()
                node_map = {row[0]: (row[1], row[2]) for row in nodes}
                self.assertEqual(node_map["node_branch_conv_root"], (1, 0))
                self.assertEqual(node_map["node_branch_conv_main"], (1, 1))
                self.assertEqual(node_map["node_branch_conv_branch"], (0, None))

                edges = conn.execute(
                    "SELECT parent_node_id, child_node_id, child_index FROM node_children WHERE conversation_id = 'branch_conv' ORDER BY child_index ASC"
                ).fetchall()
                self.assertEqual(
                    [tuple(row) for row in edges],
                    [
                        ("node_branch_conv_root", "node_branch_conv_main", 0),
                        ("node_branch_conv_root", "node_branch_conv_branch", 1),
                    ],
                )
        finally:
            os.unlink(db_path)

    def test_skip_existing_run_id_is_idempotent(self):
        handle = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        db_path = handle.name
        handle.close()
        try:
            mgr = CanonicalManager(db_path, mode="skip_existing")
            self.assertTrue(mgr.begin_run("run_same", ["run_same.json"]))
            mgr.ingest_conversation(_make_single_turn("conv_same"), "run_same.json", run_id="run_same")
            mgr.finalize_run()
            self.assertFalse(mgr.begin_run("run_same", ["run_same.json"]))
            mgr.close()

            with self._open(db_path) as conn:
                runs = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
                self.assertEqual(runs, 1)
        finally:
            os.unlink(db_path)

    def test_older_noncanonical_import_does_not_clear_existing_canonical_snapshot(self):
        run_new = ("run_new", [_make_extended("conv_snapshot")])
        run_old = ("run_old", [_make_single_turn("conv_snapshot", title="Older Snapshot", ts=900.0)])
        db_path = self._ingest_runs([run_new, run_old])
        try:
            with self._open(db_path) as conn:
                run_rows = conn.execute(
                    """
                    SELECT run_id, message_count, is_canonical_snapshot
                    FROM conversation_runs
                    WHERE conversation_id = 'conv_snapshot'
                    ORDER BY run_id ASC
                    """
                ).fetchall()
                self.assertEqual(
                    [tuple(row) for row in run_rows],
                    [("run_new", 3, 1), ("run_old", 1, 0)],
                )

                conv = conn.execute(
                    "SELECT run_id, message_count FROM conversations WHERE id = 'conv_snapshot'"
                ).fetchone()
                self.assertEqual(tuple(conv), ("run_new", 3))
        finally:
            os.unlink(db_path)

    def test_links_attachments_and_tool_rows_are_extracted(self):
        db_path = self._ingest_runs([("run_rich", [_make_rich_conv()])])
        try:
            with self._open(db_path) as conn:
                conversation = conn.execute(
                    """
                    SELECT safe_url_count, blocked_url_count, message_count, message_count_main_path
                    FROM conversations
                    WHERE id = 'rich_conv'
                    """
                ).fetchone()
                self.assertEqual(tuple(conversation), (1, 1, 4, 4))

                links = conn.execute(
                    "SELECT source, url, message_id FROM links WHERE conversation_id = 'rich_conv' ORDER BY source, url"
                ).fetchall()
                self.assertEqual(
                    [tuple(row) for row in links],
                    [
                        ("message_text", "https://example.com/docs", "msg_rich_conv_user"),
                        ("safe_url", "https://chat.openai.com/c/example", None),
                    ],
                )

                attachments = conn.execute(
                    "SELECT message_id, type, filesize_bytes, source_ref FROM attachments WHERE conversation_id = 'rich_conv'"
                ).fetchall()
                self.assertEqual(
                    [tuple(row) for row in attachments],
                    [("msg_rich_conv_image", "image", 2048, "file-service://asset-123")],
                )

                tool_calls = conn.execute(
                    "SELECT message_id, tool_name, raw_arguments, arguments_json FROM tool_calls WHERE conversation_id = 'rich_conv'"
                ).fetchall()
                self.assertEqual(
                    [tuple(row) for row in tool_calls],
                    [("msg_rich_conv_tool_call", "python", "{\"city\": \"Austin\"}", "{\"city\": \"Austin\"}")],
                )

                tool_results = conn.execute(
                    "SELECT message_id, raw_result FROM tool_results WHERE conversation_id = 'rich_conv'"
                ).fetchall()
                self.assertEqual(
                    [tuple(row) for row in tool_results],
                    [("msg_rich_conv_tool_result", "72 and sunny")],
                )
        finally:
            os.unlink(db_path)

    def test_rich_content_populates_existing_schema_and_links_tool_exchange(self):
        db_path = self._ingest_runs([("run_rich", [_make_rich_content()])])
        try:
            with self._open(db_path) as conn:
                links = conn.execute(
                    "SELECT source, url, display_text FROM links WHERE conversation_id = 'rich_conv' ORDER BY source, url"
                ).fetchall()
                self.assertEqual(len(links), 3)
                self.assertEqual({row[0] for row in links}, {"message_text", "content_reference", "citation"})

                attachments = conn.execute(
                    "SELECT type, filename, mime_type, filesize_bytes, source_ref, metadata FROM attachments WHERE conversation_id = 'rich_conv' ORDER BY type"
                ).fetchall()
                self.assertEqual(len(attachments), 2)
                self.assertEqual({row[0] for row in attachments}, {"image", "file"})
                self.assertIn("report.pdf", {row[1] for row in attachments})
                self.assertTrue(all(json.loads(row[5])["availability"] == "unresolved" for row in attachments))

                tool_call = conn.execute(
                    "SELECT id, tool_name, arguments_json FROM tool_calls WHERE conversation_id = 'rich_conv'"
                ).fetchone()
                self.assertEqual(tool_call[1], "browser.search")
                self.assertEqual(json.loads(tool_call[2]), {"query": "atlas"})

                tool_result = conn.execute(
                    "SELECT tool_call_id, result_json, raw_result, metadata FROM tool_results WHERE conversation_id = 'rich_conv'"
                ).fetchone()
                self.assertEqual(tool_result[0], tool_call[0])
                self.assertEqual(json.loads(tool_result[1]), {"ok": True})
                self.assertEqual(json.loads(tool_result[3]), {})
        finally:
            os.unlink(db_path)

    def test_rich_content_is_deduplicated_across_reimport_runs(self):
        db_path = self._ingest_runs([
            ("run_rich_a", [_make_rich_content()]),
            ("run_rich_b", [_make_rich_content()]),
        ])
        try:
            with self._open(db_path) as conn:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM links WHERE conversation_id = 'rich_conv'").fetchone()[0], 3)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM attachments WHERE conversation_id = 'rich_conv'").fetchone()[0], 2)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM tool_calls WHERE conversation_id = 'rich_conv'").fetchone()[0], 1)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM tool_results WHERE conversation_id = 'rich_conv'").fetchone()[0], 1)
        finally:
            os.unlink(db_path)

    def test_identical_reimport_records_provenance_without_rewriting_canonical_content(self):
        handle = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        db_path = handle.name
        handle.close()
        try:
            conversation = _make_rich_content()
            mgr = CanonicalManager(db_path)
            self.assertTrue(mgr.begin_run("run_rich_a", ["run_rich_a.json"]))
            mgr.ingest_conversation(conversation, "run_rich_a.json", run_id="run_rich_a")
            mgr.finalize_run()

            statements = []
            mgr.conn.set_trace_callback(statements.append)
            self.assertTrue(mgr.begin_run("run_rich_b", ["run_rich_b.json"]))
            mgr.ingest_conversation(conversation, "run_rich_b.json", run_id="run_rich_b")
            mgr.finalize_run()
            mgr.conn.set_trace_callback(None)
            mgr.close()

            content_write_prefixes = (
                "INSERT INTO CONVERSATIONS ",
                "UPDATE CONVERSATIONS ",
                "INSERT INTO NODES ",
                "INSERT INTO NODE_CHILDREN ",
                "INSERT INTO MESSAGES ",
                "DELETE FROM MESSAGE_FTS ",
                "INSERT INTO MESSAGE_FTS ",
                "INSERT INTO LINKS ",
                "INSERT INTO ATTACHMENTS ",
                "INSERT INTO TOOL_CALLS ",
                "INSERT INTO TOOL_RESULTS ",
            )
            content_writes = [
                statement
                for statement in statements
                if " ".join(statement.upper().split()).startswith(content_write_prefixes)
            ]
            self.assertEqual(content_writes, [])

            with self._open(db_path) as conn:
                canonical = conn.execute(
                    "SELECT run_id FROM conversations WHERE id = 'rich_conv'"
                ).fetchone()[0]
                self.assertEqual(canonical, "run_rich_a")

                snapshots = conn.execute(
                    """
                    SELECT run_id, is_canonical_snapshot
                    FROM conversation_runs
                    WHERE conversation_id = 'rich_conv'
                    ORDER BY run_id
                    """
                ).fetchall()
                self.assertEqual(
                    [tuple(row) for row in snapshots],
                    [("run_rich_a", 1), ("run_rich_b", 0)],
                )
                self.assertEqual(
                    conn.execute(
                        "SELECT COUNT(*) FROM message_runs WHERE conversation_id = 'rich_conv'"
                    ).fetchone()[0],
                    8,
                )
                for table in ("links", "attachments", "tool_calls", "tool_results"):
                    run_ids = {
                        row[0]
                        for row in conn.execute(
                            f"SELECT DISTINCT run_id FROM {table} WHERE conversation_id = 'rich_conv'"
                        )
                    }
                    self.assertEqual(run_ids, {"run_rich_a"})

                first_stats = json.loads(
                    conn.execute("SELECT stats FROM runs WHERE run_id = 'run_rich_a'").fetchone()[0]
                )
                second_stats = json.loads(
                    conn.execute("SELECT stats FROM runs WHERE run_id = 'run_rich_b'").fetchone()[0]
                )
                self.assertEqual(second_stats, first_stats)
        finally:
            os.unlink(db_path)

    def test_new_conversations_do_not_issue_fts_deletes(self):
        handle = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        db_path = handle.name
        handle.close()
        try:
            mgr = CanonicalManager(db_path)
            statements = []
            mgr.conn.set_trace_callback(statements.append)
            self.assertTrue(mgr.begin_run("run_new", ["run_new.json"]))
            mgr.ingest_conversation(_make_extended("new_conv"), "run_new.json", run_id="run_new")
            mgr.finalize_run()
            mgr.conn.set_trace_callback(None)
            mgr.close()

            fts_deletes = [
                statement
                for statement in statements
                if " ".join(statement.upper().split()).startswith("DELETE FROM MESSAGE_FTS")
            ]
            self.assertEqual(fts_deletes, [])
        finally:
            os.unlink(db_path)


if __name__ == "__main__":
    unittest.main()
