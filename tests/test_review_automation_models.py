from __future__ import annotations

from dataclasses import replace

import pytest

from src.review_automation.models import (
    ANALYZER_VERSION,
    AdvisoryRecommendation,
    AutomatedAuditEvent,
    HumanDecisionAuditEvent,
    RecommendationCategory,
    ReviewAutomationModelError,
    SuggestedRevision,
    canonical_sha256,
)


def recommendation(**overrides) -> AdvisoryRecommendation:
    values = {
        "record_id": "v06-test-001",
        "dataset_version": "v0.6",
        "record_revision": 1,
        "input_record_sha256": "a" * 64,
        "prompt_version": "gaialab-review-v1",
        "provider": "local",
        "model_name": "deterministic-rules",
        "generation_timestamp": "2026-07-28T12:00:00+00:00",
        "analyzer_version": ANALYZER_VERSION,
        "summary": "A concise business-writing example.",
        "quality_score": 82,
        "language_grammar_findings": (),
        "safety_findings": (),
        "factuality_concerns": (),
        "cultural_context_concerns": (),
        "pidgin_authenticity_concerns": (),
        "ambiguity_findings": (),
        "unsupported_claim_indicators": (),
        "missing_citation_indicators": (),
        "high_risk_domain_indicators": (),
        "duplicate_matches": (),
        "technical_review_required": True,
        "domain_review_required": False,
        "suggested_revision": SuggestedRevision(
            prompt="Write a polite payment reminder.",
            response="Good day. Kindly settle the outstanding invoice. Thank you.",
            changes_summary=("Clarified the request.",),
            reasons=("Improve specificity.",),
            safety_impact="No material change.",
            factuality_impact="No new factual claim.",
            cultural_context_impact="Retains clear Nigerian business English.",
        ),
        "rationale": "Clear and safe, but still requires human technical review.",
        "confidence_score": 88,
        "recommendation": RecommendationCategory.REVISE_CANDIDATE,
    }
    values.update(overrides)
    return AdvisoryRecommendation.create(**values)


def test_recommendation_hash_is_deterministic() -> None:
    assert recommendation() == recommendation()
    assert len(recommendation().recommendation_hash) == 64


def test_recommendation_hash_detects_mutation() -> None:
    original = recommendation()
    with pytest.raises(ReviewAutomationModelError, match="does not match"):
        replace(original, summary="Altered after hashing")


def test_no_recommendation_category_is_final_human_approval() -> None:
    values = {category.value for category in RecommendationCategory}
    assert "approved" not in values
    assert "rejected" not in values
    assert values == {
        "approve_candidate",
        "revise_candidate",
        "reject_candidate",
        "escalate_for_domain_review",
        "escalate_for_safety_review",
    }


def test_invalid_recommendation_output_fails_schema_validation() -> None:
    with pytest.raises(ReviewAutomationModelError, match="invalid recommendation"):
        recommendation(recommendation="approved")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("quality_score", True),
        ("confidence_score", "high"),
        ("language_grammar_findings", ["not", "a", "tuple"]),
        ("duplicate_matches", ({"record_id": "wrong type"},)),
    ],
)
def test_malformed_structured_values_are_rejected(field, value) -> None:
    with pytest.raises(ReviewAutomationModelError):
        recommendation(**{field: value})


def test_ai_and_human_audit_events_cannot_be_confused() -> None:
    common = {
        "event_id": "event-1",
        "dataset_version": "v0.6",
        "record_id": "v06-test-001",
        "record_revision": 1,
        "record_sha256": "a" * 64,
        "timestamp": "2026-07-28T12:00:00+00:00",
    }
    automated_values = {
        **common,
        "event_type": "automated_recommendation",
        "analyzer_version": ANALYZER_VERSION,
        "prompt_version": "gaialab-review-v1",
        "provider": "local",
        "model_name": "deterministic-rules",
        "recommendation": RecommendationCategory.APPROVE_CANDIDATE,
        "confidence": 80,
        "findings_summary": (),
        "recommendation_hash": "c" * 64,
    }
    automated = AutomatedAuditEvent(
        **automated_values,
        event_sha256=canonical_sha256({
            **automated_values,
            "recommendation": "approve_candidate",
        }),
    )
    human_values = {
        **common,
        "event_type": "human_decision",
        "reviewer_identifier": "reviewer-01",
        "reviewer_role": "technical_reviewer",
        "action": "request_revision",
        "decision_note": "Clarify the response.",
        "prior_status": "automated_reviewed",
        "new_status": "needs_revision",
        "related_recommendation_id": "recommendation-01",
    }
    human = HumanDecisionAuditEvent(
        **human_values,
        event_sha256=canonical_sha256(human_values),
    )
    assert automated.event_type != human.event_type
    with pytest.raises(ReviewAutomationModelError):
        replace(automated, event_type="human_decision")
    with pytest.raises(ReviewAutomationModelError, match="does not match"):
        replace(human, action="approve")
