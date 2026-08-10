from __future__ import annotations

import json
from pathlib import Path

from src.dataset_management import example_sha256, import_version, review_state
from src.language_governance import (
    cultural_validation_is_current,
    requires_cultural_validation,
    stage_trust_fixture_records,
)
from src.review_workflow import create_revision, record_cultural_validation, transition_review
from src.training_eligibility import assess_eligibility


def _fixture() -> dict:
    return {
        "id": "pidgin-trust-test",
        "language": "Nigerian Pidgin",
        "user_message": "Transfer nko?",
        "assistant_response": "The transfer still dey pending.",
        "authoritative_state": {"transaction_status": "pending"},
        "expected_extracted_claims": {"transaction_status": "pending"},
        "expected_disposition": "ALLOW",
        "expected_claim_status": "SUPPORTED",
        "synthetic": True,
        "culturally_validated": False,
    }


def _registry(tmp_path: Path) -> Path:
    staged = stage_trust_fixture_records([_fixture()], source_path="evaluation/fixture.jsonl")
    source = tmp_path / "source.jsonl"
    source.write_text(json.dumps(staged[0]) + "\n", encoding="utf-8")
    registry = tmp_path / "registry"
    import_version(source, registry, "naija-review-v0.1")
    return registry


def test_staging_is_draft_and_never_culturally_validated():
    row = stage_trust_fixture_records([_fixture()], source_path="fixture.jsonl")[0]
    assert row["review_status"] == "draft"
    assert row["culturally_validated"] is False
    assert row["cultural_review_completed"] is False
    assert row["source"].startswith("gaialab-naija-language-review:")
    assert requires_cultural_validation(row) is True


def test_training_gate_requires_current_cultural_validation(tmp_path: Path):
    registry = _registry(tmp_path)
    record_id = "naija-language-pidgin-trust-test"
    transition_review(registry, "naija-review-v0.1", record_id, "automated_reviewed", "auto-01", "reviewer")
    transition_review(registry, "naija-review-v0.1", record_id, "technical_reviewed", "tech-01", "technical_reviewer")
    transition_review(registry, "naija-review-v0.1", record_id, "domain_reviewed", "domain-01", "domain_reviewer")
    transition_review(registry, "naija-review-v0.1", record_id, "approved", "domain-01", "domain_reviewer")

    approved = review_state(registry, "naija-review-v0.1")[0]
    decision = assess_eligibility(approved, "naija-review-v0.1")
    assert decision.eligible is False
    assert "cultural_validation_incomplete" in decision.reasons

    record_cultural_validation(
        registry,
        "naija-review-v0.1",
        record_id,
        "naija-cultural-01",
        "domain_reviewer",
        culturally_validated=True,
        review_notes="Reviewed Nigerian Pidgin phrasing and meaning.",
        now=lambda: "2026-08-10T20:00:00+00:00",
    )
    validated = review_state(registry, "naija-review-v0.1")[0]
    assert cultural_validation_is_current(validated) is True
    assert assess_eligibility(validated, "naija-review-v0.1").eligible is True


def test_revision_invalidates_prior_cultural_validation(tmp_path: Path):
    registry = _registry(tmp_path)
    record_id = "naija-language-pidgin-trust-test"
    record_cultural_validation(
        registry,
        "naija-review-v0.1",
        record_id,
        "naija-cultural-01",
        "domain_reviewer",
        culturally_validated=True,
        now=lambda: "2026-08-10T20:00:00+00:00",
    )
    current = review_state(registry, "naija-review-v0.1")[0]
    assert cultural_validation_is_current(current) is True

    messages = list(current["messages"])
    messages = [dict(message) for message in messages]
    messages[2]["content"] = "The transfer dey pending for now."
    create_revision(
        registry,
        "naija-review-v0.1",
        record_id,
        messages,
        "naija-cultural-01",
        now=lambda: "2026-08-10T20:01:00+00:00",
    )
    revised = review_state(registry, "naija-review-v0.1")[0]
    assert revised["review_status"] == "draft"
    assert revised["culturally_validated"] is False
    assert revised["cultural_review_record_sha256"] == ""
    assert cultural_validation_is_current(revised) is False


def test_hash_bound_cultural_metadata_cannot_be_reused_on_changed_content():
    row = stage_trust_fixture_records([_fixture()], source_path="fixture.jsonl")[0]
    row.update(
        dataset_version="naija-review-v0.1",
        revision=1,
        review_status="approved",
        technical_review_completed=True,
        domain_review_completed=True,
        culturally_validated=True,
        cultural_review_completed=True,
        cultural_reviewer="naija-cultural-01",
        cultural_review_timestamp="2026-08-10T20:00:00+00:00",
    )
    row["example_sha256"] = example_sha256(row)
    row["cultural_review_record_sha256"] = row["example_sha256"]
    assert cultural_validation_is_current(row) is True

    row["messages"][2]["content"] = "Changed content"
    row["example_sha256"] = example_sha256(row)
    assert cultural_validation_is_current(row) is False
    assert "cultural_validation_incomplete" in assess_eligibility(row, "naija-review-v0.1").reasons
