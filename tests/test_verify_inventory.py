from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path


SCRIPTS_DIR = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))
SCRIPT_PATH = SCRIPTS_DIR / "verify_inventory.py"
SPEC = importlib.util.spec_from_file_location("verify_inventory", SCRIPT_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class VerifyInventoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.channel = self.root / "Channel"
        self.audit_dir = self.channel / ".stream-writedown"
        self.audit_dir.mkdir(parents=True)

    def write_transcript(self, video_id: str, filename: str) -> tuple[str, str]:
        audit_path = self.audit_dir / f"{video_id}.audit.json"
        output_path = self.channel / filename
        body = f"### 話題\n\n{video_id}の本文です。"
        audit = {
            "schema_version": 1,
            "video_id": video_id,
            "source_route": "computer_use",
            "source_export_path": None,
            "source_language": "ja",
            "cues": [{"timestamp": "00:00", "text": f"{video_id}の本文です"}],
            "preproofread_body_markdown": f"### 話題\n\n{video_id}の本文です",
            "proofread_body_markdown": body,
            "translation": {
                "enabled": False,
                "target_language": None,
                "body_markdown": None,
                "review": None,
            },
            "checks": {
                "source_complete": True,
                "source_matches_preproofread": True,
                "proofread_no_omissions": True,
                "proofread_meaning_preserved": True,
            },
        }
        audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
        output_path.write_text(
            "\n".join(
                [
                    "---",
                    f'video_id: "{video_id}"',
                    'transcript_status: "complete"',
                    'transcript_layout: "content_sections"',
                    "proofread: true",
                    f'proofread_audit: ".stream-writedown/{video_id}.audit.json"',
                    "translated: false",
                    "translation_target_language: null",
                    "---",
                    "",
                    "# Title",
                    "",
                    "## 文字起こし",
                    "",
                    body,
                    "",
                ]
            ),
            encoding="utf-8",
        )
        return (
            output_path.relative_to(self.root).as_posix(),
            audit_path.relative_to(self.root).as_posix(),
        )

    @staticmethod
    def item(
        index: int,
        video_id: str,
        output_path: str,
        audit_path: str,
        *,
        status: str = "complete",
    ) -> dict:
        return {
            "inventory_index": index,
            "kind": "video",
            "visibility": "visible",
            "video_id": video_id,
            "title": f"Video {index}",
            "position": index,
            "selected": True,
            "status": status,
            "reason": "reused_existing_verified" if status == "existing_complete" else None,
            "reason_source": None,
            "attempt_count": 1 if status == "complete" else 0,
            "transcript_language": "ja",
            "language_checked": True,
            "output_path": output_path,
            "audit_path": audit_path,
            "verified_at": "2026-08-23T12:00:00+09:00",
        }

    @staticmethod
    def hidden_placeholder(index: int) -> dict:
        return {
            "inventory_index": index,
            "kind": "unavailable_placeholder",
            "visibility": "hidden",
            "video_id": None,
            "title": None,
            "position": None,
            "selected": True,
            "status": "unavailable",
            "reason": "YouTube UI reported 1 unavailable video hidden",
            "reason_source": "youtube_ui",
            "attempt_count": 0,
            "transcript_language": None,
            "language_checked": False,
            "output_path": None,
            "audit_path": None,
            "verified_at": None,
        }

    def valid_inventory(self) -> dict:
        output1, audit1 = self.write_transcript("video000001", "2026-08-23-one.md")
        output2, audit2 = self.write_transcript("video000002", "2026-08-23-two.md")
        return {
            "schema_version": 1,
            "inventory_status": "complete",
            "output_root": str(self.root),
            "scope": {
                "type": "playlist",
                "id": "PLexample",
                "url": "https://www.youtube.com/playlist?list=PLexample",
                "title": "Example",
                "selection_mode": "all",
                "displayed_total": 3,
                "displayed_total_reason": None,
                "observed_item_count": 3,
                "visible_video_count": 2,
                "hidden_unavailable_count": 1,
            },
            "status_summary": {
                "complete": 1,
                "existing_complete": 1,
                "unavailable": 1,
                "partial": 0,
                "pending": 0,
                "out_of_scope": 0,
            },
            "items": [
                self.item(1, "video000001", output1, audit1),
                self.item(2, "video000002", output2, audit2, status="existing_complete"),
                self.hidden_placeholder(3),
            ],
        }

    def write_inventory(self, inventory: dict) -> Path:
        path = self.root / ".stream-writedown" / "PLexample.inventory.json"
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(inventory, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def test_valid_inventory_verifies_recorded_files_and_audits(self):
        path = self.write_inventory(self.valid_inventory())
        result = MODULE.verify_inventory(path)
        self.assertEqual(result["item_count"], 3)
        self.assertEqual(result["verified_complete_items"], 2)

    def test_rejects_summary_and_display_count_mismatch(self):
        inventory = self.valid_inventory()
        inventory["status_summary"]["complete"] = 2
        inventory["scope"]["displayed_total"] = 80
        path = self.write_inventory(inventory)
        with self.assertRaises(MODULE.InventoryVerificationError) as raised:
            MODULE.verify_inventory(path)
        message = str(raised.exception)
        self.assertIn("status_summary.complete", message)
        self.assertIn("displayed_total=80", message)

    def test_rejects_duplicate_video_id_and_frontmatter_mismatch(self):
        inventory = self.valid_inventory()
        inventory["items"][1]["video_id"] = "video000001"
        path = self.write_inventory(inventory)
        with self.assertRaises(MODULE.InventoryVerificationError) as raised:
            MODULE.verify_inventory(path)
        message = str(raised.exception)
        self.assertIn("duplicate video_id", message)
        self.assertIn("output frontmatter video_id", message)

    def test_uses_recorded_path_without_recomputing_filename(self):
        inventory = self.valid_inventory()
        inventory["items"][0]["output_path"] = "Channel/recomputed-but-wrong.md"
        path = self.write_inventory(inventory)
        with self.assertRaisesRegex(MODULE.InventoryVerificationError, "recorded output_path does not exist"):
            MODULE.verify_inventory(path)

    def test_selected_inventory_uses_pending_and_out_of_scope_strictly(self):
        inventory = self.valid_inventory()
        inventory["inventory_status"] = "in_progress"
        inventory["scope"].update(
            {
                "selection_mode": "selected",
                "displayed_total": 2,
                "observed_item_count": 2,
                "visible_video_count": 2,
                "hidden_unavailable_count": 0,
            }
        )
        inventory["items"] = [
            {
                "inventory_index": 1,
                "kind": "video",
                "visibility": "visible",
                "video_id": "video000001",
                "title": "Selected",
                "position": 1,
                "selected": True,
                "status": "pending",
                "reason": "not_attempted",
                "reason_source": None,
                "attempt_count": 0,
                "transcript_language": None,
                "language_checked": False,
                "output_path": None,
                "audit_path": None,
                "verified_at": None,
            },
            {
                "inventory_index": 2,
                "kind": "video",
                "visibility": "visible",
                "video_id": "video000002",
                "title": "Not selected",
                "position": 2,
                "selected": False,
                "status": "out_of_scope",
                "reason": "not_selected",
                "reason_source": None,
                "attempt_count": 0,
                "transcript_language": None,
                "language_checked": False,
                "output_path": None,
                "audit_path": None,
                "verified_at": None,
            },
        ]
        inventory["status_summary"] = {
            "complete": 0,
            "existing_complete": 0,
            "unavailable": 0,
            "partial": 0,
            "pending": 1,
            "out_of_scope": 1,
        }
        path = self.write_inventory(inventory)
        MODULE.verify_inventory(path, allow_incomplete=True)
        with self.assertRaisesRegex(MODULE.InventoryVerificationError, "final verification requires"):
            MODULE.verify_inventory(path)

        invalid = deepcopy(inventory)
        invalid["items"][1].update(
            {"status": "pending", "reason": "not_attempted", "selected": False}
        )
        invalid["status_summary"].update({"pending": 2, "out_of_scope": 0})
        invalid_path = self.write_inventory(invalid)
        with self.assertRaisesRegex(MODULE.InventoryVerificationError, "pending means selected"):
            MODULE.verify_inventory(invalid_path, allow_incomplete=True)

    def test_partial_language_failure_preserves_verified_item(self):
        inventory = self.valid_inventory()
        inventory["scope"].update(
            {
                "displayed_total": 2,
                "observed_item_count": 2,
                "visible_video_count": 2,
                "hidden_unavailable_count": 0,
            }
        )
        failed = {
            "inventory_index": 2,
            "kind": "video",
            "visibility": "visible",
            "video_id": "video000003",
            "title": "English item",
            "position": 2,
            "selected": True,
            "status": "partial",
            "reason": "English translation failed after source verification",
            "reason_source": "translation",
            "attempt_count": 1,
            "transcript_language": "en",
            "language_checked": True,
            "output_path": None,
            "audit_path": None,
            "verified_at": None,
        }
        inventory["items"] = [inventory["items"][0], failed]
        inventory["status_summary"] = {
            "complete": 1,
            "existing_complete": 0,
            "unavailable": 0,
            "partial": 1,
            "pending": 0,
            "out_of_scope": 0,
        }
        path = self.write_inventory(inventory)
        result = MODULE.verify_inventory(path)
        self.assertEqual(result["verified_complete_items"], 1)
        self.assertEqual(result["status_summary"]["partial"], 1)


if __name__ == "__main__":
    unittest.main()
