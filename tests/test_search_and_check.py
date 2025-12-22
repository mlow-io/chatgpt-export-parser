import json
import os
import sys
import tempfile
import unittest
from io import StringIO
from types import SimpleNamespace
from contextlib import redirect_stdout, closing
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from chatgpt_parser.cli.commands import run_parse, run_ingest, run_search
from chatgpt_parser.db.maintenance import run_check
from chatgpt_parser.core.exporter import run_export_conversation
from chatgpt_parser.utils.logging import setup_logging


def _make_conv(conv_id: str, text: str, ts: float = 1.0):
    node_id = f"node_{conv_id}"
    return {
        "id": conv_id,
        "title": f"title {conv_id}",
        "create_time": ts,
        "update_time": ts,
        "default_model_slug": "gpt-test",
        "current_node": node_id,
        "mapping": {
            node_id: {
                "id": node_id,
                "parent": None,
                "children": [],
                "message": {
                    "id": f"msg_{conv_id}",
                    "author": {"role": "user"},
                    "content": {"content_type": "text", "parts": [text]},
                    "create_time": ts,
                    "update_time": ts,
                },
            }
        },
    }


def _make_branch_conv(conv_id: str):
    root_id = f"node_{conv_id}_root"
    child_a = f"node_{conv_id}_a"
    child_b = f"node_{conv_id}_b"
    return {
        "id": conv_id,
        "title": f"title {conv_id}",
        "create_time": 1.0,
        "update_time": 3.0,
        "default_model_slug": "gpt-test",
        "current_node": child_a,
        "mapping": {
            root_id: {
                "id": root_id,
                "parent": None,
                "children": [child_a, child_b],
                "message": {
                    "id": f"msg_{conv_id}_root",
                    "author": {"role": "user"},
                    "content": {"content_type": "text", "parts": ["hello"]},
                    "create_time": 1.0,
                    "update_time": 1.0,
                },
            },
            child_a: {
                "id": child_a,
                "parent": root_id,
                "children": [],
                "message": {
                    "id": f"msg_{conv_id}_a",
                    "author": {"role": "assistant"},
                    "content": {"content_type": "text", "parts": ["branch a"]},
                    "create_time": 2.0,
                    "update_time": 2.0,
                },
            },
            child_b: {
                "id": child_b,
                "parent": root_id,
                "children": [],
                "message": {
                    "id": f"msg_{conv_id}_b",
                    "author": {"role": "assistant"},
                    "content": {"content_type": "text", "parts": ["branch b"]},
                    "create_time": 3.0,
                    "update_time": 3.0,
                },
            },
        },
    }


class SearchAndCheckTests(unittest.TestCase):
    def _parse_and_ingest(self, sample):
        logger = setup_logging(None, verbose=False)
        tmpdir = tempfile.mkdtemp()
        export_path = os.path.join(tmpdir, "export.json")
        with open(export_path, "w", encoding="utf-8") as f:
            json.dump(sample, f)

        parse_args = SimpleNamespace(
            inputs=[export_path],
            output_dir=None,
            output_root=tmpdir,
            run_id="test_run",
            force=True,
            streaming=False,
        )
        res = run_parse(parse_args, logger)
        self.assertIsNotNone(res)
        out_dir, run_id = res

        db_path = os.path.join(tmpdir, "db.sqlite")
        ingest_args = SimpleNamespace(
            jsonl_dir=out_dir,
            db=db_path,
            mode="overwrite",
            run_id=run_id,
        )
        run_ingest(ingest_args, logger)
        return db_path, run_id

    def test_search_fts(self):
        db_path, run_id = self._parse_and_ingest(
            [_make_conv("conv1", "I like pizza"), _make_conv("conv2", "no pizza here")]
        )
        logger = setup_logging(None, verbose=False)
        import sqlite3
        with closing(sqlite3.connect(db_path)) as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM message_fts")
            count = cur.fetchone()[0]
            cur.execute("SELECT conversation_id FROM message_fts WHERE message_fts MATCH 'pizza'")
            direct = {r[0] for r in cur.fetchall()}
        self.assertGreater(count, 0)
        self.assertEqual(direct, {"conv1", "conv2"})
        buf = StringIO()
        search_args = SimpleNamespace(
            db=db_path,
            q="pizza",
            role=None,
            kind=None,
            conversation_id=None,
            run_id=None,
            limit=10,
            offset=0,
            format="json",
        )
        with redirect_stdout(buf):
            run_search(search_args, logger)
        output = json.loads(buf.getvalue())
        conv_ids = {row["conversation_id"] for row in output}
        self.assertEqual(conv_ids, {"conv1", "conv2"})

    def test_check_ok(self):
        db_path, _ = self._parse_and_ingest([_make_conv("convA", "hello world")])
        logger = setup_logging(None, verbose=False)
        buf = StringIO()
        check_args = SimpleNamespace(db=db_path, format="json")
        with redirect_stdout(buf):
            run_check(check_args, logger)
        res = json.loads(buf.getvalue())
        self.assertTrue(res["ok"])

    def test_export_conversation(self):
        db_path, _ = self._parse_and_ingest([_make_conv("convX", "export me")])
        logger = setup_logging(None, verbose=False)
        buf = StringIO()
        export_args = SimpleNamespace(
            db=db_path,
            conversation_id="convX",
            format="markdown",
            output=None,
            include_hidden="false",
        )
        with redirect_stdout(buf):
            run_export_conversation(export_args, logger)
        content = buf.getvalue()
        self.assertIn("export me", content)
        self.assertIn("convX", content)

    def test_node_children_ingest(self):
        db_path, _ = self._parse_and_ingest([_make_branch_conv("conv_branch")])
        logger = setup_logging(None, verbose=False)
        import sqlite3
        with closing(sqlite3.connect(db_path)) as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM node_children")
            count = cur.fetchone()[0]
        self.assertEqual(count, 2)


if __name__ == "__main__":
    unittest.main()
