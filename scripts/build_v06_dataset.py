"""Load, validate, and build the GaiaLab Naija v0.6 source dataset."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE_DIR = PROJECT_ROOT / "data/v0.6/examples"
DEFAULT_GENERATED_DIR = PROJECT_ROOT / "data/v0.6/generated"
DEFAULT_BACKUP_DIR = PROJECT_ROOT / "data/v0.6/backups"
EXPECTED_FILES = (
    "banking.csv",
    "healthcare.csv",
    "government_services.csv",
    "education.csv",
    "agriculture.csv",
    "travel.csv",
    "technology_support.csv",
    "small_business.csv",
    "nigerian_pidgin.csv",
    "business_writing.csv",
)
REQUIRED_COLUMNS = (
    "id",
    "category",
    "risk_level",
    "user",
    "assistant",
    "system",
    "source",
    "status",
    "review_notes",
)
ALLOWED_RISK_LEVELS = {"low", "medium", "high"}
DATASET_LICENSE = "CC0-1.0"


class DatasetV06Error(ValueError):
    """Raised when v0.6 source data violates its contract."""


def normalize_prompt(text: str) -> str:
    """Normalize a user prompt for cross-file duplicate detection."""
    return " ".join(text.casefold().split())


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def load_csv_file(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise DatasetV06Error(f"Missing required CSV: {_display_path(path)}")

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        actual_columns = tuple(reader.fieldnames or ())
        if actual_columns != REQUIRED_COLUMNS:
            raise DatasetV06Error(
                f"{_display_path(path)} has columns {actual_columns}; "
                f"expected exactly {REQUIRED_COLUMNS}."
            )

        rows: list[dict[str, str]] = []
        for line_number, raw_row in enumerate(reader, start=2):
            if None in raw_row:
                raise DatasetV06Error(
                    f"{_display_path(path)}:{line_number} has extra column values."
                )
            row = {column: (raw_row[column] or "").strip() for column in REQUIRED_COLUMNS}
            row["_source_file"] = _display_path(path)
            row["_source_line"] = str(line_number)
            rows.append(row)

    if not rows:
        raise DatasetV06Error(f"{_display_path(path)} contains no examples.")
    return rows


def load_all_csvs(source_dir: Path = DEFAULT_SOURCE_DIR) -> list[dict[str, str]]:
    """Load only the ten versioned source files, in a stable order."""
    return [
        row
        for filename in EXPECTED_FILES
        for row in load_csv_file(source_dir / filename)
    ]


def validate_rows(rows: Iterable[dict[str, str]]) -> list[dict[str, str]]:
    """Validate fields and reject duplicate IDs/prompts across all source CSVs."""
    materialized = list(rows)
    errors: list[str] = []
    ids: dict[str, list[str]] = {}
    prompts: dict[str, list[str]] = {}

    for row in materialized:
        location = f"{row.get('_source_file', '<memory>')}:{row.get('_source_line', '?')}"
        for field in REQUIRED_COLUMNS:
            if field not in row:
                errors.append(f"{location}: missing required column {field!r}.")

        record_id = row.get("id", "").strip()
        category = row.get("category", "").strip()
        risk_level = row.get("risk_level", "").strip()
        user = row.get("user", "").strip()
        assistant = row.get("assistant", "").strip()

        if not record_id:
            errors.append(f"{location}: id must not be empty.")
        elif not record_id.startswith("v06"):
            errors.append(f"{location}: id must begin with 'v06'.")
        if not category:
            errors.append(f"{location}: category must not be empty.")
        if risk_level not in ALLOWED_RISK_LEVELS:
            errors.append(
                f"{location}: risk_level {risk_level!r} is not one of "
                f"{sorted(ALLOWED_RISK_LEVELS)}."
            )
        if not user:
            errors.append(f"{location}: user text must not be empty.")
        if not assistant:
            errors.append(f"{location}: assistant text must not be empty.")
        if not row.get("system", "").strip():
            errors.append(f"{location}: system text must not be empty.")
        if not row.get("source", "").strip():
            errors.append(f"{location}: source must not be empty.")
        elif row["source"].strip() != "synthetic":
            errors.append(f"{location}: source must be 'synthetic'.")
        if not row.get("status", "").strip():
            errors.append(f"{location}: status must not be empty.")
        elif row["status"].strip() != "draft":
            errors.append(f"{location}: status must be 'draft'.")

        if record_id:
            ids.setdefault(record_id, []).append(location)
        if user:
            prompts.setdefault(normalize_prompt(user), []).append(location)

    for record_id, locations in sorted(ids.items()):
        if len(locations) > 1:
            errors.append(f"Duplicate ID {record_id!r}: {', '.join(locations)}.")
    for prompt, locations in sorted(prompts.items()):
        if len(locations) > 1:
            errors.append(
                f"Duplicate normalized prompt {prompt!r}: {', '.join(locations)}."
            )

    if not materialized:
        errors.append("No v0.6 examples were loaded.")
    if errors:
        raise DatasetV06Error("\n".join(errors))
    return materialized


def row_to_record(row: dict[str, str]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "category": row["category"],
        "risk_level": row["risk_level"],
        "messages": [
            {"role": "system", "content": row["system"]},
            {"role": "user", "content": row["user"]},
            {"role": "assistant", "content": row["assistant"]},
        ],
        "source": row["source"],
        "license": DATASET_LICENSE,
        "status": row["status"],
        "review_notes": row["review_notes"],
    }


def backup_existing_file(path: Path, backup_dir: Path = DEFAULT_BACKUP_DIR) -> Path | None:
    """Copy an existing generated file to a unique backup before replacement."""
    if not path.exists():
        return None
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    candidate = backup_dir / f"{path.stem}_{timestamp}{path.suffix}"
    counter = 1
    while candidate.exists():
        candidate = backup_dir / f"{path.stem}_{timestamp}_{counter}{path.suffix}"
        counter += 1
    shutil.copy2(path, candidate)
    return candidate


def atomic_write_text(
    path: Path,
    text: str,
    *,
    backup: bool = True,
    backup_dir: Path = DEFAULT_BACKUP_DIR,
) -> Path | None:
    """Write completely or not at all; never replace before making a backup."""
    path.parent.mkdir(parents=True, exist_ok=True)
    backup_path = backup_existing_file(path, backup_dir) if backup else None
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        temporary_path.replace(path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise
    return backup_path


def jsonl_text(records: Iterable[dict[str, Any]]) -> str:
    return "".join(
        json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
        for record in records
    )


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_dataset(
    source_dir: Path = DEFAULT_SOURCE_DIR,
    generated_dir: Path = DEFAULT_GENERATED_DIR,
) -> tuple[list[dict[str, Any]], list[Path | None]]:
    rows = validate_rows(load_all_csvs(source_dir))
    records = [row_to_record(row) for row in rows]
    all_path = generated_dir / "v0.6_all.jsonl"
    backups = [atomic_write_text(all_path, jsonl_text(records))]

    manifest = {
        "dataset_version": "v0.6",
        "dataset_status": "draft_pending_independent_nigerian_human_review",
        "license": DATASET_LICENSE,
        "record_count": len(records),
        "source_files": [
            {
                "path": _display_path(source_dir / filename),
                "record_count": sum(
                    row["_source_file"] == _display_path(source_dir / filename)
                    for row in rows
                ),
                "sha256": file_sha256(source_dir / filename),
            }
            for filename in EXPECTED_FILES
        ],
        "outputs": {"all": _display_path(all_path)},
        "category_counts": dict(sorted(Counter(r["category"] for r in records).items())),
        "risk_level_counts": dict(
            sorted(Counter(r["risk_level"] for r in records).items())
        ),
        "validation": {
            "required_columns": "passed",
            "duplicate_ids": 0,
            "duplicate_normalized_prompts": 0,
        },
    }
    manifest_path = generated_dir / "dataset_manifest.json"
    backups.append(
        atomic_write_text(
            manifest_path,
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            backup=False,
        )
    )
    return records, backups


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    parser.add_argument("--generated-dir", type=Path, default=DEFAULT_GENERATED_DIR)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        records, backups = build_dataset(args.source_dir, args.generated_dir)
    except (DatasetV06Error, OSError) as exc:
        print(f"v0.6 build failed: {exc}")
        return 1
    print(f"Built {len(records)} records in {_display_path(args.generated_dir)}.")
    for backup in backups:
        if backup:
            print(f"Backed up previous output to {_display_path(backup)}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
