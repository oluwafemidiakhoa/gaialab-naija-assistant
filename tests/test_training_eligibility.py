from copy import deepcopy

from src.dataset_management import example_sha256
from src.training_eligibility import (
    assess_eligibility, assert_no_benchmark_leakage, deterministic_splits,
)


def record(category="business_writing"):
    row = {
        "id": "v06-x-001", "dataset_version": "v0.6", "revision": 1,
        "category": category, "risk_level": "low", "source": "synthetic",
        "license": "CC0-1.0", "review_status": "approved",
        "technical_review_completed": True,
        "messages": [
            {"role": "system", "content": "Help."},
            {"role": "user", "content": "Write a note."},
            {"role": "assistant", "content": "Thank you for your order."},
        ],
    }
    row["example_sha256"] = example_sha256(row)
    return row


def test_eligible_approved_record():
    decision = assess_eligibility(record(), "v0.6", now=lambda: "2026-01-01T00:00:00+00:00")
    assert decision.eligible and len(decision.decision_sha256) == 64


def test_draft_is_excluded_with_reasons():
    row = record()
    row["review_status"] = "draft"
    assert "not_approved" in assess_eligibility(row, "v0.6").reasons


def test_domain_review_and_critical_findings_exclude():
    row = record("healthcare")
    reasons = assess_eligibility(
        row, "v0.6", critical_findings=[{"severity": "critical"}]
    ).reasons
    assert {"domain_review_incomplete", "unresolved_critical_finding"} <= set(reasons)


def test_hash_license_provenance_and_release_enforced():
    row = record()
    row.update(source="", license="", dataset_version="v9", example_sha256="bad")
    reasons = assess_eligibility(row, "v0.6").reasons
    assert {"provenance_incomplete", "license_missing", "content_hash_mismatch", "wrong_release"} <= set(reasons)


def test_splits_are_deterministic_and_disjoint():
    rows = []
    for number in range(10):
        row = record()
        row["id"] = f"v06-x-{number:03}"
        row["messages"][1]["content"] = f"Write note number {number}."
        row["example_sha256"] = example_sha256(row)
        rows.append(row)
    assert deterministic_splits(rows) == deterministic_splits(reversed(rows))
    assert_no_benchmark_leakage(deterministic_splits(rows))


def test_leakage_detection():
    row = record()
    splits = {"training": [row], "validation": [], "held_out_benchmark": [deepcopy(row)]}
    try:
        assert_no_benchmark_leakage(splits)
    except ValueError as exc:
        assert "leakage" in str(exc)
    else:
        raise AssertionError("leakage was accepted")
