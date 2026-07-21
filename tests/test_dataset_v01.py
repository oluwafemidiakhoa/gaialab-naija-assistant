import json
from collections import Counter
from pathlib import Path

from src.validate_dataset import validate_records


DATASET_PATH = Path(__file__).parents[1] / "data" / "gaialab_naija_v0.1.jsonl"
EXPECTED_SOURCE = "GaiaLab original draft — pending Nigerian human review"
EXPECTED_CATEGORIES = {
    "customer_service": 25,
    "terminology": 20,
    "translation_en_to_pidgin": 20,
    "translation_pidgin_to_en": 15,
    "business_writing": 20,
}


def load_dataset():
    return [
        json.loads(line)
        for line in DATASET_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_v01_has_exact_size_distribution_and_metadata():
    records = load_dataset()

    assert len(records) == 100
    assert Counter(record["category"] for record in records) == EXPECTED_CATEGORIES
    assert all(record["source"] == EXPECTED_SOURCE for record in records)
    assert all(record["license"] == "CC0-1.0" for record in records)


def test_v01_passes_validation_without_duplicates_or_warnings():
    records, report = validate_records(load_dataset())

    assert len(records) == 100
    assert report.valid_records == 100
    assert report.duplicates_removed == 0
    assert report.warnings == []
    assert report.by_category == EXPECTED_CATEGORIES


def test_v01_instruction_input_pairs_are_unique():
    records = load_dataset()
    prompts = {(record["instruction"], record["input"]) for record in records}

    assert len(prompts) == len(records)
