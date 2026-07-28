from __future__ import annotations

import argparse
import json
import shutil
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_BASE_FILE = Path("data/v0.4/v0.4_training.jsonl")
DEFAULT_NEW_FILE = Path("data/v0.5/v0.5_new_examples.jsonl")
DEFAULT_OUTPUT_FILE = Path("data/v0.5/v0.5_training.jsonl")
DEFAULT_MANIFEST_FILE = Path("data/v0.5/dataset_manifest.json")
DEFAULT_BACKUP_DIR = Path("data/v0.5/backups")

REQUIRED_TOP_LEVEL_FIELDS = {"id", "category", "risk_level", "messages"}
VALID_RISK_LEVELS = {"low", "medium", "high"}
EXPECTED_ROLES = ["system", "user", "assistant"]


class DatasetError(Exception):
    """Raised when the dataset is invalid."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build GaiaLab Naija Assistant v0.5 by merging the stable v0.4 "
            "training dataset with new v0.5 examples."
        )
    )
    parser.add_argument("--base-file", type=Path, default=DEFAULT_BASE_FILE)
    parser.add_argument("--new-file", type=Path, default=DEFAULT_NEW_FILE)
    parser.add_argument("--output-file", type=Path, default=DEFAULT_OUTPUT_FILE)
    parser.add_argument("--manifest-file", type=Path, default=DEFAULT_MANIFEST_FILE)
    parser.add_argument("--backup-dir", type=Path, default=DEFAULT_BACKUP_DIR)
    parser.add_argument(
        "--allow-duplicate-prompts",
        action="store_true",
        help="Allow the same user prompt to appear more than once.",
    )
    return parser.parse_args()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise DatasetError(f"File not found: {path}")

    records: list[dict[str, Any]] = []

    with path.open("r", encoding="utf-8-sig") as file:
        for line_number, raw_line in enumerate(file, start=1):
            line = raw_line.strip()

            if not line:
                continue

            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise DatasetError(
                    f"{path}, line {line_number}: invalid JSON: {exc.msg}"
                ) from exc

            if not isinstance(record, dict):
                raise DatasetError(
                    f"{path}, line {line_number}: each record must be a JSON object."
                )

            validate_record(record, path, line_number)
            records.append(record)

    if not records:
        raise DatasetError(f"No valid records found in: {path}")

    return records


def validate_record(
    record: dict[str, Any],
    source_path: Path,
    line_number: int,
) -> None:
    missing = REQUIRED_TOP_LEVEL_FIELDS - set(record)

    if missing:
        raise DatasetError(
            f"{source_path}, line {line_number}: missing fields: "
            f"{', '.join(sorted(missing))}"
        )

    record_id = record["id"]
    category = record["category"]
    risk_level = record["risk_level"]
    messages = record["messages"]

    if not isinstance(record_id, str) or not record_id.strip():
        raise DatasetError(
            f"{source_path}, line {line_number}: 'id' must be a non-empty string."
        )

    if not isinstance(category, str) or not category.strip():
        raise DatasetError(
            f"{source_path}, line {line_number}: "
            "'category' must be a non-empty string."
        )

    if risk_level not in VALID_RISK_LEVELS:
        raise DatasetError(
            f"{source_path}, line {line_number}: invalid risk_level "
            f"{risk_level!r}. Expected one of {sorted(VALID_RISK_LEVELS)}."
        )

    if not isinstance(messages, list) or len(messages) != 3:
        raise DatasetError(
            f"{source_path}, line {line_number}: 'messages' must contain exactly "
            "three messages: system, user, and assistant."
        )

    roles: list[str] = []

    for message_index, message in enumerate(messages, start=1):
        if not isinstance(message, dict):
            raise DatasetError(
                f"{source_path}, line {line_number}: message {message_index} "
                "must be an object."
            )

        if set(message) != {"role", "content"}:
            raise DatasetError(
                f"{source_path}, line {line_number}: message {message_index} "
                "must contain only 'role' and 'content'."
            )

        role = message["role"]
        content = message["content"]

        if not isinstance(role, str):
            raise DatasetError(
                f"{source_path}, line {line_number}: message {message_index} "
                "'role' must be a string."
            )

        if not isinstance(content, str) or not content.strip():
            raise DatasetError(
                f"{source_path}, line {line_number}: message {message_index} "
                "'content' must be a non-empty string."
            )

        roles.append(role)

    if roles != EXPECTED_ROLES:
        raise DatasetError(
            f"{source_path}, line {line_number}: roles must be exactly "
            f"{EXPECTED_ROLES}, but found {roles}."
        )


def normalize_prompt(text: str) -> str:
    return " ".join(text.lower().split())


def validate_merged_dataset(
    records: list[dict[str, Any]],
    allow_duplicate_prompts: bool,
) -> None:
    ids = [record["id"] for record in records]
    duplicate_ids = sorted(
        record_id for record_id, count in Counter(ids).items() if count > 1
    )

    if duplicate_ids:
        raise DatasetError(
            "Duplicate IDs found:\n  - " + "\n  - ".join(duplicate_ids)
        )

    prompts = [
        normalize_prompt(record["messages"][1]["content"])
        for record in records
    ]
    duplicate_prompts = sorted(
        prompt for prompt, count in Counter(prompts).items() if count > 1
    )

    if duplicate_prompts and not allow_duplicate_prompts:
        preview = duplicate_prompts[:10]
        message = "Duplicate user prompts found:\n  - " + "\n  - ".join(preview)

        if len(duplicate_prompts) > 10:
            message += f"\n  ... and {len(duplicate_prompts) - 10} more."

        message += (
            "\n\nReview the duplicates or rerun with "
            "--allow-duplicate-prompts if they are intentional."
        )
        raise DatasetError(message)


def backup_existing_output(output_file: Path, backup_dir: Path) -> Path | None:
    if not output_file.exists():
        return None

    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = backup_dir / f"{output_file.stem}_{timestamp}{output_file.suffix}"
    shutil.copy2(output_file, backup_path)
    return backup_path


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")

    with temporary_path.open("w", encoding="utf-8", newline="\n") as file:
        for record in records:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")

    temporary_path.replace(path)


def write_manifest(
    path: Path,
    base_file: Path,
    new_file: Path,
    output_file: Path,
    base_records: list[dict[str, Any]],
    new_records: list[dict[str, Any]],
    merged_records: list[dict[str, Any]],
) -> None:
    category_counts = Counter(record["category"] for record in merged_records)
    risk_counts = Counter(record["risk_level"] for record in merged_records)

    manifest = {
        "dataset_version": "v0.5",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "base_file": str(base_file),
        "new_examples_file": str(new_file),
        "output_file": str(output_file),
        "base_examples": len(base_records),
        "new_examples": len(new_records),
        "total_examples": len(merged_records),
        "categories": dict(sorted(category_counts.items())),
        "risk_levels": dict(sorted(risk_counts.items())),
        "validation": {
            "valid_json": True,
            "duplicate_ids": 0,
            "message_structure": "system-user-assistant",
            "status": "PASSED",
        },
    }

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def print_summary(
    base_records: list[dict[str, Any]],
    new_records: list[dict[str, Any]],
    merged_records: list[dict[str, Any]],
    output_file: Path,
    manifest_file: Path,
    backup_path: Path | None,
) -> None:
    category_counts = Counter(record["category"] for record in merged_records)

    print()
    print("GaiaLab Naija Assistant Dataset Builder")
    print("=" * 42)
    print(f"Base examples : {len(base_records)}")
    print(f"New examples  : {len(new_records)}")
    print(f"Total examples: {len(merged_records)}")
    print()
    print("Categories")
    print("-" * 42)

    width = max(len(category) for category in category_counts)
    for category, count in sorted(category_counts.items()):
        print(f"{category:<{width}}  {count:>4}")

    print()
    print("Validation")
    print("-" * 42)
    print("Valid JSON       : PASSED")
    print("Required fields  : PASSED")
    print("Message roles    : PASSED")
    print("Duplicate IDs    : 0")
    print()
    print(f"Training file    : {output_file}")
    print(f"Manifest file    : {manifest_file}")

    if backup_path:
        print(f"Previous backup  : {backup_path}")

    print()
    print("BUILD SUCCESSFUL")


def main() -> int:
    args = parse_args()

    try:
        base_records = load_jsonl(args.base_file)
        new_records = load_jsonl(args.new_file)
        merged_records = base_records + new_records

        validate_merged_dataset(
            merged_records,
            allow_duplicate_prompts=args.allow_duplicate_prompts,
        )

        backup_path = backup_existing_output(
            args.output_file,
            args.backup_dir,
        )

        write_jsonl(args.output_file, merged_records)
        write_manifest(
            args.manifest_file,
            args.base_file,
            args.new_file,
            args.output_file,
            base_records,
            new_records,
            merged_records,
        )

        print_summary(
            base_records,
            new_records,
            merged_records,
            args.output_file,
            args.manifest_file,
            backup_path,
        )
        return 0

    except DatasetError as exc:
        print()
        print("BUILD FAILED")
        print("=" * 42)
        print(exc)
        return 1

    except OSError as exc:
        print()
        print("BUILD FAILED")
        print("=" * 42)
        print(f"File system error: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
