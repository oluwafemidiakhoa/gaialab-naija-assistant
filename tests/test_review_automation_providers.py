from __future__ import annotations

import pytest

from src.review_automation.providers import (
    CallableJSONProvider,
    ProviderRequest,
    ReviewProviderError,
)


def request() -> ProviderRequest:
    return ProviderRequest(
        prompt_version="gaialab-review-v1",
        prompt_template="Return JSON.",
        record_id="v06-test-001",
        category="small_business",
        risk_level="low",
        user_text="Write a follow-up.",
        assistant_text="Good day.",
    )


def test_callable_provider_parses_json_and_retries() -> None:
    calls = 0

    def evaluator(payload):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ConnectionError("private provider detail")
        return '{"summary": "ok"}'

    provider = CallableJSONProvider(
        evaluator, name="test", model_name="test-model",
        timeout_seconds=1, maximum_retry_count=1,
    )
    assert provider.generate(request()) == {"summary": "ok"}
    assert calls == 2


def test_provider_errors_are_redacted() -> None:
    def evaluator(payload):
        raise RuntimeError("api-key-secret-value")

    provider = CallableJSONProvider(
        evaluator, name="test", model_name="test-model",
        timeout_seconds=1, maximum_retry_count=0,
    )
    with pytest.raises(ReviewProviderError) as captured:
        provider.generate(request())
    assert "api-key-secret-value" not in str(captured.value)
