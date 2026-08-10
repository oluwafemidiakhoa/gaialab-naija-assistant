from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.provider_adapters import ProviderAdapterError, verify_provider_candidate
from src.provider_sdk_wrappers import (
    anthropic_messages_adapter,
    gemini_interactions_adapter,
    natlas_local_adapter,
    openai_responses_adapter,
    qwen_dashscope_adapter,
)
from src.trust_api import verify_payload


class _Recorder:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


class _GenerationRecorder:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def call(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


def test_openai_responses_wrapper_normalizes_and_gates_delivery():
    responses = _Recorder(SimpleNamespace(
        id="resp_1",
        status="completed",
        model="gpt-example",
        output_text="The transfer is still pending.",
        usage=SimpleNamespace(input_tokens=10, output_tokens=6, total_tokens=16),
    ))
    client = SimpleNamespace(responses=responses)
    adapter = openai_responses_adapter(
        client=client,
        model_name="gpt-example",
        default_options={"temperature": 0.2, "api_key": "never-forward"},
    )
    result = verify_provider_candidate(
        adapter=adapter,
        provider_request={
            "input": "Status?",
            "provider_options": {"top_p": 0.8, "authorization": "drop"},
        },
        trust_context={"authoritative_state": {"transaction_status": "pending"}},
        verify_fn=verify_payload,
    )
    assert responses.calls == [{
        "model": "gpt-example",
        "input": "Status?",
        "temperature": 0.2,
        "top_p": 0.8,
    }]
    assert result["candidate"]["provider"] == "openai"
    assert result["candidate"]["metadata"]["response_id"] == "resp_1"
    assert result["candidate"]["metadata"]["usage"]["total_tokens"] == 16
    assert result["delivery"] == {
        "automated_delivery_allowed": True,
        "disposition": "ALLOW",
    }


def test_anthropic_wrapper_separates_system_and_messages():
    messages = _Recorder(SimpleNamespace(
        id="msg_1",
        model="claude-example",
        stop_reason="end_turn",
        usage=SimpleNamespace(input_tokens=12, output_tokens=5),
        content=[
            SimpleNamespace(type="text", text="The transfer is still pending."),
        ],
    ))
    client = SimpleNamespace(messages=messages)
    adapter = anthropic_messages_adapter(
        client=client,
        model_name="claude-example",
        max_tokens=200,
    )
    candidate = adapter.generate_candidate({
        "messages": [
            {"role": "system", "content": "Be precise."},
            {"role": "user", "content": "Status?"},
        ],
        "provider_options": {"temperature": 0.1, "api_key": "drop"},
    })
    assert messages.calls == [{
        "model": "claude-example",
        "max_tokens": 200,
        "messages": [{"role": "user", "content": "Status?"}],
        "temperature": 0.1,
        "system": "Be precise.",
    }]
    assert candidate.text == "The transfer is still pending."
    assert candidate.metadata["stop_reason"] == "end_turn"


def test_gemini_interactions_wrapper_uses_output_text():
    interactions = _Recorder(SimpleNamespace(
        id="interaction_1",
        status="completed",
        model="gemini-example",
        output_text="The transfer is still pending.",
        usage={"total_tokens": 8},
    ))
    client = SimpleNamespace(interactions=interactions)
    adapter = gemini_interactions_adapter(client=client, model_name="gemini-example")
    candidate = adapter.generate_candidate({"prompt": "Status?"})
    assert interactions.calls == [{"model": "gemini-example", "input": "Status?"}]
    assert candidate.text == "The transfer is still pending."
    assert candidate.metadata["response_id"] == "interaction_1"


def test_qwen_dashscope_wrapper_extracts_message_content():
    generation = _GenerationRecorder({
        "request_id": "qwen_req_1",
        "status_code": 200,
        "usage": {"input_tokens": 5, "output_tokens": 4},
        "output": {
            "choices": [
                {"message": {"role": "assistant", "content": "The transfer is still pending."}}
            ]
        },
    })
    adapter = qwen_dashscope_adapter(
        generation=generation,
        model_name="qwen-example",
        default_options={"top_p": 0.9},
    )
    candidate = adapter.generate_candidate({
        "messages": [{"role": "user", "content": "Status?"}],
    })
    assert generation.calls == [{
        "model": "qwen-example",
        "messages": [{"role": "user", "content": "Status?"}],
        "result_format": "message",
        "top_p": 0.9,
    }]
    assert candidate.text == "The transfer is still pending."
    assert candidate.metadata["request_id"] == "qwen_req_1"


def test_natlas_local_wrapper_supports_pipeline_style_output():
    calls = []

    def inference(value, **kwargs):
        calls.append((value, kwargs))
        return [{"generated_text": "The transfer is still pending."}]

    adapter = natlas_local_adapter(
        inference=inference,
        default_options={"max_new_tokens": 80, "token": "drop"},
    )
    candidate = adapter.generate_candidate({"user_message": "Status?"})
    assert calls == [("Status?", {"max_new_tokens": 80})]
    assert candidate.provider == "n-atlas"
    assert candidate.text == "The transfer is still pending."
    assert candidate.metadata["transport"] == "local_inference"


def test_wrapper_empty_output_still_fails_closed():
    responses = _Recorder(SimpleNamespace(output_text="   "))
    adapter = openai_responses_adapter(
        client=SimpleNamespace(responses=responses),
        model_name="gpt-example",
    )
    with pytest.raises(ProviderAdapterError, match="empty candidate"):
        adapter.generate_candidate({"input": "Status?"})


def test_unknown_provider_options_are_not_forwarded():
    interactions = _Recorder(SimpleNamespace(output_text="The transfer is still pending."))
    adapter = gemini_interactions_adapter(
        client=SimpleNamespace(interactions=interactions),
        model_name="gemini-example",
    )
    adapter.generate_candidate({
        "input": "Status?",
        "provider_options": {
            "temperature": 0.2,
            "api_key": "secret",
            "arbitrary_transport_escape": True,
        },
    })
    assert interactions.calls == [{
        "model": "gemini-example",
        "input": "Status?",
        "temperature": 0.2,
    }]


def test_contradicted_openai_candidate_remains_blocked_by_trust_rail():
    responses = _Recorder(SimpleNamespace(output_text="The transfer was successful."))
    adapter = openai_responses_adapter(
        client=SimpleNamespace(responses=responses),
        model_name="gpt-example",
    )
    result = verify_provider_candidate(
        adapter=adapter,
        provider_request={"input": "Status?"},
        trust_context={"authoritative_state": {"transaction_status": "pending"}},
        verify_fn=verify_payload,
    )
    assert result["delivery"]["disposition"] == "BLOCK"
    assert result["delivery"]["automated_delivery_allowed"] is False
