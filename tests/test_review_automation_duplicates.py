from __future__ import annotations

from src.review_automation.duplicates import (
    duplicate_match_map,
    duplicate_likelihood,
    find_duplicate_matches,
    normalize_text,
    similarity,
)


def record(record_id: str, prompt: str, answer: str) -> dict:
    return {
        "id": record_id,
        "example_sha256": record_id[-1] * 64,
        "messages": [
            {"role": "system", "content": "Be safe."},
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": answer},
        ],
    }


def test_normalization_is_unicode_case_and_punctuation_stable() -> None:
    assert normalize_text("  GOOD—Day, Lagos! ") == "good day lagos"


def test_exact_and_field_duplicates_identify_matched_record() -> None:
    first = record("record-a", "Where is my order?", "Please check the order reference.")
    second = record("record-b", "Where is my order?", "Please check the order reference.")
    matches = find_duplicate_matches(first, [first, second])
    assert {match.match_type for match in matches} >= {
        "exact", "prompt", "answer", "prompt_answer"
    }
    assert {match.matched_record_id for match in matches} == {"record-b"}
    assert duplicate_likelihood(matches) == 100


def test_normalized_and_near_duplicates_are_explained() -> None:
    first = record("record-a", "Please confirm my transfer.", "Use your official bank app.")
    normalized = record(
        "record-b", "please CONFIRM my transfer!", "Use your official bank app"
    )
    near = record(
        "record-c",
        "Please confirm whether my transfer arrived.",
        "Check through your official bank app.",
    )
    matches = find_duplicate_matches(
        first, [first, normalized, near], near_threshold=0.55
    )
    assert any(
        match.match_type == "normalized" and match.matched_record_id == "record-b"
        for match in matches
    )
    assert any(
        match.match_type == "near" and match.matched_record_id == "record-c"
        for match in matches
    )
    assert similarity("one two three", "one two four") == similarity(
        "one two four", "one two three"
    )


def test_batch_duplicate_map_matches_individual_analysis() -> None:
    rows = [
        record("record-a", "Where is my order?", "Please check your order."),
        record("record-b", "Where is my order?", "Please check your order."),
        record("record-c", "How do I update stock?", "Count the available items."),
    ]
    mapped = duplicate_match_map(rows)
    for row in rows:
        identity = (row["id"], row["example_sha256"])
        assert mapped[identity] == find_duplicate_matches(row, rows)
