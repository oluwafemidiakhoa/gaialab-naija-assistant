from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


DEFAULT_INPUT_FILE = Path("data/v0.5/v0.5_examples.csv")
DEFAULT_OUTPUT_FILE = Path("data/v0.5/v0.5_new_examples.jsonl")

SYSTEM_PROMPT = (
    "You are GaiaLab Naija Assistant. Be helpful, concise, culturally aware, "
    "truthful, and safe. Never invent facts or request passwords, PINs, or OTPs."
)

REQUIRED_COLUMNS = {
    "id",
    "category",
    "risk_level",
    "user",
    "assistant",
}

VALID_RISK_LEVELS = {"low", "medium", "high"}


class ExampleGenerationError(Exception):
    """Raised when examples cannot be generated."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert GaiaLab v0.5 CSV examples into JSONL."
    )
    parser.add_argument(
        "--input-file",
        type=Path,
        default=DEFAULT_INPUT_FILE,
        help="CSV file containing new examples.",
    )
    parser.add_argument(
        "--output-file",
        type=Path,
        default=DEFAULT_OUTPUT_FILE,
        help="JSONL file to create.",
    )
    return parser.parse_args()


def validate_row(
    row: dict[str, str],
    row_number: int,
    seen_ids: set[str],
) -> dict[str, str]:
    cleaned = {
        key: (value.strip() if isinstance(value, str) else "")
        for key, value in row.items()
        if key is not None
    }

    missing_values = [
        column for column in REQUIRED_COLUMNS if not cleaned.get(column)
    ]

    if missing_values:
        raise ExampleGenerationError(
            f"CSV row {row_number}: missing values for "
            f"{', '.join(sorted(missing_values))}."
        )

    record_id = cleaned["id"]
    risk_level = cleaned["risk_level"].lower()

    if record_id in seen_ids:
        raise ExampleGenerationError(
            f"CSV row {row_number}: duplicate ID {record_id!r}."
        )

    if risk_level not in VALID_RISK_LEVELS:
        raise ExampleGenerationError(
            f"CSV row {row_number}: invalid risk level {risk_level!r}. "
            f"Use low, medium, or high."
        )

    seen_ids.add(record_id)
    cleaned["risk_level"] = risk_level
    return cleaned


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise ExampleGenerationError(
            f"Input CSV not found: {path}\n"
            "Create the CSV first using the included template."
        )

    with path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)

        if reader.fieldnames is None:
            raise ExampleGenerationError("The CSV file has no header row.")

        actual_columns = {name.strip() for name in reader.fieldnames if name}
        missing_columns = REQUIRED_COLUMNS - actual_columns

        if missing_columns:
            raise ExampleGenerationError(
                "CSV is missing required columns: "
                + ", ".join(sorted(missing_columns))
            )

        rows: list[dict[str, str]] = []
        seen_ids: set[str] = set()

        for row_number, row in enumerate(reader, start=2):
            if not any((value or "").strip() for value in row.values()):
                continue

            rows.append(validate_row(row, row_number, seen_ids))

    if not rows:
        raise ExampleGenerationError("The CSV contains no examples.")

    return rows


def convert_to_records(rows: list[dict[str, str]]) -> list[dict]:
    records = []

    for row in rows:
        system_prompt = row.get("system", "").strip() or SYSTEM_PROMPT

        records.append(
            {
                "id": row["id"],
                "category": row["category"],
                "risk_level": row["risk_level"],
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": row["user"]},
                    {"role": "assistant", "content": row["assistant"]},
                ],
            }
        )

    return records


def write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")

    with temporary_path.open("w", encoding="utf-8", newline="\n") as file:
        for record in records:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")

    temporary_path.replace(path)


def main() -> int:
    args = parse_args()

    try:
        rows = read_csv(args.input_file)
        records = convert_to_records(rows)
        write_jsonl(args.output_file, records)

        print()
        print("GaiaLab Example Generator")
        print("=" * 42)
        print(f"Input CSV       : {args.input_file}")
        print(f"Output JSONL    : {args.output_file}")
        print(f"Examples written: {len(records)}")
        print()
        print("GENERATION SUCCESSFUL")
        return 0

    except ExampleGenerationError as exc:
        print()
        print("GENERATION FAILED")
        print("=" * 42)
        print(exc)
        return 1

    except OSError as exc:
        print()
        print("GENERATION FAILED")
        print("=" * 42)
        print(f"File system error: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
