#!/usr/bin/env python3
"""Verify a streame-writedown audit record against its final Markdown."""

from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from pathlib import Path
from typing import Any


class VerificationError(ValueError):
    pass


TIMESTAMP_RE = re.compile(r"^(?:(\d+):)?([0-5]?\d):([0-5]\d)(?:[.,]\d+)?$")
TRANSCRIPT_HEADING_RE = re.compile(r"^## 文字起こし(?:（[^）]+訳）)?\s*$")
SECTION_HEADING_RE = re.compile(r"^###\s+\S", re.MULTILINE)
MARKDOWN_ESCAPE_RE = re.compile(r"\\([\\`*_[\]#<>+\-])")


def canonical_text(value: str) -> str:
    """Remove layout whitespace while preserving every non-whitespace character."""
    return "".join(char for char in value if not char.isspace())


def timestamp_seconds(value: str) -> float:
    match = TIMESTAMP_RE.fullmatch(value.strip())
    if not match:
        raise VerificationError(f"Invalid timestamp: {value!r}")
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2))
    seconds = float(match.group(3).replace(",", "."))
    return hours * 3600 + minutes * 60 + seconds


def parse_frontmatter(markdown: str) -> dict[str, Any]:
    normalized = markdown.replace("\r\n", "\n")
    if not normalized.startswith("---\n"):
        raise VerificationError("Markdown frontmatter is missing")
    end = normalized.find("\n---\n", 4)
    if end < 0:
        raise VerificationError("Markdown frontmatter is not closed")

    result: dict[str, Any] = {}
    for raw_line in normalized[4:end].splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        if ":" not in raw_line:
            continue
        key, raw_value = raw_line.split(":", 1)
        key = key.strip()
        value = raw_value.strip()
        if not key or value == "":
            continue
        if value == "null":
            result[key] = None
        elif value == "true":
            result[key] = True
        elif value == "false":
            result[key] = False
        elif value.startswith('"') and value.endswith('"'):
            try:
                result[key] = json.loads(value)
            except json.JSONDecodeError as error:
                raise VerificationError(f"Invalid quoted YAML scalar for {key}") from error
        elif value.startswith("'") and value.endswith("'"):
            result[key] = value[1:-1].replace("''", "'")
        else:
            result[key] = value
    return result


def extract_transcript_body(markdown: str) -> str:
    lines = markdown.replace("\r\n", "\n").splitlines()
    start: int | None = None
    for index, line in enumerate(lines):
        if TRANSCRIPT_HEADING_RE.fullmatch(line):
            start = index + 1
            break
    if start is None:
        raise VerificationError("Transcript heading is missing")

    end = len(lines)
    for index in range(start, len(lines)):
        if lines[index].startswith("## "):
            end = index
            break
    return "\n".join(lines[start:end]).strip()


def visible_body_text(body_markdown: str) -> str:
    content_lines: list[str] = []
    for raw_line in body_markdown.replace("\r\n", "\n").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("### "):
            continue
        content_lines.append(MARKDOWN_ESCAPE_RE.sub(r"\1", line))
    return "".join(content_lines)


def count_paragraphs(body_markdown: str) -> int:
    blocks = re.split(r"\n\s*\n", body_markdown.replace("\r\n", "\n").strip())
    return sum(1 for block in blocks if block.strip() and not block.lstrip().startswith("### "))


def require_true(mapping: dict[str, Any], key: str, label: str) -> None:
    if mapping.get(key) is not True:
        raise VerificationError(f"{label}.{key} must be true")


