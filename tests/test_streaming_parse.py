import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.append(str(Path(__file__).resolve().parents[1]))

from ChatGPT_Export_parser import run_parse, setup_logging


def _make_conversation(conv_id: str, message_id: str, ts: float):
    node_id = f"node_{conv_id}"
    return {
        "id": conv_id,
        "title": f"Conversation {conv_id}",
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
                    "id": message_id,
                    "author": {"role": "user"},
                    "content": {"content_type": "text", "parts": [f"hello {conv_id}"]},
                    "create_time": ts,
                    "update_time": ts,
                },
            }
        },
    }


def _make_branch_conversation(conv_id: str):
    root_id = f"node_{conv_id}_root"
    child_a = f"node_{conv_id}_a"
    child_b = f"node_{conv_id}_b"
    return {
        "id": conv_id,
        "title": f"Conversation {conv_id}",
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


class StreamingParseTests(unittest.TestCase):
    def test_streaming_parse_writes_jsonl_files(self):
        sample = [
            _make_conversation("conv_stream_1", "msg_1", 1.0),
            _make_conversation("conv_stream_2", "msg_2", 2.0),
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            export_path = os.path.join(tmpdir, "export.json")
            with open(export_path, "w", encoding="utf-8") as f:
                json.dump(sample, f)

            args = SimpleNamespace(
                inputs=[export_path],
                output_dir=None,
                output_root=tmpdir,
                run_id="test_stream_run",
                force=True,
                streaming=True,
                stream_chunk_size=8,  # small to force multiple chunks
            )
            logger = setup_logging(None, verbose=False)

            res = run_parse(args, logger)
            self.assertIsNotNone(res)
            out_dir, run_id = res

            conversations_path = os.path.join(out_dir, "conversations.jsonl")
            messages_path = os.path.join(out_dir, "messages.jsonl")
            node_children_path = os.path.join(out_dir, "node_children.jsonl")
            run_json_path = os.path.join(out_dir, "run.json")

            self.assertTrue(os.path.exists(conversations_path))
            self.assertTrue(os.path.exists(messages_path))
            self.assertTrue(os.path.exists(node_children_path))
            self.assertTrue(os.path.exists(run_json_path))

            with open(conversations_path, "r", encoding="utf-8") as f:
                conv_rows = [json.loads(line) for line in f]
            ids = {c["id"] for c in conv_rows}
            self.assertEqual(ids, {"conv_stream_1", "conv_stream_2"})

            with open(messages_path, "r", encoding="utf-8") as f:
                msg_rows = [json.loads(line) for line in f]
            self.assertEqual(len(msg_rows), 2)
            self.assertTrue(all(m["message_kind"] == "user_visible_user" for m in msg_rows))
            self.assertEqual(run_id, "test_stream_run")

    def test_node_children_written_for_branch(self):
        sample = [_make_branch_conversation("conv_branch")]

        with tempfile.TemporaryDirectory() as tmpdir:
            export_path = os.path.join(tmpdir, "export.json")
            with open(export_path, "w", encoding="utf-8") as f:
                json.dump(sample, f)

            args = SimpleNamespace(
                inputs=[export_path],
                output_dir=None,
                output_root=tmpdir,
                run_id="test_branch_run",
                force=True,
                streaming=False,
            )
            logger = setup_logging(None, verbose=False)

            res = run_parse(args, logger)
            self.assertIsNotNone(res)
            out_dir, _ = res

            node_children_path = os.path.join(out_dir, "node_children.jsonl")
            with open(node_children_path, "r", encoding="utf-8") as f:
                rows = [json.loads(line) for line in f]

            self.assertEqual(len(rows), 2)
            self.assertEqual({row["parent_node_id"] for row in rows}, {"node_conv_branch_root"})
            ordered_children = [row["child_node_id"] for row in sorted(rows, key=lambda r: r["child_index"])]
            self.assertEqual(
                ordered_children,
                ["node_conv_branch_a", "node_conv_branch_b"],
            )


if __name__ == "__main__":
    unittest.main()
