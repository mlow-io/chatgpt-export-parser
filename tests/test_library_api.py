import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import zipfile
from contextlib import closing
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from chatgpt_parser import (
    IngestError,
    ingest_exports,
    inspect_inputs,
    parser_contract,
)


def _conversation(conversation_id: str):
    node_id = f"node_{conversation_id}"
    return {
        "id": conversation_id,
        "title": f"Conversation {conversation_id}",
        "create_time": 1.0,
        "update_time": 2.0,
        "current_node": node_id,
        "mapping": {
            node_id: {
                "id": node_id,
                "parent": None,
                "children": [],
                "message": {
                    "id": f"message_{conversation_id}",
                    "author": {"role": "user"},
                    "content": {"content_type": "text", "parts": ["library contract"]},
                    "create_time": 1.0,
                },
            }
        },
    }


class LibraryAPITests(unittest.TestCase):
    def test_contract_is_machine_readable_and_versioned(self):
        contract = parser_contract()
        self.assertEqual(contract["contract_version"], 1)
        self.assertGreaterEqual(contract["canonical_schema_version"], 2)
        self.assertIn("ingest_exports", contract["operations"])
        self.assertIn("export_folder", contract["input_kinds"])

    def test_direct_library_ingest_supports_split_export_folder(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            export_dir = os.path.join(tmpdir, "export")
            os.makedirs(export_dir)
            for index, conversation_id in enumerate(("first", "second")):
                with open(os.path.join(export_dir, f"conversations-{index:03}.json"), "w", encoding="utf-8") as handle:
                    json.dump([_conversation(conversation_id)], handle)

            inspection = inspect_inputs([export_dir])
            self.assertTrue(inspection.can_ingest)
            self.assertEqual(len(inspection.sources), 2)

            database = os.path.join(tmpdir, "archive.sqlite3")
            result = ingest_exports([export_dir], database, run_id="library_run")
            self.assertFalse(result.failed)
            self.assertEqual(result.stats["conversations"], 2)

            with closing(sqlite3.connect(database)) as connection:
                rows = connection.execute("SELECT id FROM conversations ORDER BY id").fetchall()
            self.assertEqual(rows, [("first",), ("second",)])

    def test_direct_library_ingest_supports_zip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            json_path = os.path.join(tmpdir, "conversations.json")
            with open(json_path, "w", encoding="utf-8") as handle:
                json.dump([_conversation("zip")], handle)
            zip_path = os.path.join(tmpdir, "export.zip")
            with zipfile.ZipFile(zip_path, "w") as archive:
                archive.write(json_path, arcname="nested/conversations.json")

            result = ingest_exports([zip_path], os.path.join(tmpdir, "archive.sqlite3"), run_id="zip_run")
            self.assertEqual(result.stats["conversations"], 1)

    def test_diagnostic_only_input_raises_typed_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            html_path = os.path.join(tmpdir, "chat.html")
            with open(html_path, "w", encoding="utf-8") as handle:
                handle.write('<script>var jsonData = [{"id": "diagnostic"}];</script>')

            with self.assertRaises(IngestError) as raised:
                ingest_exports([html_path], os.path.join(tmpdir, "archive.sqlite3"))
            self.assertTrue(raised.exception.result.failed)
            self.assertEqual(raised.exception.result.diagnostics[0]["kind"], "chat_html")

    def test_package_module_exposes_contract_for_native_clients(self):
        completed = subprocess.run(
            [sys.executable, "-m", "chatgpt_parser", "--json", "contract"],
            cwd=Path(__file__).resolve().parents[1],
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["contract_version"], 1)


if __name__ == "__main__":
    unittest.main()
