import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from io import StringIO
from contextlib import redirect_stdout, closing

sys.path.append(str(Path(__file__).resolve().parents[1]))

from chatgpt_parser.cli.commands import run_parse, run_ingest
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
    def test_parse_and_ingest_flow(self):
        """Simulate the parse-and-ingest logic from main.py"""
        sample = [_make_simple_conv("integration_test")]
        
        with tempfile.TemporaryDirectory() as tmpdir:
            # 1. Prepare Input
            export_path = os.path.join(tmpdir, "export.json")
            with open(export_path, "w", encoding="utf-8") as f:
                json.dump(sample, f)
            
            # 2. Setup Args mimicking main.py structure
            db_path = os.path.join(tmpdir, "integration.db")
            args = SimpleNamespace(
                command="parse-and-ingest",
                inputs=[export_path],
                output_dir=None,
                output_root=tmpdir,
                run_id="integration_run",
                force=True,
                streaming=False,
                db=db_path,
                mode="overwrite",
                jsonl_dir=None # Will be filled by parse result
            )
            logger = setup_logging(None, verbose=False)

            # 3. Run Parse
            res = run_parse(args, logger)
            self.assertIsNotNone(res)
            out_dir, run_id = res
            self.assertEqual(run_id, "integration_run")
            
            # 4. Inject jsonl_dir and Run Ingest
            args.jsonl_dir = out_dir
            run_ingest(args, logger)

            # 5. Verify DB Content
            import sqlite3
            with closing(sqlite3.connect(db_path)) as conn:
                cur = conn.cursor()
                cur.execute("SELECT id FROM conversations")
                rows = cur.fetchall()
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0][0], "integration_test")
                
                cur.execute("SELECT run_id FROM runs")
                runs = cur.fetchall()
                self.assertEqual(len(runs), 1)
                self.assertEqual(runs[0][0], "integration_run")

if __name__ == "__main__":
    unittest.main()
