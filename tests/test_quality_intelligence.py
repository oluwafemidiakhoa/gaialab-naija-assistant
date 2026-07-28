from __future__ import annotations

import pytest

from src.quality_intelligence import (
    DeterministicQualityProvider,
    OptionalLLMQualityProvider,
    assess_records,
)


def row(record_id: str, user: str, assistant: str, category: str = "small_business", risk: str = "low") -> dict:
    return {
        "id": record_id,
        "category": category,
        "risk_level": risk,
        "example_sha256": record_id.ljust(64, "0")[:64],
        "messages": [
            {"role": "system", "content": "Be safe."},
            {"role": "user", "content": user},
            {"role": "assistant", "content": assistant},
        ],
    }


def test_quality_scoring_is_deterministic() -> None:
    record = row("one", "Draft a customer reply.", "Good afternoon. Thank you for contacting us.")
    first = DeterministicQualityProvider().assess(record, assessed_at="2026-01-01T00:00:00+00:00")
    second = DeterministicQualityProvider().assess(record, assessed_at="2026-01-01T00:00:00+00:00")
    assert first == second
    assert 0 <= first.overall_score <= 100


@pytest.mark.parametrize("secret", ["OTP", "PIN", "password", "CVV", "private key", "authentication token"])
def test_credential_solicitation_is_critical(secret: str) -> None:
    assessment = DeterministicQualityProvider().assess(
        row("one", "Help me.", f"Please send your {secret} so I can continue."),
        assessed_at="2026-01-01T00:00:00+00:00",
    )
    assert any(f["check"] == "credential_solicitation" and f["severity"] == "critical" for f in assessment.findings)
    assert assessment.recommended_action == "reject_candidate"


def test_near_duplicate_detection() -> None:
    records = [
        row("one", "Please confirm whether my transfer arrived.", "Check your official bank channel."),
        row("two", "Please confirm whether my transfer has arrived.", "Check through your official bank channel."),
    ]
    assessments = assess_records(records, assessed_at="2026-01-01T00:00:00+00:00")
    assert any(f["check"] == "near_duplicate_prompt" for f in assessments[0].findings)


def test_factual_categories_require_human_review_not_approval() -> None:
    assessment = DeterministicQualityProvider().assess(
        row("one", "How do I prepare?", "Check the current official guidance.", "government_services"),
        assessed_at="2026-01-01T00:00:00+00:00",
    )
    assert assessment.factual_review_required is True
    assert assessment.recommended_action != "approve"


def test_optional_llm_provider_is_disabled_by_default() -> None:
    with pytest.raises(RuntimeError, match="disabled"):
        OptionalLLMQualityProvider().assess(row("one", "Hi", "Hello there."))


def test_negated_financial_guarantee_is_a_safety_warning_not_a_claim() -> None:
    assessment = DeterministicQualityProvider().assess(
        row(
            "one",
            "Is this loan app guaranteed?",
            (
                "I cannot guarantee approval. Check the provider through official "
                "sources and speak with your bank if you are unsure."
            ),
            category="banking",
            risk="high",
        )
    )
    assert "financial_guarantee" not in {
        finding["check"] for finding in assessment.findings
    }


def test_caution_about_a_guarantee_is_not_a_guaranteed_outcome() -> None:
    assessment = DeterministicQualityProvider().assess(
        row(
            "one", "An agent guarantees admission.",
            "Treat the guarantee cautiously and confirm through the institution.",
            category="education",
        )
    )
    assert "guaranteed_outcome" not in {
        finding["check"] for finding in assessment.findings
    }
