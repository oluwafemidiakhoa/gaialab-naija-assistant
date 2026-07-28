import json

import pytest

from src.validate_dataset import (
    DatasetValidationError,
    split_records,
    validate_and_split,
    validate_records,
)


def record(**overrides):
    value = {
        "instruction": "Write a reply",
        "input": "A customer asked a question",
        "output": "Thank you for your message. We will reply shortly.",
        "language": "Nigerian English",
        "category": "customer_service",
        "source": "Original test fixture",
        "license": "CC0-1.0",
    }
    value.update(overrides)
    return value


@pytest.mark.parametrize("field", ["instruction", "output", "source", "license"])
def test_rejects_missing_required_fields(field):
    value = record()
    del value[field]
    with pytest.raises(DatasetValidationError, match="missing required field"):
        validate_records([value])


@pytest.mark.parametrize("field", ["instruction", "output", "source", "license"])
def test_rejects_empty_critical_fields(field):
    with pytest.raises(DatasetValidationError, match=f"'{field}' must not be empty"):
        validate_records([record(**{field: "   "})])


def test_removes_exact_duplicates_and_reports_counts():
    first = record()
    second = record(language="Nigerian Pidgin", category="translation")
    records, report = validate_records([first, first.copy(), second])
    assert len(records) == 2
    assert report.duplicates_removed == 1
    assert report.by_language == {"Nigerian English": 1, "Nigerian Pidgin": 1}
    assert report.by_category == {"customer_service": 1, "translation": 1}


def test_warns_about_short_output():
    _, report = validate_records([record(output="Too short")])
    assert len(report.warnings) == 1
    assert "unusually short" in report.warnings[0]


def test_split_is_reproducible_and_nonempty():
    records = [record(instruction=f"Instruction {index}") for index in range(10)]
    assert split_records(records, seed=7) == split_records(records, seed=7)
    train, validation = split_records(records, validation_ratio=0.2, seed=7)
    assert len(train) == 8
    assert len(validation) == 2


def test_validate_and_split_writes_jsonl(tmp_path):
    input_path = tmp_path / "input.jsonl"
    values = [record(instruction=f"Instruction {index}") for index in range(5)]
    input_path.write_text(
        "".join(json.dumps(value) + "\n" for value in values), encoding="utf-8"
    )
    output_dir = tmp_path / "prepared"
    report = validate_and_split(input_path, output_dir)
    assert report.valid_records == 5
    assert len((output_dir / "train.jsonl").read_text().splitlines()) == 4
    assert len((output_dir / "validation.jsonl").read_text().splitlines()) == 1


def test_chat_schema_v06_compatibility():
    value = {
        "id": "v06-test-001", "category": "banking", "risk_level": "high",
        "source": "synthetic", "license": "CC0-1.0",
        "messages": [
            {"role": "system", "content": "Be safe."},
            {"role": "user", "content": "I noticed an unknown debit."},
            {"role": "assistant", "content": "Contact your bank through an official channel."},
        ],
    }
    records, report = validate_records([value])
    assert records[0]["id"] == "v06-test-001"
    assert report.by_language == {"Nigerian English": 1}


def test_chat_schema_rejects_empty_user():
    value = {
        "id": "v06-test-001", "category": "banking", "risk_level": "high",
        "source": "synthetic", "license": "CC0-1.0",
        "messages": [
            {"role": "system", "content": "Be safe."},
            {"role": "user", "content": ""},
            {"role": "assistant", "content": "Contact your bank."},
        ],
    }
    with pytest.raises(DatasetValidationError, match="user"):
        validate_records([value])
