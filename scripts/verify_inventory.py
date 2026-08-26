#!/usr/bin/env python3
"""Verify a stream-writedown scope inventory and every completed item."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from verify_transcript import (
    VerificationError as TranscriptVerificationError,
    parse_frontmatter,
    verify as verify_transcript,
)


class InventoryVerificationError(ValueError):
    pass


STATUSES = (
    "complete",
    "existing_complete",
    "unavailable",
    "partial",
    "pending",
    "out_of_scope",
)


def nonnegative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def resolve_recorded_path(output_root: Path, value: str) -> Path:
    recorded = Path(value)
    resolved = recorded.resolve() if recorded.is_absolute() else (output_root / recorded).resolve()
    try:
        resolved.relative_to(output_root)
    except ValueError as error:
        raise InventoryVerificationError(f"Recorded path escapes output_root: {value}") from error
    return resolved


def verify_inventory(inventory_path: Path, *, allow_incomplete: bool = False) -> dict[str, Any]:
    try:
        inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise InventoryVerificationError(f"Cannot read inventory JSON: {error}") from error

    errors: list[str] = []
    if inventory.get("schema_version") != 1:
        errors.append("schema_version must be 1; migrate legacy inventory explicitly")

    output_root_value = inventory.get("output_root")
    output_root: Path | None = None
    if not isinstance(output_root_value, str) or not output_root_value:
        errors.append("output_root must be a non-empty absolute path")
    else:
        candidate_root = Path(output_root_value)
        if not candidate_root.is_absolute():
            errors.append("output_root must be absolute")
        else:
            output_root = candidate_root.resolve()
            if not output_root.is_dir():
                errors.append(f"output_root does not exist: {output_root}")

    items = inventory.get("items")
    if not isinstance(items, list):
        errors.append("items must be an array")
        items = []

    inventory_status = inventory.get("inventory_status")
    if inventory_status not in {"in_progress", "complete"}:
        errors.append("inventory_status must be in_progress or complete")
    if not allow_incomplete and inventory_status != "complete":
        errors.append("final verification requires inventory_status complete")

    scope = inventory.get("scope")
    if not isinstance(scope, dict):
        errors.append("scope must be an object")
        scope = {}
    if scope.get("type") not in {"playlist", "channel"}:
        errors.append("scope.type must be playlist or channel")
    selection_mode = scope.get("selection_mode")
    if selection_mode not in {"all", "selected"}:
        errors.append("scope.selection_mode must be all or selected")

    observed_count = scope.get("observed_item_count")
    visible_count = scope.get("visible_video_count")
    hidden_count = scope.get("hidden_unavailable_count")
    displayed_total = scope.get("displayed_total")
    for key, value in (
        ("observed_item_count", observed_count),
        ("visible_video_count", visible_count),
        ("hidden_unavailable_count", hidden_count),
    ):
        if not nonnegative_int(value):
            errors.append(f"scope.{key} must be a non-negative integer")
    if nonnegative_int(observed_count) and observed_count != len(items):
        errors.append(f"scope.observed_item_count={observed_count} but items={len(items)}")
    if nonnegative_int(visible_count) and nonnegative_int(hidden_count) and nonnegative_int(observed_count):
        if visible_count + hidden_count != observed_count:
            errors.append("visible_video_count + hidden_unavailable_count must equal observed_item_count")
    if displayed_total is None:
        reason = scope.get("displayed_total_reason")
        if not isinstance(reason, str) or not reason.strip():
            errors.append("scope.displayed_total_reason is required when displayed_total is null")
    elif not nonnegative_int(displayed_total):
        errors.append("scope.displayed_total must be a non-negative integer or null")
    elif nonnegative_int(observed_count) and displayed_total != observed_count:
        errors.append(f"scope.displayed_total={displayed_total} but observed_item_count={observed_count}")

    summary = inventory.get("status_summary")
    if not isinstance(summary, dict):
        errors.append("status_summary must be an object")
        summary = {}
    missing_statuses = [status for status in STATUSES if status not in summary]
    extra_statuses = [status for status in summary if status not in STATUSES]
    if missing_statuses:
        errors.append(f"status_summary is missing: {', '.join(missing_statuses)}")
    if extra_statuses:
        errors.append(f"status_summary has unknown states: {', '.join(extra_statuses)}")
    for status in STATUSES:
        if status in summary and not nonnegative_int(summary[status]):
            errors.append(f"status_summary.{status} must be a non-negative integer")

    actual_statuses = Counter(
        item.get("status") for item in items if isinstance(item, dict) and item.get("status") in STATUSES
    )
    if all(nonnegative_int(summary.get(status)) for status in STATUSES):
        for status in STATUSES:
            if summary[status] != actual_statuses[status]:
                errors.append(
                    f"status_summary.{status}={summary[status]} but items contain {actual_statuses[status]}"
                )
        if sum(summary[status] for status in STATUSES) != len(items):
            errors.append("status_summary total must equal items length")
        if inventory_status == "complete" and summary["pending"] != 0:
            errors.append("complete inventory cannot contain pending items")

    seen_indexes: set[int] = set()
    seen_video_ids: dict[str, int] = {}
    seen_output_paths: dict[Path, int] = {}
    seen_audit_paths: dict[Path, int] = {}
    calculated_visible = 0
    calculated_hidden = 0
    verified_items = 0

    for offset, item in enumerate(items):
        label = f"items[{offset}]"
        if not isinstance(item, dict):
            errors.append(f"{label} must be an object")
            continue

        inventory_index = item.get("inventory_index")
        if not isinstance(inventory_index, int) or isinstance(inventory_index, bool) or inventory_index < 1:
            errors.append(f"{label}.inventory_index must be a positive integer")
        elif inventory_index in seen_indexes:
            errors.append(f"duplicate inventory_index: {inventory_index}")
        else:
            seen_indexes.add(inventory_index)

        kind = item.get("kind")
        visibility = item.get("visibility")
        if kind not in {"video", "unavailable_placeholder"}:
            errors.append(f"{label}.kind must be video or unavailable_placeholder")
        if visibility not in {"visible", "hidden"}:
            errors.append(f"{label}.visibility must be visible or hidden")
        elif visibility == "visible":
            calculated_visible += 1

        video_id = item.get("video_id")
        if kind == "video" and (not isinstance(video_id, str) or not video_id):
            errors.append(f"{label}.video_id is required for video items")
        if isinstance(video_id, str) and video_id:
            if video_id in seen_video_ids:
                errors.append(
                    f"duplicate video_id {video_id!r} at items {seen_video_ids[video_id]} and {offset}"
                )
            else:
                seen_video_ids[video_id] = offset

        status = item.get("status")
        if status not in STATUSES:
            errors.append(f"{label}.status is invalid: {status!r}")
        selected = item.get("selected")
        if not isinstance(selected, bool):
            errors.append(f"{label}.selected must be boolean")
        attempts = item.get("attempt_count")
        if not nonnegative_int(attempts):
            errors.append(f"{label}.attempt_count must be a non-negative integer")

        reason = item.get("reason")
        if status == "pending":
            if selected is not True or attempts != 0 or reason != "not_attempted":
                errors.append(f"{label} pending means selected, untried, and reason=not_attempted")
        elif status == "out_of_scope":
            if selected is not False or attempts != 0 or reason != "not_selected":
                errors.append(f"{label} out_of_scope means unselected, untried, and reason=not_selected")
        elif status in {"complete", "existing_complete", "partial", "unavailable"} and selected is not True:
            errors.append(f"{label} status {status} requires selected=true")

        if selection_mode == "all" and selected is False:
            errors.append(f"{label} cannot be unselected when selection_mode=all")
        if selected is False and status != "out_of_scope":
            errors.append(f"{label} unselected item must be out_of_scope, not {status}")

        if status in {"unavailable", "partial"} and (not isinstance(reason, str) or not reason.strip()):
            errors.append(f"{label} status {status} requires a reason")
        if status == "partial" and (not nonnegative_int(attempts) or attempts < 1):
            errors.append(f"{label} partial requires attempt_count >= 1")
        if status == "complete" and (not nonnegative_int(attempts) or attempts < 1):
            errors.append(f"{label} complete requires attempt_count >= 1")
        if status == "existing_complete" and reason != "reused_existing_verified":
            errors.append(f"{label} existing_complete requires reason=reused_existing_verified")

        if kind == "unavailable_placeholder":
            if video_id is not None:
                errors.append(f"{label} unavailable placeholder video_id must be null")
            if status != "unavailable":
                errors.append(f"{label} unavailable placeholder status must be unavailable")
            if visibility == "hidden":
                calculated_hidden += 1
                if item.get("title") is not None or item.get("position") is not None:
                    errors.append(f"{label} hidden placeholder title and position must be null")
                if item.get("reason_source") != "youtube_ui":
                    errors.append(f"{label} hidden placeholder reason_source must be youtube_ui")
        elif visibility == "hidden":
            errors.append(f"{label} hidden item must be an unavailable_placeholder")

        output_value = item.get("output_path")
        audit_value = item.get("audit_path")
        if status in {"complete", "existing_complete"}:
            if item.get("language_checked") is not True:
                errors.append(f"{label} completed item requires language_checked=true")
            language = item.get("transcript_language")
            if not isinstance(language, str) or not language.strip():
                errors.append(f"{label} completed item requires transcript_language")
            if not isinstance(item.get("verified_at"), str) or not item["verified_at"].strip():
                errors.append(f"{label} completed item requires verified_at")
            if not isinstance(output_value, str) or not output_value:
                errors.append(f"{label} completed item requires recorded output_path")
            if not isinstance(audit_value, str) or not audit_value:
                errors.append(f"{label} completed item requires recorded audit_path")

            if output_root is not None and isinstance(output_value, str) and output_value:
                try:
                    output_path = resolve_recorded_path(output_root, output_value)
                    if output_path in seen_output_paths:
                        errors.append(
                            f"recorded output_path reused by items {seen_output_paths[output_path]} and {offset}: {output_value}"
                        )
                    else:
                        seen_output_paths[output_path] = offset
                    if not output_path.is_file():
                        errors.append(f"{label} recorded output_path does not exist: {output_value}")
                except InventoryVerificationError as error:
                    errors.append(f"{label} {error}")
                    output_path = None
            else:
                output_path = None

            if output_root is not None and isinstance(audit_value, str) and audit_value:
                try:
                    audit_path = resolve_recorded_path(output_root, audit_value)
                    if audit_path in seen_audit_paths:
                        errors.append(
                            f"recorded audit_path reused by items {seen_audit_paths[audit_path]} and {offset}: {audit_value}"
                        )
                    else:
                        seen_audit_paths[audit_path] = offset
                    if not audit_path.is_file():
                        errors.append(f"{label} recorded audit_path does not exist: {audit_value}")
                except InventoryVerificationError as error:
                    errors.append(f"{label} {error}")
                    audit_path = None
            else:
                audit_path = None

            if output_path is not None and output_path.is_file() and isinstance(video_id, str):
                try:
                    frontmatter = parse_frontmatter(output_path.read_text(encoding="utf-8"))
                    if frontmatter.get("video_id") != video_id:
                        errors.append(
                            f"{label} output frontmatter video_id={frontmatter.get('video_id')!r} "
                            f"but inventory video_id={video_id!r}"
                        )
                except (OSError, TranscriptVerificationError) as error:
                    errors.append(f"{label} cannot inspect output frontmatter: {error}")

            if output_path is not None and audit_path is not None and output_path.is_file() and audit_path.is_file():
                try:
                    verify_transcript(audit_path, output_path)
                    verified_items += 1
                except (OSError, TranscriptVerificationError) as error:
                    errors.append(f"{label} transcript verification failed: {error}")
        else:
            for field_name, field_value in (("output_path", output_value), ("audit_path", audit_value)):
                if field_value is not None and (not isinstance(field_value, str) or not field_value):
                    errors.append(f"{label}.{field_name} must be a non-empty string or null")
                elif output_root is not None and isinstance(field_value, str):
                    try:
                        recorded_path = resolve_recorded_path(output_root, field_value)
                        if not recorded_path.is_file():
                            errors.append(f"{label} recorded {field_name} does not exist: {field_value}")
                    except InventoryVerificationError as error:
                        errors.append(f"{label} {error}")

    if nonnegative_int(visible_count) and visible_count != calculated_visible:
        errors.append(f"scope.visible_video_count={visible_count} but items contain {calculated_visible} visible entries")
    if nonnegative_int(hidden_count) and hidden_count != calculated_hidden:
        errors.append(
            f"scope.hidden_unavailable_count={hidden_count} but items contain {calculated_hidden} hidden placeholders"
        )

    if errors:
        raise InventoryVerificationError("Inventory verification failed:\n- " + "\n- ".join(errors))

    return {
        "scope_type": scope["type"],
        "scope_id": scope.get("id"),
        "inventory_status": inventory_status,
        "item_count": len(items),
        "status_summary": {status: summary[status] for status in STATUSES},
        "verified_complete_items": verified_items,
        "status": "ok",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inventory", type=Path)
    parser.add_argument("--allow-incomplete", action="store_true")
    args = parser.parse_args()

    try:
        result = verify_inventory(args.inventory, allow_incomplete=args.allow_incomplete)
    except (OSError, InventoryVerificationError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
