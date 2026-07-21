import json
from pathlib import Path

import pytest

from src.prepare_dataset import (
    format_example,
    load_validated_splits,
    remove_generated_output,
)


def record(instruction: str) -> dict[str, str]:
    return {
        "instruction": instruction,
        "input": "Order context",
        "output": "A complete and useful response.",
        "language": "Nigerian English",
        "category": "customer_service",
        "source": "Original test fixture",
        "license": "CC0-1.0",
    }


def write_jsonl(path, records):
    path.write_text(
        "".join(json.dumps(item) + "\n" for item in records), encoding="utf-8"
    )


def test_formats_conversational_prompt_and_completion():
    formatted = format_example(record("Write a reply"))
    assert [message["role"] for message in formatted["prompt"]] == ["system", "user"]
    assert formatted["completion"] == [
        {"role": "assistant", "content": "A complete and useful response."}
    ]


def test_rejects_duplicate_record_across_splits(tmp_path):
    duplicate = record("Write a reply")
    train = tmp_path / "train.jsonl"
    validation = tmp_path / "validation.jsonl"
    write_jsonl(train, [duplicate])
    write_jsonl(validation, [duplicate])
    with pytest.raises(ValueError, match="both dataset splits"):
        load_validated_splits(train, validation)


def test_loads_distinct_validated_splits(tmp_path):
    train = tmp_path / "train.jsonl"
    validation = tmp_path / "validation.jsonl"
    write_jsonl(train, [record("Train instruction")])
    write_jsonl(validation, [record("Validation instruction")])
    splits = load_validated_splits(train, validation)
    assert set(splits) == {"train", "validation"}


def test_removes_only_explicit_generated_directory(tmp_path):
    output = tmp_path / "prepared" / "hf"
    output.mkdir(parents=True)
    (output / "state.json").write_text("{}", encoding="utf-8")
    remove_generated_output(output)
    assert not output.exists()


def test_refuses_to_remove_current_directory():
    with pytest.raises(ValueError, match="protected directory"):
        remove_generated_output(Path.cwd())
