import json
import random
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]

V01_PATH = PROJECT_ROOT / "data" / "gaialab_naija_v0.1_with_ids.jsonl"
V02_PATH = PROJECT_ROOT / "data" / "v0.2" / "english_to_pidgin_100.jsonl"

OUTPUT_DIR = PROJECT_ROOT / "data" / "v0.2" / "prepared"
COMBINED_PATH = OUTPUT_DIR / "gaialab_naija_v0.2_combined.jsonl"
TRAIN_PATH = OUTPUT_DIR / "gaialab_naija_v0.2_train.jsonl"
VALIDATION_PATH = OUTPUT_DIR / "gaialab_naija_v0.2_validation.jsonl"

RANDOM_SEED = 42
VALIDATION_RATIO = 0.10


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"Dataset file not found: {path}")

    records = []

    with path.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            line = line.strip()

            if not line:
                continue

            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as error:
                raise ValueError(
                    f"Invalid JSON in {path} on line {line_number}: {error}"
                ) from error

    return records


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8") as file:
        for record in records:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")


def validate_required_fields(records: list[dict[str, Any]]) -> None:
    required_fields = {"id", "input", "output"}

    for index, record in enumerate(records, start=1):
        missing_fields = required_fields - record.keys()

        if missing_fields:
            raise ValueError(
                f"Record {index} is missing fields: {sorted(missing_fields)}"
            )

        for field in required_fields:
            value = record[field]

            if not isinstance(value, str):
                raise TypeError(
                    f"Record {record.get('id', index)} field "
                    f"'{field}' must be a string."
                )

            if not value.strip():
                raise ValueError(
                    f"Record {record.get('id', index)} field "
                    f"'{field}' cannot be empty."
                )


def find_duplicate_ids(records: list[dict[str, Any]]) -> list[str]:
    seen = set()
    duplicates = set()

    for record in records:
        record_id = record["id"]

        if record_id in seen:
            duplicates.add(record_id)

        seen.add(record_id)

    return sorted(duplicates)


def find_duplicate_examples(records: list[dict[str, Any]]) -> list[str]:
    seen = set()
    duplicates = []

    for record in records:
        signature = (
            record["input"].strip().lower(),
            record["output"].strip().lower(),
        )

        if signature in seen:
            duplicates.append(record["id"])
        else:
            seen.add(signature)

    return duplicates


def main() -> None:
    v01_records = load_jsonl(V01_PATH)
    v02_records = load_jsonl(V02_PATH)

    combined_records = v01_records + v02_records

    validate_required_fields(combined_records)

    duplicate_ids = find_duplicate_ids(combined_records)

    if duplicate_ids:
        raise ValueError(
            f"Duplicate record IDs found: {duplicate_ids}"
        )

    duplicate_examples = find_duplicate_examples(combined_records)

    if duplicate_examples:
        raise ValueError(
            "Duplicate training examples found in records: "
            f"{duplicate_examples}"
        )

    random_generator = random.Random(RANDOM_SEED)
    random_generator.shuffle(combined_records)

    validation_size = max(
        1,
        round(len(combined_records) * VALIDATION_RATIO),
    )

    validation_records = combined_records[:validation_size]
    train_records = combined_records[validation_size:]

    write_jsonl(COMBINED_PATH, combined_records)
    write_jsonl(TRAIN_PATH, train_records)
    write_jsonl(VALIDATION_PATH, validation_records)

    print("GaiaLab Naija v0.2 dataset preparation complete")
    print(f"v0.1 records:       {len(v01_records)}")
    print(f"New v0.2 records:   {len(v02_records)}")
    print(f"Combined records:   {len(combined_records)}")
    print(f"Training records:   {len(train_records)}")
    print(f"Validation records: {len(validation_records)}")
    print(f"Random seed:        {RANDOM_SEED}")
    print()
    print(f"Combined:   {COMBINED_PATH}")
    print(f"Train:      {TRAIN_PATH}")
    print(f"Validation: {VALIDATION_PATH}")


if __name__ == "__main__":
    main()