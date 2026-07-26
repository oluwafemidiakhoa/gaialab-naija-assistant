from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from typing import Any


DEFAULT_V02_PATH = Path(
    "data/v0.2/prepared/gaialab_naija_v0.2_combined.jsonl"
)

DEFAULT_V03_APPROVED_PATH = Path(
    "data/v0.3/approved/gaialab_naija_v0.3_approved.jsonl"
)

DEFAULT_OUTPUT_DIR = Path(
    "data/v0.3/prepared"
)


def normalize_text(value: Any) -> str:
    """
    Normalize text for duplicate comparison.

    The normalization:
    - converts the value to a string
    - removes leading and trailing spaces
    - converts text to lowercase
    - collapses repeated whitespace
    """
    if value is None:
        return ""

    return " ".join(str(value).strip().lower().split())


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    """
    Load a JSONL file and return a list of JSON objects.
    """
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

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
                    f"Invalid JSON in {path} on line "
                    f"{line_number}: {exc}"
                ) from exc

            if not isinstance(record, dict):
                raise ValueError(
                    f"Line {line_number} in {path} "
                    "must contain a JSON object."
                )

            records.append(record)

    return records


def record_key(record: dict[str, Any]) -> str:
    """
    Create a stable duplicate-detection key.

    Supported schemas:

    v0.2:
        instruction
        input
        output

    v0.3:
        messages
    """

    messages = record.get("messages")

    if isinstance(messages, list) and messages:
        normalized_messages: list[dict[str, str]] = []

        for message in messages:
            if not isinstance(message, dict):
                continue

            role = normalize_text(message.get("role"))
            content = normalize_text(message.get("content"))

            if role or content:
                normalized_messages.append(
                    {
                        "role": role,
                        "content": content,
                    }
                )

        if normalized_messages:
            return json.dumps(
                {
                    "schema": "messages",
                    "messages": normalized_messages,
                },
                sort_keys=True,
                ensure_ascii=False,
            )

    instruction = normalize_text(record.get("instruction"))
    input_text = normalize_text(record.get("input"))
    output_text = normalize_text(record.get("output"))

    if instruction or input_text or output_text:
        return json.dumps(
            {
                "schema": "instruction_input_output",
                "instruction": instruction,
                "input": input_text,
                "output": output_text,
            },
            sort_keys=True,
            ensure_ascii=False,
        )

    record_id = normalize_text(record.get("id"))

    if record_id:
        return json.dumps(
            {
                "schema": "record_id",
                "id": record_id,
            },
            sort_keys=True,
            ensure_ascii=False,
        )

    return json.dumps(
        record,
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    )


