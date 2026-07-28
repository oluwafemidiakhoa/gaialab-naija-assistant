from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


DEFAULT_DATASET_FILE = Path("data/v0.5/v0.5_training.jsonl")
VALID_RISK_LEVELS = {"low", "medium", "high"}
EXPECTED_ROLES = ["system", "user", "assistant"]
REQUIRED_FIELDS = {"id", "category", "risk_level", "messages"}


class ValidationError(Exception):
    """Raised when the dataset fails validation."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate the GaiaLab Naija Assistant JSONL dataset."
    )
    parser.add_argument(
        "--dataset-file",
        type=Path,
        default=DEFAULT_DATASET_FILE,
        help="Dataset JSONL file to validate.",
    )
    return parser.parse_args()


def normalize_text(text: str) -> str:
    return " ".join(text.lower().split())


def load_and_validate(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise ValidationError(f"Dataset file not found: {path}")

    records: list[dict[str, Any]] = []
    ids: list[str] = []
    prompts: list[str] = []

    with path.open("r", encoding="utf-8-sig") as file:
        for line_number, raw_line in enumerate(file, start=1):
            line = raw_line.strip()

            if not line:
                continue

            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValidationError(
                    f"Line {line_number}: invalid JSON: {exc.msg}"
                ) from exc

            if not isinstance(record, dict):
                raise ValidationError(
                    f"Line {line_number}: each line must be a JSON object."
                )

            missing_fields = REQUIRED_FIELDS - set(record)
            if missing_fields:
                raise ValidationError(
                    f"Line {line_number}: missing fields: "
                    f"{', '.join(sorted(missing_fields))}"
                )

            record_id = record["id"]
            category = record["category"]
            risk_level = record["risk_level"]
            messages = record["messages"]

            if not isinstance(record_id, str) or not record_id.strip():
                raise ValidationError(
                    f"Line {line_number}: 'id' must be a non-empty string."
                )

            if not isinstance(category, str) or not category.strip():
                raise ValidationError(
                    f"Line {line_number}: 'category' must be a non-empty string."
                )

            if risk_level not in VALID_RISK_LEVELS:
                raise ValidationError(
                    f"Line {line_number}: invalid risk_level {risk_level!r}. "
                    "Use low, medium, or high."
                )

            if not isinstance(messages, list) or len(messages) != 3:
                raise ValidationError(
                    f"Line {line_number}: 'messages' must contain exactly "
                    "three entries."
                )

            roles: list[str] = []

            for message_number, message in enumerate(messages, start=1):
                if not isinstance(message, dict):
                    raise ValidationError(
                        f"Line {line_number}, message {message_number}: "
                        "message must be an object."
                    )

                if set(message) != {"role", "content"}:
                    raise ValidationError(
                        f"Line {line_number}, message {message_number}: "
                        "message must contain only 'role' and 'content'."
                    )

                role = message["role"]
                content = message["content"]

                if not isinstance(role, str):
                    raise ValidationError(
                        f"Line {line_number}, message {message_number}: "
                        "'role' must be a string."
                    )

                if not isinstance(content, str) or not content.strip():
                    raise ValidationError(
                        f"Line {line_number}, message {message_number}: "
                        "'content' must be a non-empty string."
                    )

                roles.append(role)

            if roles != EXPECTED_ROLES:
                raise ValidationError(
                    f"Line {line_number}: roles must be exactly "
                    f"{EXPECTED_ROLES}, but found {roles}."
                )

            ids.append(record_id.strip())
            prompts.append(normalize_text(messages[1]["content"]))
            records.append(record)

    if not records:
        raise ValidationError("The dataset contains no records.")

    duplicate_ids = sorted(
        value for value, count in Counter(ids).items() if count > 1
    )
    duplicate_prompts = sorted(
        value for value, count in Counter(prompts).items() if count > 1
    )

    if duplicate_ids:
        raise ValidationError(
            "Duplicate IDs found:\n  - " + "\n  - ".join(duplicate_ids)
        )

    if duplicate_prompts:
        preview = duplicate_prompts[:10]
        message = "Duplicate prompts found:\n  - " + "\n  - ".join(preview)
        if len(duplicate_prompts) > 10:
            message += f"\n  ... and {len(duplicate_prompts) - 10} more."
        raise ValidationError(message)

    return records


def main() -> int:
    args = parse_args()

    try:
        records = load_and_validate(args.dataset_file)

        category_counts = Counter(record["category"] for record in records)
        risk_counts = Counter(record["risk_level"] for record in records)

        print()
        print("GaiaLab Dataset Validator")
        print("=" * 42)
        print(f"Dataset file      : {args.dataset_file}")
        print(f"Total examples    : {len(records)}")
        print(f"Categories        : {len(category_counts)}")
        print(f"Risk levels       : {dict(sorted(risk_counts.items()))}")
        print("Duplicate IDs     : 0")
        print("Duplicate prompts : 0")
        print("Message structure : PASSED")
        print("Required fields   : PASSED")
        print()
        print("VALIDATION PASSED")
        return 0

    except ValidationError as exc:
        print()
        print("VALIDATION FAILED")
        print("=" * 42)
        print(exc)
        return 1

    except OSError as exc:
        print()
        print("VALIDATION FAILED")
        print("=" * 42)
        print(f"File system error: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
