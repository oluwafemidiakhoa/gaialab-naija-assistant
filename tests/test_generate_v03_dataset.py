from scripts.generate_v03_dataset import (
    add_record_ids,
    build_customer_service_records,
    build_terminology_records,
    build_translation_records,
    validate_dataset,
)


def build_all_records():
    records = []
    records.extend(build_customer_service_records())
    records.extend(build_terminology_records())
    records.extend(build_translation_records())
    return add_record_ids(records)


def test_v03_generator_creates_expected_number_of_records():
    records = build_all_records()

    assert len(records) == 19


def test_v03_candidate_ids_are_unique():
    records = build_all_records()
    record_ids = [record["id"] for record in records]

    assert len(record_ids) == len(set(record_ids))


def test_v03_candidates_require_human_review():
    records = build_all_records()

    for record in records:
        assert record["status"] == "needs_human_review"
        assert record["approved_for_training"] is False


def test_v03_generated_dataset_is_valid():
    records = build_all_records()

    validate_dataset(records)