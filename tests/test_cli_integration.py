import json
import os
import sqlite3
import sys
import tempfile
import unittest
import zipfile
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

    def test_zip_input_matches_standard_flow(self):
        sample = [_make_simple_conv("zip_test")]

        with tempfile.TemporaryDirectory() as tmpdir:
            json_path = os.path.join(tmpdir, "conversations.json")
            with open(json_path, "w", encoding="utf-8") as handle:
                json.dump(sample, handle)

            zip_path = os.path.join(tmpdir, "export.zip")
            with zipfile.ZipFile(zip_path, "w") as archive:
                archive.write(json_path, arcname="conversations.json")

            db_path = os.path.join(tmpdir, "zip.db")
            args = SimpleNamespace(
                command="parse-and-ingest",
                inputs=[zip_path],
                db=db_path,
                run_id="zip_run",
                mode="skip_existing",
                streaming=True,
            )
            logger = setup_logging(None, verbose=False)

            run_canonical_ingest(args, logger)

            with closing(sqlite3.connect(db_path)) as conn:
                cur = conn.cursor()
                cur.execute("SELECT id, run_id, message_count FROM conversations")
                rows = cur.fetchall()
                self.assertEqual(rows, [("zip_test", "zip_run", 1)])

    def test_streaming_and_non_streaming_ingest_produce_same_rows(self):
        sample = [_make_simple_conv("stream_a"), _make_simple_conv("stream_b")]

        with tempfile.TemporaryDirectory() as tmpdir:
            export_path = os.path.join(tmpdir, "export.json")
            with open(export_path, "w", encoding="utf-8") as handle:
                json.dump(sample, handle)

            logger = setup_logging(None, verbose=False)
            streaming_db = os.path.join(tmpdir, "streaming.db")
            non_streaming_db = os.path.join(tmpdir, "non_streaming.db")

            run_canonical_ingest(
                SimpleNamespace(
                    command="parse-and-ingest",
                    inputs=[export_path],
                    db=streaming_db,
                    run_id="streaming_run",
                    mode="skip_existing",
                    streaming=True,
                ),
                logger,
            )
            run_canonical_ingest(
                SimpleNamespace(
                    command="parse-and-ingest",
                    inputs=[export_path],
                    db=non_streaming_db,
                    run_id="non_streaming_run",
                    mode="skip_existing",
                    streaming=False,
                ),
                logger,
            )

            with closing(sqlite3.connect(streaming_db)) as streaming_conn, closing(sqlite3.connect(non_streaming_db)) as non_streaming_conn:
                streaming_rows = streaming_conn.execute(
                    "SELECT id, title, message_count, message_count_main_path FROM conversations ORDER BY id"
                ).fetchall()
                non_streaming_rows = non_streaming_conn.execute(
                    "SELECT id, title, message_count, message_count_main_path FROM conversations ORDER BY id"
                ).fetchall()
                self.assertEqual(streaming_rows, non_streaming_rows)

    def test_export_folder_with_split_conversation_json_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "conversations-001.json"), "w", encoding="utf-8") as handle:
                json.dump([_make_simple_conv("folder_b")], handle)
            with open(os.path.join(tmpdir, "conversations-000.json"), "w", encoding="utf-8") as handle:
                json.dump([_make_simple_conv("folder_a")], handle)
            with open(os.path.join(tmpdir, "user.json"), "w", encoding="utf-8") as handle:
                json.dump({"ignored": True}, handle)
            with open(os.path.join(tmpdir, "chat.html"), "w", encoding="utf-8") as handle:
                handle.write("<html><script>var jsonData = [];</script></html>")

            db_path = os.path.join(tmpdir, "folder.db")
            trace_path = os.path.join(tmpdir, "trace.json")
            args = SimpleNamespace(
                command="parse-and-ingest",
                inputs=[tmpdir],
                db=db_path,
                run_id="folder_run",
                mode="skip_existing",
                streaming=True,
                trace_run=trace_path,
            )
            logger = setup_logging(None, verbose=False)

            result = run_canonical_ingest(args, logger)

            self.assertFalse(result.get("failed"))
            with closing(sqlite3.connect(db_path)) as conn:
                rows = conn.execute("SELECT id FROM conversations ORDER BY id").fetchall()
            self.assertEqual(rows, [("folder_a",), ("folder_b",)])

            with open(trace_path, "r", encoding="utf-8") as handle:
                trace = json.load(handle)
            self.assertEqual(len(trace["discovered_sources"]), 2)
            self.assertEqual([source["path"].split(os.sep)[-1] for source in trace["discovered_sources"]], ["conversations-000.json", "conversations-001.json"])
            self.assertEqual([row["conversations_seen"] for row in trace["source_results"]], [1, 1])
            self.assertEqual(trace["diagnostics"][0]["kind"], "chat_html")

    def test_zip_with_split_conversation_json_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            first = os.path.join(tmpdir, "conversations-000.json")
            second = os.path.join(tmpdir, "conversations-001.json")
            with open(first, "w", encoding="utf-8") as handle:
                json.dump([_make_simple_conv("zip_a")], handle)
            with open(second, "w", encoding="utf-8") as handle:
                json.dump([_make_simple_conv("zip_b")], handle)

            zip_path = os.path.join(tmpdir, "split.zip")
            with zipfile.ZipFile(zip_path, "w") as archive:
                archive.write(second, arcname="nested/conversations-001.json")
                archive.write(first, arcname="nested/conversations-000.json")

            db_path = os.path.join(tmpdir, "zip_split.db")
            args = SimpleNamespace(
                command="parse-and-ingest",
                inputs=[zip_path],
                db=db_path,
                run_id="zip_split_run",
                mode="skip_existing",
                streaming=True,
                trace_run=None,
            )
            logger = setup_logging(None, verbose=False)

            result = run_canonical_ingest(args, logger)

            self.assertFalse(result.get("failed"))
            with closing(sqlite3.connect(db_path)) as conn:
                rows = conn.execute("SELECT id FROM conversations ORDER BY id").fetchall()
            self.assertEqual(rows, [("zip_a",), ("zip_b",)])

    def test_chat_html_input_is_diagnostic_not_canonical_source(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            html_path = os.path.join(tmpdir, "chat.html")
            trace_path = os.path.join(tmpdir, "trace.json")
            with open(html_path, "w", encoding="utf-8") as handle:
                handle.write('<html><script>var jsonData = [{"id": "html_conv", "create_time": 1.0}];</script></html>')

            result = run_canonical_ingest(
                SimpleNamespace(
                    command="parse-and-ingest",
                    inputs=[html_path],
                    db=os.path.join(tmpdir, "html.db"),
                    run_id="html_run",
                    mode="skip_existing",
                    streaming=True,
                    trace_run=trace_path,
                ),
                setup_logging(None, verbose=False),
            )

            self.assertTrue(result.get("failed"))
            self.assertFalse(os.path.exists(os.path.join(tmpdir, "html.db")))
            with open(trace_path, "r", encoding="utf-8") as handle:
                trace = json.load(handle)
            self.assertEqual(trace["diagnostics"][0]["kind"], "chat_html")
            self.assertEqual(trace["diagnostics"][0]["embedded_conversation_count"], 1)


if __name__ == "__main__":
    unittest.main()
