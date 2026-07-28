from __future__ import annotations

import csv
import sys
from collections import Counter
from pathlib import Path

import pytest


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from build_v06_dataset import (  # noqa: E402
    DatasetV06Error,
    REQUIRED_COLUMNS,
    atomic_write_text,
    load_csv_file,
    validate_rows,
)
from split_v06_dataset import stratified_split  # noqa: E402


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REQUIRED_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def valid_row(record_id: str = "v06-test-001", user: str = "A unique prompt") -> dict[str, str]:
    return {
        "id": record_id,
        "category": "test_category",
        "risk_level": "low",
        "user": user,
        "assistant": "A concise response.",
        "system": "Be helpful and safe.",
        "source": "synthetic",
        "status": "draft",
        "review_notes": "Fixture only.",
    }


def add_locations(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        {**row, "_source_file": f"fixture-{index}.csv", "_source_line": "2"}
        for index, row in enumerate(rows)
    ]


def split_record(
    record_id: str, category: str, risk_level: str
) -> dict[str, object]:
    return {
        "id": record_id,
        "category": category,
        "risk_level": risk_level,
        "messages": [
            {"role": "system", "content": "Safe."},
            {"role": "user", "content": f"Prompt {record_id}"},
            {"role": "assistant", "content": "Response."},
        ],
    }


def test_csv_loading_strips_values_and_tracks_location(tmp_path: Path) -> None:
    path = tmp_path / "examples.csv"
    row = valid_row()
    row["assistant"] = "  A concise response.  "
    write_csv(path, [row])

    loaded = load_csv_file(path)

    assert loaded[0]["assistant"] == "A concise response."
    assert loaded[0]["_source_file"] == str(path)
    assert loaded[0]["_source_line"] == "2"


def test_csv_loading_rejects_incorrect_columns(tmp_path: Path) -> None:
    path = tmp_path / "examples.csv"
    path.write_text("id,user\none,hello\n", encoding="utf-8")

    with pytest.raises(DatasetV06Error, match="expected exactly"):
        load_csv_file(path)


@pytest.mark.parametrize(
    ("rows", "message"),
    [
        (
            [
                valid_row("duplicate-id", "First prompt"),
                valid_row("duplicate-id", "Second prompt"),
            ],
            "Duplicate ID",
        ),
        (
            [
                valid_row("id-one", "  SAME   Prompt "),
                valid_row("id-two", "same prompt"),
            ],
            "Duplicate normalized prompt",
        ),
    ],
)
def test_duplicate_detection_across_csv_rows(
    rows: list[dict[str, str]], message: str
) -> None:
    with pytest.raises(DatasetV06Error, match=message):
        validate_rows(add_locations(rows))


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("risk_level", "critical", "risk_level"),
        ("id", "test-001", "begin with 'v06'"),
        ("user", " ", "user text must not be empty"),
        ("assistant", "", "assistant text must not be empty"),
        ("source", "unknown", "source must be 'synthetic'"),
        ("status", "approved", "status must be 'draft'"),
    ],
)
def test_validation_rejects_invalid_required_values(
    field: str, value: str, message: str
) -> None:
    row = valid_row()
    row[field] = value

    with pytest.raises(DatasetV06Error, match=message):
        validate_rows(add_locations([row]))


def test_stratified_split_is_deterministic_and_partitions_each_stratum() -> None:
    records = [
        split_record(f"{category}-{risk}-{index}", category, risk)
        for category in ("banking", "travel")
        for risk in ("low", "high")
        for index in range(4)
    ]

    first = stratified_split(records, validation_fraction=0.25, seed="test-seed")
    second = stratified_split(list(reversed(records)), 0.25, "test-seed")

    assert first == second
    training, validation = first
    assert {record["id"] for record in training}.isdisjoint(
        record["id"] for record in validation
    )
    assert len(training) + len(validation) == len(records)
    assert Counter((r["category"], r["risk_level"]) for r in validation) == {
        ("banking", "high"): 1,
        ("banking", "low"): 1,
        ("travel", "high"): 1,
        ("travel", "low"): 1,
    }


def test_singleton_stratum_stays_in_training() -> None:
    record = split_record("only-one", "banking", "high")

    training, validation = stratified_split([record])

    assert training == [record]
    assert validation == []


def test_atomic_write_backs_up_every_existing_jsonl_version(tmp_path: Path) -> None:
    output = tmp_path / "generated" / "dataset.jsonl"
    backup_dir = tmp_path / "backups"
    output.parent.mkdir()
    output.write_text('{"version": 1}\n', encoding="utf-8")

    first_backup = atomic_write_text(
        output, '{"version": 2}\n', backup_dir=backup_dir
    )
    second_backup = atomic_write_text(
        output, '{"version": 3}\n', backup_dir=backup_dir
    )

    assert first_backup is not None
    assert second_backup is not None
    assert first_backup != second_backup
    assert first_backup.read_text(encoding="utf-8") == '{"version": 1}\n'
    assert second_backup.read_text(encoding="utf-8") == '{"version": 2}\n'
    assert output.read_text(encoding="utf-8") == '{"version": 3}\n'
