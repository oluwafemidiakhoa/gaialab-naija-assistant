"""Validate, deduplicate, summarize, and split GaiaLab JSONL datasets."""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

REQUIRED_FIELDS = (
    "instruction",
    "input",
    "output",
    "language",
    "category",
    "source",
    "license",
)
SHORT_OUTPUT_WORDS = 3


class DatasetValidationError(ValueError):
    """Raised when a dataset record does not meet the project contract."""


@dataclass
class ValidationReport:
    total_read: int = 0
    valid_records: int = 0
    duplicates_removed: int = 0
    warnings: list[str] = field(default_factory=list)
    by_language: Counter[str] = field(default_factory=Counter)
    by_category: Counter[str] = field(default_factory=Counter)

    def as_dict(self) -> dict[str, Any]:
        return {
            "total_read": self.total_read,
            "valid_records": self.valid_records,
            "duplicates_removed": self.duplicates_removed,
            "by_language": dict(sorted(self.by_language.items())),
            "by_category": dict(sorted(self.by_category.items())),
            "warnings": self.warnings,
        }


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Read JSON objects from *path*, reporting useful line-number errors."""
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise DatasetValidationError(
                    f"Line {line_number}: invalid JSON ({exc.msg})."
                ) from exc
            if not isinstance(value, dict):
                raise DatasetValidationError(
                    f"Line {line_number}: each JSONL line must be an object."
                )
            records.append(value)
    return records


def validate_records(
    records: Iterable[dict[str, Any]],
) -> tuple[list[dict[str, Any]], ValidationReport]:
    """Validate records and remove exact duplicate JSON objects."""
    report = ValidationReport()
    validated: list[dict[str, Any]] = []
    seen: set[str] = set()

    for line_number, record in enumerate(records, start=1):
        report.total_read += 1
        missing = [field for field in REQUIRED_FIELDS if field not in record]
        if missing:
            raise DatasetValidationError(
                f"Record {line_number}: missing required field(s): {', '.join(missing)}."
            )

        for field_name in REQUIRED_FIELDS:
            if not isinstance(record[field_name], str):
                raise DatasetValidationError(
                    f"Record {line_number}: '{field_name}' must be a string."
                )

        for field_name in ("instruction", "output", "source", "license"):
            if not record[field_name].strip():
                raise DatasetValidationError(
                    f"Record {line_number}: '{field_name}' must not be empty."
                )

        canonical = json.dumps(record, ensure_ascii=False, sort_keys=True)
        if canonical in seen:
            report.duplicates_removed += 1
            continue
        seen.add(canonical)

        if len(record["output"].split()) < SHORT_OUTPUT_WORDS:
            report.warnings.append(
                f"Record {line_number}: output is unusually short "
                f"(< {SHORT_OUTPUT_WORDS} words)."
            )

        clean = {field: record[field].strip() for field in REQUIRED_FIELDS}
        validated.append(clean)
        report.by_language[clean["language"]] += 1
        report.by_category[clean["category"]] += 1

    if not validated:
        raise DatasetValidationError("Dataset contains no valid records.")

    report.valid_records = len(validated)
    return validated, report


def split_records(
    records: list[dict[str, Any]], validation_ratio: float = 0.2, seed: int = 42
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return reproducible train and validation splits."""
    if not 0 < validation_ratio < 1:
        raise ValueError("validation_ratio must be between 0 and 1.")
    if len(records) < 2:
        raise DatasetValidationError("At least two unique records are required to split.")

    shuffled = list(records)
    random.Random(seed).shuffle(shuffled)
    validation_size = max(1, round(len(shuffled) * validation_ratio))
    validation_size = min(validation_size, len(shuffled) - 1)
    return shuffled[validation_size:], shuffled[:validation_size]


def write_jsonl(path: Path, records: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def validate_and_split(
    input_path: Path,
    output_dir: Path,
    validation_ratio: float = 0.2,
    seed: int = 42,
) -> ValidationReport:
    records, report = validate_records(read_jsonl(input_path))
    train, validation = split_records(records, validation_ratio, seed)
    write_jsonl(output_dir / "train.jsonl", train)
    write_jsonl(output_dir / "validation.jsonl", validation)
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Input JSONL dataset")
    parser.add_argument("--output-dir", type=Path, default=Path("prepared_data"))
    parser.add_argument("--validation-ratio", type=float, default=0.2)
    parser.add_argument("--seed", type=int, default=42)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        report = validate_and_split(
            args.input, args.output_dir, args.validation_ratio, args.seed
        )
    except (OSError, DatasetValidationError, ValueError) as exc:
        print(f"Dataset validation failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report.as_dict(), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
