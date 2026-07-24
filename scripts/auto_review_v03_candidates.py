"""
Automatically review GaiaLab v0.3 candidate records using strict rules.

This script does not replace human linguistic review.
It auto-approves only records that pass all safety and structure checks.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


DEFAULT_INPUT = Path(
    "data/v0.3/candidates/gaialab_naija_v0.3_candidates.jsonl"
)

DEFAULT_OUTPUT = Path(
    "data/v0.3/candidates/gaialab_naija_v0.3_candidates_reviewed.jsonl"
)


REQUIRED_FIELDS = {
    "id",
    "category",
    "task",
    "source_language",
    "target_language",
    "difficulty",
    "failure_tags",
    "messages",
    "status",
    "approved_for_training",
    "review_notes",
}


HIGH_RISK_TAGS = {
    "payment_safety",
    "allergy_warning",
    "safety_preservation",
    "record_integrity",
}


PIDGIN_TARGETS = {
    "nigerian_pidgin",
}


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"Input file not found: {path}")

    records: list[dict[str, Any]] = []

    with path.open("r", encoding="utf-8") as file:
        for line_number, raw_line in enumerate(file, start=1):
            line = raw_line.strip()

            if not line:
                continue

            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Invalid JSON on line {line_number}: {exc}"
                ) from exc

            if not isinstance(record, dict):
                raise ValueError(
                    f"Line {line_number} must contain a JSON object."
                )

            records.append(record)

    return records


def get_messages(record: dict[str, Any]) -> list[dict[str, str]]:
    messages = record.get("messages")

    if not isinstance(messages, list):
        return []

    return [
        message
        for message in messages
        if isinstance(message, dict)
    ]


def structural_errors(record: dict[str, Any]) -> list[str]:
    errors: list[str] = []

    missing = REQUIRED_FIELDS - record.keys()

    if missing:
        errors.append(
            "missing fields: " + ", ".join(sorted(missing))
        )

    messages = get_messages(record)

    if len(messages) != 3:
        errors.append("messages must contain exactly three entries")
        return errors

    expected_roles = ["system", "user", "assistant"]
    actual_roles = [message.get("role") for message in messages]

    if actual_roles != expected_roles:
        errors.append(f"invalid roles: {actual_roles}")

    for message in messages:
        content = message.get("content")

        if not isinstance(content, str) or not content.strip():
            errors.append(
                f"empty content for role {message.get('role')}"
            )

    return errors


def passes_basic_quality(record: dict[str, Any]) -> tuple[bool, str]:
    errors = structural_errors(record)

    if errors:
        return False, "; ".join(errors)

    messages = get_messages(record)

    user_text = messages[1]["content"].strip()
    assistant_text = messages[2]["content"].strip()

    if len(assistant_text.split()) < 5:
        return False, "assistant response is too short"

    if len(assistant_text.split()) > 160:
        return False, "assistant response is too long"

    if user_text.lower() == assistant_text.lower():
        return False, "response repeats the prompt"

    if assistant_text.count("!!!") > 0:
        return False, "excessive punctuation"

    if assistant_text.count("[") > 2:
        return False, "too many unresolved placeholders"

    return True, "basic quality checks passed"


def requires_manual_review(record: dict[str, Any]) -> tuple[bool, str]:
    failure_tags = set(record.get("failure_tags", []))
    target_language = record.get("target_language", "")

    if target_language in PIDGIN_TARGETS:
        return True, "Nigerian Pidgin naturalness requires human review"

    if failure_tags & HIGH_RISK_TAGS:
        return True, "safety-sensitive content requires human review"

    return False, ""


def auto_review_record(record: dict[str, Any]) -> dict[str, Any]:
    reviewed = dict(record)

    passed, reason = passes_basic_quality(reviewed)

    if not passed:
        reviewed["status"] = "needs_revision"
        reviewed["approved_for_training"] = False
        reviewed["review_notes"] = (
            f"Automated review failed: {reason}."
        )
        return reviewed

    manual_required, manual_reason = requires_manual_review(reviewed)

    if manual_required:
        reviewed["status"] = "needs_human_review"
        reviewed["approved_for_training"] = False
        reviewed["review_notes"] = (
            f"Automated checks passed. {manual_reason}."
        )
        return reviewed

    reviewed["status"] = "approved"
    reviewed["approved_for_training"] = True
    reviewed["review_notes"] = (
        "Automated checks passed for structure, completeness, "
        "length, and response quality. Human spot-check recommended."
    )

    return reviewed


def write_jsonl(
    records: list[dict[str, Any]],
    path: Path,
    overwrite: bool,
) -> None:
    if path.exists() and not overwrite:
        raise FileExistsError(
            f"Output already exists: {path}. "
            "Use --overwrite to replace it."
        )

    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open(
        "w",
        encoding="utf-8",
        newline="\n",
    ) as file:
        for record in records:
            file.write(
                json.dumps(record, ensure_ascii=False) + "\n"
            )


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Automatically review GaiaLab v0.3 candidates."
    )

    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT,
    )

    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
    )

    parser.add_argument(
        "--overwrite",
        action="store_true",
    )

    return parser.parse_args()


def main() -> int:
    args = parse_arguments()

    try:
        records = load_jsonl(args.input)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Auto-review failed: {exc}")
        return 1

    reviewed_records = [
        auto_review_record(record)
        for record in records
    ]

    try:
        write_jsonl(
            reviewed_records,
            args.output,
            overwrite=args.overwrite,
        )
    except FileExistsError as exc:
        print(f"Auto-review failed: {exc}")
        return 1

    approved = sum(
        1
        for record in reviewed_records
        if record["status"] == "approved"
    )

    human_review = sum(
        1
        for record in reviewed_records
        if record["status"] == "needs_human_review"
    )

    revision = sum(
        1
        for record in reviewed_records
        if record["status"] == "needs_revision"
    )

    print(f"Total records: {len(reviewed_records)}")
    print(f"Auto-approved: {approved}")
    print(f"Needs human review: {human_review}")
    print(f"Needs revision: {revision}")
    print(f"Output: {args.output}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())