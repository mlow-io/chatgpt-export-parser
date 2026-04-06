import json
import os
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

sys.path.append(str(Path(__file__).resolve().parents[1]))

from chatgpt_parser.cli.commands import run_canonical_ingest
from chatgpt_parser.utils.logging import setup_logging


def _make_simple_conv(conv_id="conv1"):
    node_id = f"node_{conv_id}"
    return {
        "id": conv_id,
        "title": f"Test {conv_id}",
        "create_time": 1000.0,
        "update_time": 1000.0,
        "default_model_slug": "gpt-4",
        "current_node": node_id,
        "mapping": {
            node_id: {
                "id": node_id,
                "parent": None,
                "children": [],
                "message": {
                    "id": f"msg_{conv_id}",
                    "author": {"role": "user"},
                    "content": {"content_type": "text", "parts": ["Integration test"]},
                    "create_time": 1000.0,
                },
            }
        },
    }


class CLIIntegrationTests(unittest.TestCase):
    def test_parse_and_ingest_standard_flow(self):
        sample = [_make_simple_conv("integration_test")]

        with tempfile.TemporaryDirectory() as tmpdir:
            export_path = os.path.join(tmpdir, "export.json")
            with open(export_path, "w", encoding="utf-8") as handle:
                json.dump(sample, handle)

            db_path = os.path.join(tmpdir, "integration.db")
            args = SimpleNamespace(
                command="parse-and-ingest",
                inputs=[export_path],
                db=db_path,
                run_id="integration_run",
                mode="skip_existing",
                streaming=False,
            )
            logger = setup_logging(None, verbose=False)

            run_canonical_ingest(args, logger)

            import sqlite3
            with closing(sqlite3.connect(db_path)) as conn:
                cur = conn.cursor()
                cur.execute("SELECT id, run_id, message_count FROM conversations")
                rows = cur.fetchall()
                self.assertEqual(rows, [("integration_test", "integration_run", 1)])

                cur.execute("SELECT run_id FROM runs")
                runs = cur.fetchall()
                self.assertEqual(runs, [("integration_run",)])

    def test_explicit_canonical_alias_flow(self):
        sample = [_make_simple_conv("canonical_test")]

        with tempfile.TemporaryDirectory() as tmpdir:
            export_path = os.path.join(tmpdir, "export.json")
            with open(export_path, "w", encoding="utf-8") as handle:
                json.dump(sample, handle)

            db_path = os.path.join(tmpdir, "canonical.db")
            args = SimpleNamespace(
                command="canonical-ingest",
                inputs=[export_path],
                db=db_path,
                run_id="canonical_run",
                mode="skip_existing",
                streaming=False,
            )
            logger = setup_logging(None, verbose=False)

            run_canonical_ingest(args, logger)

            import sqlite3
            with closing(sqlite3.connect(db_path)) as conn:
                cur = conn.cursor()
                cur.execute("SELECT id, run_id, message_count FROM conversations")
                rows = cur.fetchall()
                self.assertEqual(rows, [("canonical_test", "canonical_run", 1)])

                cur.execute("SELECT run_id FROM runs")
                runs = cur.fetchall()
                self.assertEqual(runs, [("canonical_run",)])


if __name__ == "__main__":
    unittest.main()
