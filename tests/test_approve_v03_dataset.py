from scripts.approve_v03_dataset import (
    is_approved,
    validate_approved_record,
)


def make_record(
    status="approved",
    approved_for_training=True,
):
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
                "content": "System instruction",
            },
            {
                "role": "user",
                "content": "User prompt",
            },
            {
                "role": "assistant",
                "content": "Assistant response",
            },
        ],
        "status": status,
        "approved_for_training": approved_for_training,
        "review_notes": "Reviewed.",
    }


def test_is_approved_requires_both_fields():
    assert is_approved(make_record()) is True

    assert (
        is_approved(
            make_record(status="needs_human_review")
        )
        is False
    )

    assert (
        is_approved(
            make_record(approved_for_training=False)
        )
        is False
    )


def test_valid_approved_record_has_no_errors():
    errors = validate_approved_record(make_record())

    assert errors == []


def test_rejects_invalid_message_structure():
    record = make_record()
    record["messages"] = []

    errors = validate_approved_record(record)

    assert errors


def test_rejects_unapproved_record():
    record = make_record(
        status="needs_revision",
        approved_for_training=False,
    )

    errors = validate_approved_record(record)

    assert "status must be approved" in errors
    assert "approved_for_training must be true" in errors