def verify(audit_path: Path, markdown_path: Path) -> dict[str, Any]:
    try:
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise VerificationError(f"Cannot read audit JSON: {error}") from error
    markdown = markdown_path.read_text(encoding="utf-8")
    frontmatter = parse_frontmatter(markdown)

    if audit.get("schema_version") != 1:
        raise VerificationError("audit.schema_version must be 1")
    video_id = audit.get("video_id")
    if not isinstance(video_id, str) or not video_id:
        raise VerificationError("audit.video_id is missing")
    if frontmatter.get("video_id") != video_id:
        raise VerificationError("video_id differs between audit and Markdown")

    cues = audit.get("cues")
    if not isinstance(cues, list) or not cues:
        raise VerificationError("audit.cues must contain at least one cue")
    source_parts: list[str] = []
    previous_time = -1.0
    for index, cue in enumerate(cues):
        if not isinstance(cue, dict):
            raise VerificationError(f"Cue {index} is not an object")
        timestamp = cue.get("timestamp")
        text = cue.get("text")
        if not isinstance(timestamp, str) or not isinstance(text, str):
            raise VerificationError(f"Cue {index} requires string timestamp and text")
        current_time = timestamp_seconds(timestamp)
        if current_time < previous_time:
            raise VerificationError(f"Timestamp goes backward at cue {index}")
        previous_time = current_time
        source_parts.append(text)

    preproofread = audit.get("preproofread_body_markdown")
    proofread = audit.get("proofread_body_markdown")
    if not isinstance(preproofread, str) or not preproofread.strip():
        raise VerificationError("audit.preproofread_body_markdown is missing")
    if not isinstance(proofread, str) or not proofread.strip():
        raise VerificationError("audit.proofread_body_markdown is missing")

    source_canonical = canonical_text("".join(source_parts))
    preproofread_canonical = canonical_text(visible_body_text(preproofread))
    if source_canonical != preproofread_canonical:
        matcher = difflib.SequenceMatcher(None, source_canonical, preproofread_canonical)
        raise VerificationError(
            "Pre-proofread body does not losslessly match source cues "
            f"(ratio={matcher.ratio():.6f}, source_chars={len(source_canonical)}, "
            f"body_chars={len(preproofread_canonical)})"
        )

    checks = audit.get("checks")
    if not isinstance(checks, dict):
        raise VerificationError("audit.checks is missing")
    for key in (
        "source_complete",
        "source_matches_preproofread",
        "proofread_no_omissions",
        "proofread_meaning_preserved",
    ):
        require_true(checks, key, "checks")

    required_frontmatter = {
        "transcript_status": "complete",
        "transcript_layout": "content_sections",
        "proofread": True,
    }
    for key, expected in required_frontmatter.items():
        if frontmatter.get(key) != expected:
            raise VerificationError(f"frontmatter {key} must be {expected!r}")

    audit_reference = frontmatter.get("proofread_audit")
    if not isinstance(audit_reference, str) or not audit_reference:
        raise VerificationError("frontmatter proofread_audit is missing")
    referenced_path = (markdown_path.parent / audit_reference).resolve()
    if referenced_path != audit_path.resolve():
        raise VerificationError("frontmatter proofread_audit does not point to the audit file")

    translation = audit.get("translation")
    if not isinstance(translation, dict):
        raise VerificationError("audit.translation is missing")
    translated = translation.get("enabled") is True
    source_language = audit.get("source_language")
    if not isinstance(source_language, str) or not source_language.strip():
        raise VerificationError("audit.source_language is missing")
    normalized_language = source_language.strip().lower().replace("_", "-")
    is_english = normalized_language.startswith("english") or normalized_language == "en" or normalized_language.startswith("en-")
    if is_english and not translated:
        raise VerificationError("English transcripts must include a translation")
    if frontmatter.get("translated") is not translated:
        raise VerificationError("frontmatter translated differs from audit")

    if translated:
        target_language = translation.get("target_language")
        translated_body = translation.get("body_markdown")
        review = translation.get("review")
        if not isinstance(target_language, str) or not target_language:
            raise VerificationError("translation.target_language is missing")
        if frontmatter.get("translation_target_language") != target_language:
            raise VerificationError("translation target differs between audit and Markdown")
        if not isinstance(translated_body, str) or not translated_body.strip():
            raise VerificationError("translation.body_markdown is missing")
        if not isinstance(review, dict):
            raise VerificationError("translation.review is missing")
        for key in ("paragraphs_aligned", "no_omissions_or_duplicates", "meaning_preserved"):
            require_true(review, key, "translation.review")
        expected_final_body = translated_body
    else:
        if frontmatter.get("translation_target_language") is not None:
            raise VerificationError("translation_target_language must be null when not translated")
        expected_final_body = proofread

    actual_final_body = extract_transcript_body(markdown)
    if actual_final_body.replace("\r\n", "\n").strip() != expected_final_body.replace("\r\n", "\n").strip():
        raise VerificationError("Final Markdown transcript body differs from the audited final body")

    section_count = len(SECTION_HEADING_RE.findall(expected_final_body.replace("\r\n", "\n")))
    paragraph_count = count_paragraphs(expected_final_body)
    if section_count < 1 or paragraph_count < 1:
        raise VerificationError("Content-section layout requires at least one section and paragraph")

    proofread_matcher = difflib.SequenceMatcher(
        None,
        visible_body_text(preproofread),
        visible_body_text(proofread),
    )
    changed_blocks = sum(1 for opcode, *_ in proofread_matcher.get_opcodes() if opcode != "equal")

    return {
        "video_id": video_id,
        "cue_count": len(cues),
        "source_characters_without_whitespace": len(source_canonical),
        "sections": section_count,
        "paragraphs": paragraph_count,
        "proofread_changed_blocks": changed_blocks,
        "translated": translated,
        "status": "ok",
    }


def print_diff(audit_path: Path) -> None:
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    before = audit["preproofread_body_markdown"].replace("\r\n", "\n").splitlines()
    after = audit["proofread_body_markdown"].replace("\r\n", "\n").splitlines()
    print("\nProofreading diff:")
    print("\n".join(difflib.unified_diff(before, after, "preproofread", "proofread", lineterm="")))
    translation = audit.get("translation", {})
    if translation.get("enabled") is True:
        translated = translation["body_markdown"].replace("\r\n", "\n").splitlines()
        print("\nTranslation diff (source to target):")
        print("\n".join(difflib.unified_diff(after, translated, "proofread-source", "translation", lineterm="")))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audit", type=Path)
    parser.add_argument("markdown", type=Path)
    parser.add_argument("--show-diff", action="store_true")
    args = parser.parse_args()

    try:
        result = verify(args.audit, args.markdown)
    except (OSError, VerificationError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.show_diff:
        print_diff(args.audit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
