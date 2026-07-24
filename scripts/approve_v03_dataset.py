"""
Extract approved GaiaLab Naija Assistant v0.3 records.

Input:
    data/v0.3/candidates/gaialab_naija_v0.3_candidates.jsonl

Output:
    data/v0.3/approved/gaialab_naija_v0.3_approved.jsonl

A record is exported only when:

    status == "approved"

and:

    approved_for_training is True
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
    "data/v0.3/approved/gaialab_naija_v0.3_approved.jsonl"
)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    """Load and validate a JSONL file."""

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


def is_approved(record: dict[str, Any]) -> bool:
    """Return True only for fully approved training records."""

    return (
        record.get("status") == "approved"
        and record.get("approved_for_training") is True
    )


def validate_approved_record(record: dict[str, Any]) -> list[str]:
    """Validate an approved record before export."""

    errors: list[str] = []

    required_fields = {
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

    missing_fields = required_fields - record.keys()

    if missing_fields:
        errors.append(
            "Missing required fields: "
            + ", ".join(sorted(missing_fields))
        )

    if record.get("status") != "approved":
        errors.append("status must be approved")

    if record.get("approved_for_training") is not True:
        errors.append("approved_for_training must be true")

    messages = record.get("messages")

    if not isinstance(messages, list) or len(messages) != 3:
        errors.append(
            "messages must contain exactly three entries"
        )
        return errors

    expected_roles = ["system", "user", "assistant"]

    actual_roles = [
        message.get("role")
        for message in messages
        if isinstance(message, dict)
    ]

    if actual_roles != expected_roles:
        errors.append(
            f"Invalid message roles: {actual_roles}"
        )

    for message in messages:
        if not isinstance(message, dict):
            errors.append("Every message must be an object")
            continue

        content = message.get("content")

        if not isinstance(content, str) or not content.strip():
            errors.append(
                f"Empty content for role: {message.get('role')}"
            )

    return errors


def write_jsonl(
    records: list[dict[str, Any]],
    output_path: Path,
    overwrite: bool,
) -> None:
    """Write approved records to JSONL."""

    if output_path.exists() and not overwrite:
        raise FileExistsError(
            f"Output already exists: {output_path}. "
            "Use --overwrite to replace it."
        )

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with output_path.open(
        "w",
        encoding="utf-8",
        newline="\n",
    ) as file:
        for record in records:
            file.write(
                json.dumps(
                    record,
                    ensure_ascii=False,
                )
                + "\n"
            )


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Extract fully approved GaiaLab v0.3 records "
            "into a training-ready JSONL file."
        )
    )

    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT,
        help="Candidate JSONL file.",
    )

    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Approved JSONL output file.",
    )

    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace the output file if it already exists.",
    )

    return parser.parse_args()


def main() -> int:
    args = parse_arguments()

    try:
        candidate_records = load_jsonl(args.input)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Approval failed: {exc}")
        return 1

    approved_records = [
        record
        for record in candidate_records
        if is_approved(record)
    ]

    validation_errors: list[str] = []

    for record in approved_records:
        record_id = record.get("id", "unknown")

        for error in validate_approved_record(record):
            validation_errors.append(
                f"{record_id}: {error}"
            )

    if validation_errors:
        print("Approval failed because approved records are invalid:")

        for error in validation_errors:
            print(f"- {error}")

        return 1

    try:
        write_jsonl(
            approved_records,
            args.output,
            overwrite=args.overwrite,
        )
    except FileExistsError as exc:
        print(f"Approval failed: {exc}")
        return 1

    total = len(candidate_records)
    approved = len(approved_records)
    excluded = total - approved

    print(f"Candidate records: {total}")
    print(f"Approved records: {approved}")
    print(f"Excluded records: {excluded}")
    print(f"Output: {args.output}")

    if approved == 0:
        print(
            "Warning: no records were approved for training."
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())