import json
import os
import sqlite3
import sys
import tempfile
import time
import unittest
from contextlib import closing, redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

sys.path.append(str(Path(__file__).resolve().parents[1]))

from chatgpt_parser.cli.commands import (
    run_canonical_ingest,
    run_export_bundle,
    run_export_conversations,
    run_query,
)
from chatgpt_parser.db.maintenance import run_dump_db, run_list_runs, run_restore_db
from chatgpt_parser.utils.logging import setup_logging


def _make_conv(conv_id: str, text: str, ts: float | None = None):
    ts = ts if ts is not None else time.time()
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


class ExportAndMaintenanceTests(unittest.TestCase):
    def _ingest_sample(self, sample):
        logger = setup_logging(None, verbose=False)
        tmpdir = tempfile.mkdtemp()
        export_path = os.path.join(tmpdir, "export.json")
        with open(export_path, "w", encoding="utf-8") as handle:
            json.dump(sample, handle)

        db_path = os.path.join(tmpdir, "db.sqlite")
        args = SimpleNamespace(
            inputs=[export_path],
            db=db_path,
            run_id="test_run",
            mode="skip_existing",
            streaming=False,
        )
        run_canonical_ingest(args, logger)
        return tmpdir, db_path, logger

    def test_export_conversations_writes_markdown_files(self):
        tmpdir, db_path, logger = self._ingest_sample(
            [_make_conv("conv1", "alpha"), _make_conv("conv2", "beta")]
        )
        output_dir = os.path.join(tmpdir, "exports")

        args = SimpleNamespace(
            db=db_path,
            query=None,
            limit=2,
            output_dir=output_dir,
            format="markdown",
            include_hidden="false",
            frontmatter=False,
        )
        run_export_conversations(args, logger)

        files = sorted(os.listdir(output_dir))
        self.assertEqual(files, ["conv1.md", "conv2.md"])

        with open(os.path.join(output_dir, "conv1.md"), "r", encoding="utf-8") as handle:
            content = handle.read()
        self.assertIn("# title conv1", content)
        self.assertIn("alpha", content)

    def test_export_conversations_text_format_writes_plain_text_files(self):
        tmpdir, db_path, logger = self._ingest_sample([_make_conv("conv_text", "plain text body")])
        output_dir = os.path.join(tmpdir, "exports_text")

        args = SimpleNamespace(
            db=db_path,
            query=None,
            limit=1,
            output_dir=output_dir,
            format="text",
            include_hidden="false",
            frontmatter=False,
        )
        run_export_conversations(args, logger)

        with open(os.path.join(output_dir, "conv_text.txt"), "r", encoding="utf-8") as handle:
            content = handle.read()

        self.assertIn("Title: title conv_text", content)
        self.assertIn("plain text body", content)
        self.assertNotIn("# title conv_text", content)
        self.assertNotIn("```", content)

    def test_export_bundle_writes_recent_bundle(self):
        recent = time.time()
        tmpdir, db_path, logger = self._ingest_sample(
            [_make_conv("conv_recent_1", "bundle alpha", recent), _make_conv("conv_recent_2", "bundle beta", recent + 1)]
        )
        output_markdown = os.path.join(tmpdir, "bundle.md")

        args = SimpleNamespace(
            db=db_path,
            since_days=30,
            output_markdown=output_markdown,
            include_hidden="false",
            frontmatter=False,
        )
        run_export_bundle(args, logger)

        with open(output_markdown, "r", encoding="utf-8") as handle:
            content = handle.read()

        self.assertIn("# ChatGPT Conversation Bundle", content)
        self.assertIn("bundle alpha", content)
        self.assertIn("bundle beta", content)

    def test_list_runs_outputs_json(self):
        _, db_path, logger = self._ingest_sample([_make_conv("conv_runs", "history")])

        buf = StringIO()
        with redirect_stdout(buf):
            run_list_runs(SimpleNamespace(db=db_path, format="json"), logger)

        payload = json.loads(buf.getvalue())
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["run_id"], "test_run")
        self.assertIn("started_at", payload[0])

    def test_dump_and_restore_round_trip(self):
        tmpdir, db_path, logger = self._ingest_sample([_make_conv("conv_restore", "round trip")])
        dump_path = os.path.join(tmpdir, "archive.sql")
        restored_path = os.path.join(tmpdir, "restored.sqlite")

        run_dump_db(SimpleNamespace(db=db_path, output=dump_path), logger)
        self.assertTrue(os.path.exists(dump_path))

        run_restore_db(SimpleNamespace(input=dump_path, db=restored_path, force=False), logger)
        self.assertTrue(os.path.exists(restored_path))

        with closing(sqlite3.connect(restored_path)) as conn:
            cur = conn.cursor()
            cur.execute("SELECT id, message_count FROM conversations")
            conversations = cur.fetchall()
            cur.execute("SELECT run_id FROM runs")
            runs = cur.fetchall()
            cur.execute("SELECT conversation_id FROM message_fts WHERE message_fts MATCH 'round'")
            search_rows = cur.fetchall()

        self.assertEqual(conversations, [("conv_restore", 1)])
        self.assertEqual(runs, [("test_run",)])
        self.assertEqual(search_rows, [("conv_restore",)])

    def test_query_conversations_allows_safe_order_by(self):
        tmpdir, db_path, logger = self._ingest_sample(
            [_make_conv("conv_old", "older", 10.0), _make_conv("conv_new", "newer", 20.0)]
        )

        buf = StringIO()
        with redirect_stdout(buf):
            run_query(
                SimpleNamespace(
                    db=db_path,
                    type="conversations",
                    limit=2,
                    conversation_id=None,
                    include_hidden="false",
                    format="json",
                    order_by="created_at ASC",
                ),
                logger,
            )

        payload = json.loads(buf.getvalue())
        self.assertEqual([row["id"] for row in payload], ["conv_old", "conv_new"])

    def test_query_conversations_rejects_unsafe_order_by(self):
        _, db_path, logger = self._ingest_sample([_make_conv("conv_safe", "safe")])

        buf = StringIO()
        with redirect_stdout(buf):
            run_query(
                SimpleNamespace(
                    db=db_path,
                    type="conversations",
                    limit=5,
                    conversation_id=None,
                    include_hidden="false",
                    format="json",
                    order_by="created_at; DROP TABLE conversations",
                ),
                logger,
            )

        self.assertEqual(buf.getvalue(), "")
        with closing(sqlite3.connect(db_path)) as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM conversations")
            self.assertEqual(cur.fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
