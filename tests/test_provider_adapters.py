import pytest

from src.provider_adapters import (
    ProviderAdapter,
    ProviderAdapterError,
    ProviderAdapterRegistry,
    SUPPORTED_PROVIDER_KINDS,
    verify_provider_candidate,
)
from src.trust_api import verify_payload


def _adapter(provider, text, *, metadata=None):
    return ProviderAdapter(
        provider=provider,
        model_name="example-model",
        model_version="2026-08",
        generate=lambda request: {"text": text, "metadata": metadata or {}, "request": dict(request)},
        extract_text=lambda raw: raw["text"],
        extract_metadata=lambda raw: raw["metadata"],
    )


@pytest.mark.parametrize(
    "provider",
    ["openai", "anthropic", "gemini", "qwen", "n-atlas", "private", "local", "custom"],
)
def test_supported_providers_share_one_candidate_contract(provider):
    adapter = _adapter(provider, "The transfer is still pending.")
    result = verify_provider_candidate(
        adapter=adapter,
        provider_request={"messages": [{"role": "user", "content": "Status?"}]},
        trust_context={"authoritative_state": {"transaction_status": "pending"}},
        verify_fn=verify_payload,
    )
    assert result["candidate"]["provider"] == provider
    assert result["candidate"]["model_name"] == "example-model"
    assert len(result["candidate"]["candidate_sha256"]) == 64
    assert result["trust"]["verification_receipt"]["model_name"] == f"{provider}/example-model"
    assert result["delivery"] == {"automated_delivery_allowed": True, "disposition": "ALLOW"}


def test_contradicted_provider_candidate_is_held_before_delivery():
    adapter = _adapter("openai", "The transfer was successful.")
    result = verify_provider_candidate(
        adapter=adapter,
        provider_request={},
        trust_context={"authoritative_state": {"transaction_status": "pending"}},
        verify_fn=verify_payload,
    )
    assert result["trust"]["disposition"] == "BLOCK"
    assert result["delivery"]["automated_delivery_allowed"] is False


def test_rewrite_or_verify_is_not_automatically_deliverable():
    adapter = _adapter("gemini", "They deducted N100 as a charge.")
    result = verify_provider_candidate(
        adapter=adapter,
        provider_request={},
        trust_context={},
        verify_fn=verify_payload,
    )
    assert result["delivery"]["disposition"] in {"VERIFY", "REWRITE", "ESCALATE", "BLOCK"}
    assert result["delivery"]["automated_delivery_allowed"] is False


def test_provider_metadata_drops_secret_like_fields():
    adapter = _adapter(
        "anthropic",
        "The transfer is still pending.",
        metadata={
            "request_id": "req_123",
            "usage": {"input": 10, "output": 5},
            "api_key": "must-not-survive",
            "auth_token": "must-not-survive",
        },
    )
    candidate = adapter.generate_candidate({})
    assert candidate.metadata == {"request_id": "req_123", "usage": {"input": 10, "output": 5}}


def test_empty_provider_candidate_fails_closed():
    adapter = _adapter("qwen", "   ")
    with pytest.raises(ProviderAdapterError, match="empty candidate"):
        adapter.generate_candidate({})


def test_provider_exception_is_normalized_without_leaking_message():
    def _boom(_request):
        raise RuntimeError("secret provider detail")

    adapter = ProviderAdapter(
        provider="private",
        model_name="internal-model",
        generate=_boom,
        extract_text=lambda raw: str(raw),
    )
    with pytest.raises(ProviderAdapterError) as exc:
        adapter.generate_candidate({})
    assert "RuntimeError" in str(exc.value)
    assert "secret provider detail" not in str(exc.value)


def test_registry_prevents_ambiguous_duplicate_adapter_names():
    registry = ProviderAdapterRegistry()
    registry.register("primary", _adapter("openai", "The transfer is still pending."))
    assert registry.names() == ("primary",)
    with pytest.raises(ValueError, match="already registered"):
        registry.register("primary", _adapter("gemini", "The transfer is still pending."))


def test_supported_provider_set_is_explicit():
    assert {"openai", "anthropic", "gemini", "qwen", "n-atlas", "private"} <= SUPPORTED_PROVIDER_KINDS
