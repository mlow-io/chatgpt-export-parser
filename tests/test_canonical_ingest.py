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


if __name__ == "__main__":
    unittest.main()
