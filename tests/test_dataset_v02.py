import json
import re
from collections import Counter
from pathlib import Path

from src.validate_dataset import validate_records


DATASET_PATH = Path("data/v0.2/english_to_pidgin_100.jsonl")
INSTRUCTION = (
    "Translate the following English sentence into natural Nigerian Pidgin. "
    "Preserve all names, numbers, dates, times, and meanings. Do not add information."
)
SOURCE = "GaiaLab original draft — pending independent Nigerian human review"
CATEGORIES = {
    "delivery_and_logistics",
    "payments_and_refunds",
    "orders_and_inventory",
    "customer_complaints",
    "appointments_and_scheduling",
    "banking_and_mobile_payments",
    "market_and_retail_conversations",
    "small_business_communication",
    "agriculture_and_food_sales",
    "general_everyday_communication",
}


def load_records():
    return [json.loads(line) for line in DATASET_PATH.read_text(encoding="utf-8").splitlines()]


def test_v02_schema_ids_distribution_and_provenance():
    records = load_records()
    validated, report = validate_records(records)

    assert len(records) == len(validated) == report.valid_records == 100
    assert [record["id"] for record in records] == [
        f"en_pcm_{index:03d}" for index in range(1, 101)
    ]
    assert Counter(record["category"] for record in records) == {
        category: 10 for category in CATEGORIES
    }
    assert all(record["instruction"] == INSTRUCTION for record in records)
    assert all(record["language"] == "English to Nigerian Pidgin" for record in records)
    assert all(record["source"] == SOURCE for record in records)
    assert all(record["license"] == "CC0-1.0" for record in records)


def test_v02_inputs_outputs_are_unique_and_nonempty():
    records = load_records()
    inputs = [record["input"] for record in records]
    outputs = [record["output"] for record in records]

    assert len(set(inputs)) == 100
    assert len(set(outputs)) == 100
    assert all(value.strip() for value in inputs + outputs)


def test_v02_preserves_numeric_expressions_exactly():
    records = load_records()
    numeric_expression = re.compile(
        r"(?:₦)?\d+(?:,\d{3})*(?:\.\d+)?(?::\d{2})?(?:\s?(?:AM|PM|kg|ml))?"
    )

    for record in records:
        assert numeric_expression.findall(record["input"]) == numeric_expression.findall(
            record["output"]
        ), record["id"]
