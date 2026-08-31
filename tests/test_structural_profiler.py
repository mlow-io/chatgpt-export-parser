import json
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from chatgpt_parser import profile_export


def _privacy_trap_conversation():
    private_email = "profile" + "@" + "example.invalid"
    private_url = "https://private.example.invalid/token-value"
    private_path = "/" + "local" + "/confidential/account-data"
    return {
        "id": "private-conversation-id",
        "title": "Private title must not appear",
        "current_node": "private-node-id",
        "mapping": {
            "private-node-id": {
                "id": "private-node-id",
                "parent": None,
                "children": [],
                "message": {
                    "id": "private-message-id",
                    "author": {"role": "user", "name": private_email},
                    "content": {
                        "content_type": "text",
                        "parts": ["Private prompt and response text must not appear"],
                    },
                    "metadata": {
                        "private_metadata_key": private_path,
                        "attachments": [{
                            "filename": "private_attachment_name.pdf",
                            "url": private_url,
                            "type": "image",
                        }],
                    },
                },
            }
        },
    }


class StructuralProfilerTests(unittest.TestCase):
    def test_profile_is_content_free_and_reports_safe_structure(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = os.path.join(tmpdir, "person-specific-export.json")
            with open(input_path, "w", encoding="utf-8") as handle:
                json.dump([_privacy_trap_conversation()], handle)

            report = profile_export(input_path, label="export-A", acquisition_date="2026-08-01")

        serialized = json.dumps(report, sort_keys=True)
        for forbidden in (
            "person-specific-export.json",
            "Private title must not appear",
            "Private prompt and response text must not appear",
            "private-conversation-id",
            "private-node-id",
            "private-message-id",
            "profile@example.invalid",
            "private.example.invalid/token-value",
            "private_attachment_name.pdf",
            "/local/confidential/account-data",
            "private_metadata_key",
            tmpdir,
        ):
            self.assertNotIn(forbidden, serialized)

        self.assertEqual(report["compatibility"], "candidate_supported")
        self.assertEqual(report["members"][0]["name"], "input.json")
        self.assertEqual(report["members"][0]["detected_dialect"], "mapping_tree_array")
        self.assertEqual(report["members"][0]["normalization_generation"], "mapping-tree-v1")
        self.assertEqual(report["members"][0]["structure"]["safe_enums"], {
            "content_types": ["text"],
            "resource_types": ["image"],
            "roles": ["user"],
        })
        self.assertTrue(report["privacy"]["content_free"])
        self.assertRegex(report["structural_fingerprint"], r"^[0-9a-f]{64}$")

    def test_structural_fingerprint_is_location_and_content_free(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            first_path = os.path.join(tmpdir, "first-private-name.json")
            second_path = os.path.join(tmpdir, "second-private-name.json")
            first = _privacy_trap_conversation()
            second = _privacy_trap_conversation()
            second["title"] = "A different private title"
            second["mapping"]["private-node-id"]["message"]["content"]["parts"] = [
                "A different private message body"
            ]
            node = second["mapping"].pop("private-node-id")
            node["id"] = "different-private-node-id"
            node["message"]["id"] = "different-private-message-id"
            second["mapping"]["different-private-node-id"] = node
            second["current_node"] = "different-private-node-id"
            for path, conversation in ((first_path, first), (second_path, second)):
                with open(path, "w", encoding="utf-8") as handle:
                    json.dump([conversation], handle)

            first_report = profile_export(first_path, label="export-E")
            second_report = profile_export(second_path, label="export-F")

        self.assertEqual(first_report["structural_fingerprint"], second_report["structural_fingerprint"])
        self.assertNotEqual(
            first_report["members"][0]["content_sha256"],
            second_report["members"][0]["content_sha256"],
        )

    def test_profile_sanitizes_zip_member_paths_and_keeps_packaging_separate(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source_path = os.path.join(tmpdir, "source.json")
            zip_path = os.path.join(tmpdir, "private-export.zip")
            with open(source_path, "w", encoding="utf-8") as handle:
                json.dump([_privacy_trap_conversation()], handle)
            with zipfile.ZipFile(zip_path, "w") as archive:
                archive.write(source_path, arcname="private-person/conversations-010.json")
                archive.writestr("private-person/private-media-name.bin", b"synthetic")

            report = profile_export(zip_path, label="export-B")

        serialized = json.dumps(report, sort_keys=True)
        self.assertNotIn("private-person", serialized)
        self.assertNotIn("private-media-name.bin", serialized)
        self.assertEqual(report["container"]["kind"], "zip_archive")
        self.assertEqual(report["compatibility"], "candidate_supported")
        self.assertEqual(
            {member["name"] for member in report["members"]},
            {"member-0001/conversations-010.json", "member-0002/member-0002.bin"},
        )

    def test_profile_recursively_inspects_a_selected_folder_without_raw_paths(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            nested = os.path.join(tmpdir, "private-folder", "nested-export")
            os.makedirs(nested)
            input_path = os.path.join(nested, "conversations.json")
            with open(input_path, "w", encoding="utf-8") as handle:
                json.dump([_privacy_trap_conversation()], handle)

            report = profile_export(tmpdir, label="export-folder")

        serialized = json.dumps(report, sort_keys=True)
        self.assertNotIn("private-folder", serialized)
        self.assertNotIn("nested-export", serialized)
        self.assertNotIn(tmpdir, serialized)
        self.assertEqual(report["container"]["kind"], "directory")
        self.assertEqual(report["compatibility"], "candidate_supported")
        self.assertEqual(report["members"][0]["name"], "member-0001/conversations.json")

    def test_profile_labels_jsonl_as_unverified_and_does_not_ingest(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = os.path.join(tmpdir, "observed.jsonl")
            with open(input_path, "w", encoding="utf-8") as handle:
                for _ in range(2):
                    json.dump(_privacy_trap_conversation(), handle)
                    handle.write("\n")

            report = profile_export(input_path, label="export-C")

        member = report["members"][0]
        self.assertEqual(member["framing"], "jsonl")
        self.assertEqual(member["detected_dialect"], "unsupported_jsonl_not_verified")
        self.assertEqual(member["compatibility"], "reject")
        self.assertEqual(report["compatibility"], "reject")
        self.assertIn({"severity": "fatal", "code": "jsonl_not_verified"}, member["findings"])

    def test_profile_rejects_inconsistent_mapping_without_emitting_identifiers(self):
        conversation = _privacy_trap_conversation()
        conversation["mapping"]["private-node-id"]["children"] = ["missing-private-node"]
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = os.path.join(tmpdir, "inconsistent.json")
            with open(input_path, "w", encoding="utf-8") as handle:
                json.dump([conversation], handle)
            report = profile_export(input_path, label="export-D")

        self.assertEqual(report["compatibility"], "reject")
        self.assertIn(
            {"severity": "fatal", "code": "dangling_child_reference"},
            report["members"][0]["findings"],
        )
        self.assertNotIn("missing-private-node", json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    unittest.main()