def remove_duplicates(
    records: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    """
    Remove duplicate records while preserving their original order.
    """
    unique_records: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    duplicate_count = 0

    for record in records:
        key = record_key(record)

        if key in seen_keys:
            duplicate_count += 1
            continue

        seen_keys.add(key)
        unique_records.append(record)

    return unique_records, duplicate_count


def validate_record(record: dict[str, Any]) -> list[str]:
    """
    Validate that a record uses either the v0.2 or v0.3 schema.
    """
    errors: list[str] = []

    messages = record.get("messages")

    if isinstance(messages, list) and messages:
        valid_messages = [
            message
            for message in messages
            if isinstance(message, dict)
            and normalize_text(message.get("role"))
            and normalize_text(message.get("content"))
        ]

        if not valid_messages:
            errors.append(
                "messages does not contain valid role/content entries"
            )

        return errors

    required_v02_fields = {
        "instruction",
        "input",
        "output",
    }

    missing_fields = [
        field
        for field in required_v02_fields
        if field not in record
    ]

    if missing_fields:
        errors.append(
            "record does not match v0.2 or v0.3 schema; "
            f"missing fields: {', '.join(sorted(missing_fields))}"
        )

    return errors


def validate_records(
    records: list[dict[str, Any]],
    source_name: str,
) -> None:
    """
    Validate all records before writing output files.
    """
    validation_errors: list[str] = []

    for index, record in enumerate(records, start=1):
        errors = validate_record(record)

        for error in errors:
            validation_errors.append(
                f"{source_name}, record {index}: {error}"
            )

    if validation_errors:
        preview = "\n".join(validation_errors[:10])

        if len(validation_errors) > 10:
            preview += (
                f"\n... and "
                f"{len(validation_errors) - 10} more errors"
            )

        raise ValueError(
            f"Dataset validation failed:\n{preview}"
        )


def write_jsonl(
    path: Path,
    records: list[dict[str, Any]],
) -> None:
    """
    Write records to a JSONL file.
    """
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with path.open(
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


def calculate_validation_count(
    total_records: int,
    validation_ratio: float,
) -> int:
    """
    Calculate the validation record count.

    The function always leaves at least one training record
    when the dataset contains more than one record.
    """
    if total_records < 2:
        raise ValueError(
            "At least two records are required "
            "to create train and validation splits."
        )

    validation_count = round(
        total_records * validation_ratio
    )

    validation_count = max(
        1,
        validation_count,
    )

    validation_count = min(
        validation_count,
        total_records - 1,
    )

    return validation_count


def prepare_dataset(
    v02_path: Path,
    v03_approved_path: Path,
    output_dir: Path,
    validation_ratio: float,
    seed: int,
) -> None:
    """
    Merge v0.2 with approved v0.3 records, remove duplicates,
    shuffle deterministically, and produce train/validation files.
    """
    v02_records = load_jsonl(v02_path)
    v03_records = load_jsonl(v03_approved_path)

    validate_records(
        v02_records,
        source_name=str(v02_path),
    )

    validate_records(
        v03_records,
        source_name=str(v03_approved_path),
    )

    all_records = v02_records + v03_records

    unique_records, duplicate_count = remove_duplicates(
        all_records
    )

    random_generator = random.Random(seed)

    shuffled_records = unique_records.copy()
    random_generator.shuffle(shuffled_records)

    validation_count = calculate_validation_count(
        total_records=len(shuffled_records),
        validation_ratio=validation_ratio,
    )

    validation_records = shuffled_records[
        :validation_count
    ]

    training_records = shuffled_records[
        validation_count:
    ]

    combined_path = (
        output_dir
        / "gaialab_naija_v0.3_combined.jsonl"
    )

    training_path = (
        output_dir
        / "gaialab_naija_v0.3_train.jsonl"
    )

    validation_path = (
        output_dir
        / "gaialab_naija_v0.3_validation.jsonl"
    )

    write_jsonl(
        combined_path,
        shuffled_records,
    )

    write_jsonl(
        training_path,
        training_records,
    )

    write_jsonl(
        validation_path,
        validation_records,
    )

    print(
        f"v0.2 source records: {len(v02_records)}"
    )
    print(
        f"v0.3 approved records: {len(v03_records)}"
    )
    print(
        f"Duplicates removed: {duplicate_count}"
    )
    print(
        f"Combined unique records: "
        f"{len(shuffled_records)}"
    )
    print(
        f"Training records: {len(training_records)}"
    )
    print(
        f"Validation records: "
        f"{len(validation_records)}"
    )
    print(
        f"Output directory: {output_dir}"
    )


def parse_arguments() -> argparse.Namespace:
    """
    Parse command-line arguments.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Prepare the GaiaLab Naija v0.3 "
            "training and validation datasets."
        )
    )

    parser.add_argument(
        "--v02",
        type=Path,
        default=DEFAULT_V02_PATH,
        help=(
            "Path to the v0.2 combined JSONL dataset."
        ),
    )

    parser.add_argument(
        "--v03-approved",
        type=Path,
        default=DEFAULT_V03_APPROVED_PATH,
        help=(
            "Path to the approved v0.3 JSONL dataset."
        ),
    )

    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=(
            "Directory where prepared datasets "
            "will be written."
        ),
    )

    parser.add_argument(
        "--validation-ratio",
        type=float,
        default=0.10,
        help=(
            "Fraction of records assigned to validation. "
            "Default: 0.10"
        ),
    )

    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help=(
            "Random seed used for deterministic shuffling. "
            "Default: 42"
        ),
    )

    return parser.parse_args()


def main() -> int:
    """
    Run the dataset preparation workflow.
    """
    args = parse_arguments()

    if not 0 < args.validation_ratio < 1:
        print(
            "Dataset preparation failed: "
            "--validation-ratio must be greater "
            "than 0 and less than 1."
        )
        return 1

    try:
        prepare_dataset(
            v02_path=args.v02,
            v03_approved_path=args.v03_approved,
            output_dir=args.output_dir,
            validation_ratio=args.validation_ratio,
            seed=args.seed,
        )
    except (
        FileNotFoundError,
        ValueError,
        OSError,
    ) as exc:
        print(
            f"Dataset preparation failed: {exc}"
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())