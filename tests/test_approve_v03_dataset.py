from scripts.approve_v03_dataset import (
    is_approved,
    validate_approved_record,
)


def make_record(
    status: str = "approved",
    approved_for_training: bool = True,
) -> dict:
    return {
        "id": "v03_candidate_0001",
        "category": "customer_service",
        "task": "business_response",
        "source_language": "english",
        "target_language": "english",
        "difficulty": "medium",
        "failure_tags": ["meaning_preservation"],
        "messages": [
            {
                "role": "system",
                "content": "Provide a clear and professional response.",
            },
            {
                "role": "user",
                "content": "When will my order arrive?",
            },
            {
                "role": "assistant",
                "content": (
                    "Your order is currently being processed. "
                    "Please check the tracking information for "
                    "the latest delivery estimate."
                ),
            },
        ],
        "status": status,
        "approved_for_training": approved_for_training,
        "review_notes": "Reviewed and approved.",
    }


def test_is_approved_accepts_valid_record() -> None:
    record = make_record()

    assert is_approved(record) is True


def test_is_approved_requires_approved_status() -> None:
    record = make_record(
        status="needs_human_review",
        approved_for_training=True,
    )

    assert is_approved(record) is False


def test_is_approved_requires_training_flag() -> None:
    record = make_record(
        status="approved",
        approved_for_training=False,
    )

    assert is_approved(record) is False


def test_valid_approved_record_has_no_errors() -> None:
    record = make_record()

    errors = validate_approved_record(record)

    assert errors == []


def test_rejects_invalid_message_structure() -> None:
    record = make_record()
    record["messages"] = []

    errors = validate_approved_record(record)

    assert errors


def test_rejects_unapproved_record() -> None:
    record = make_record(
        status="needs_revision",
        approved_for_training=False,
    )

    errors = validate_approved_record(record)

    assert "status must be approved" in errors
    assert "approved_for_training must be true" in errors