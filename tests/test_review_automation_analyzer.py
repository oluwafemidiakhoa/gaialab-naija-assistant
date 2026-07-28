from __future__ import annotations

from copy import deepcopy

from src.dataset_management import example_sha256
from src.review_automation.analyzer import ReviewAnalyzer
from src.review_automation.config import load_review_config
from src.review_automation.models import RecommendationCategory
from src.review_automation.providers import MockReviewProvider


def record(category="small_business", risk="low") -> dict:
    value = {
        "id": "v06-test-001",
        "dataset_version": "v0.6",
        "revision": 1,
        "category": category,
        "risk_level": risk,
        "source": "synthetic",
        "license": "CC0-1.0",
        "review_status": "draft",
        "messages": [
            {"role": "system", "content": "Be safe."},
            {"role": "user", "content": "Write a polite supplier follow-up."},
            {
                "role": "assistant",
                "content": "Good day. Please confirm the delivery date. Thank you.",
            },
        ],
    }
    value["example_sha256"] = example_sha256(value)
    return value


def provider_output() -> dict:
    return {
        "summary": "Clear supplier follow-up.",
        "language_grammar_findings": [],
        "safety_findings": [],
        "factuality_concerns": [],
        "cultural_context_concerns": [],
        "pidgin_authenticity_concerns": [],
        "ambiguity_findings": [],
        "unsupported_claim_indicators": [],
        "missing_citation_indicators": [],
        "high_risk_domain_indicators": [],
        "suggested_revision": None,
        "rationale": "The wording is concise.",
        "confidence_score": 90,
        "recommendation": "approve_candidate",
    }


def test_local_analysis_is_advisory_and_does_not_mutate_status() -> None:
    value = record()
    before = deepcopy(value)
    result = ReviewAnalyzer(load_review_config()).analyze(
        value, records=[value], generated_at="2026-07-28T12:00:00+00:00"
    )
    assert value == before
    assert result.recommendation == RecommendationCategory.APPROVE_CANDIDATE
    assert result.technical_review_required
    assert result.provider == "local"
    assert len(result.recommendation_hash) == 64


def test_domain_record_is_escalated_not_approved() -> None:
    value = record("healthcare", "medium")
    result = ReviewAnalyzer(load_review_config()).analyze(
        value, records=[value], generated_at="2026-07-28T12:00:00+00:00"
    )
    assert result.recommendation == RecommendationCategory.ESCALATE_DOMAIN
    assert result.domain_review_required


def test_valid_mock_provider_is_structured_and_labelled() -> None:
    value = record()
    result = ReviewAnalyzer(
        load_review_config(), provider=MockReviewProvider(provider_output())
    ).analyze(
        value, records=[value], generated_at="2026-07-28T12:00:00+00:00"
    )
    assert result.provider == "mock"
    assert result.model_name == "mock-structured-review"
    assert result.rationale.startswith("Provider-generated advisory")


def test_provider_failure_falls_back_without_exposing_error() -> None:
    value = record()
    provider = MockReviewProvider(error=RuntimeError("secret-token-value"))
    result = ReviewAnalyzer(load_review_config(), provider=provider).analyze(
        value, records=[value], generated_at="2026-07-28T12:00:00+00:00"
    )
    assert result.provider == "local_fallback"
    assert "secret-token-value" not in result.rationale
    assert provider.calls == 1


def test_malformed_provider_output_falls_back() -> None:
    value = record()
    provider = MockReviewProvider({"recommendation": "approved"})
    result = ReviewAnalyzer(load_review_config(), provider=provider).analyze(
        value, records=[value], generated_at="2026-07-28T12:00:00+00:00"
    )
    assert result.provider == "local_fallback"
    assert result.recommendation == RecommendationCategory.APPROVE_CANDIDATE


def test_suggested_revision_does_not_overwrite_source() -> None:
    value = record(risk="high")
    value["messages"][2]["content"] = "Try this"
    value["example_sha256"] = example_sha256(value)
    original = deepcopy(value)
    result = ReviewAnalyzer(load_review_config()).analyze(
        value, records=[value], generated_at="2026-07-28T12:00:00+00:00"
    )
    assert result.suggested_revision is not None
    assert result.suggested_revision.response.endswith(".")
    assert value == original
