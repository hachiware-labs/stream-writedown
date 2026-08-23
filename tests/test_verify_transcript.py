from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "verify_transcript.py"
SPEC = importlib.util.spec_from_file_location("verify_transcript", SCRIPT_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class VerifyTranscriptTests(unittest.TestCase):
    def write_case(self, audit: dict, body: str, *, translated: bool, target: str | None):
        temp = tempfile.TemporaryDirectory()
        root = Path(temp.name)
        audit_dir = root / ".streame-writedown"
        audit_dir.mkdir()
        audit_path = audit_dir / "abcdefghijk.audit.json"
        markdown_path = root / "2026-08-23-title.md"
        audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
        target_value = "null" if target is None else json.dumps(target)
        markdown_path.write_text(
            "\n".join(
                [
                    "---",
                    'video_id: "abcdefghijk"',
                    'transcript_status: "complete"',
                    'transcript_layout: "content_sections"',
                    "proofread: true",
                    'proofread_audit: ".streame-writedown/abcdefghijk.audit.json"',
                    f"translated: {'true' if translated else 'false'}",
                    f"translation_target_language: {target_value}",
                    "---",
                    "",
                    "# Title",
                    "",
                    "## 文字起こし（日本語訳）" if translated else "## 文字起こし",
                    "",
                    body,
                    "",
                ]
            ),
            encoding="utf-8",
        )
        self.addCleanup(temp.cleanup)
        return audit_path, markdown_path

    @staticmethod
    def base_audit() -> dict:
        return {
            "schema_version": 1,
            "video_id": "abcdefghijk",
            "source_route": "computer_use",
            "source_export_path": None,
            "source_language": "ja",
            "cues": [
                {"timestamp": "00:00", "text": "こんにちわ"},
                {"timestamp": "00:03", "text": "今日はテストです"},
            ],
            "preproofread_body_markdown": "### 挨拶\n\nこんにちわ今日はテストです",
            "proofread_body_markdown": "### 挨拶\n\nこんにちは。今日はテストです。",
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

    def test_valid_proofread_japanese(self):
        audit = self.base_audit()
        audit_path, markdown_path = self.write_case(
            audit,
            audit["proofread_body_markdown"],
            translated=False,
            target=None,
        )
        result = MODULE.verify(audit_path, markdown_path)
        self.assertEqual(result["cue_count"], 2)
        self.assertFalse(result["translated"])

    def test_valid_english_to_japanese_translation(self):
        audit = self.base_audit()
        audit.update(
            {
                "source_route": "chrome_export",
                "source_language": "en",
                "cues": [
                    {"timestamp": "00:00", "text": "This is a "},
                    {"timestamp": "00:02", "text": "test"},
                ],
                "preproofread_body_markdown": "### Test\n\nThis is a test",
                "proofread_body_markdown": "### Test\n\nThis is a test.",
                "translation": {
                    "enabled": True,
                    "target_language": "ja",
                    "body_markdown": "### テスト\n\nこれはテストです。",
                    "review": {
                        "paragraphs_aligned": True,
                        "no_omissions_or_duplicates": True,
                        "meaning_preserved": True,
                    },
                },
            }
        )
        audit_path, markdown_path = self.write_case(
            audit,
            audit["translation"]["body_markdown"],
            translated=True,
            target="ja",
        )
        result = MODULE.verify(audit_path, markdown_path)
        self.assertTrue(result["translated"])

    def test_rejects_loss_during_sectioning(self):
        audit = self.base_audit()
        audit["preproofread_body_markdown"] = "### 挨拶\n\nこんにちわ"
        audit_path, markdown_path = self.write_case(
            audit,
            audit["proofread_body_markdown"],
            translated=False,
            target=None,
        )
        with self.assertRaisesRegex(MODULE.VerificationError, "losslessly match"):
            MODULE.verify(audit_path, markdown_path)

    def test_rejects_untranslated_english(self):
        audit = self.base_audit()
        audit["source_language"] = "en"
        audit_path, markdown_path = self.write_case(
            audit,
            audit["proofread_body_markdown"],
            translated=False,
            target=None,
        )
        with self.assertRaisesRegex(MODULE.VerificationError, "must include a translation"):
            MODULE.verify(audit_path, markdown_path)


if __name__ == "__main__":
    unittest.main()
