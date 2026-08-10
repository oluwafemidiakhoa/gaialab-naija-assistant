"""Thin provider SDK wrappers outside the deterministic Trust Rail core.

These factories accept already-configured SDK clients or local inference
callables and return the provider-neutral ``ProviderAdapter`` contract. The
module deliberately does not import vendor SDK packages or read credentials.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Callable

from src.provider_adapters import ProviderAdapter


PROVIDER_SDK_WRAPPER_VERSION = "gaialab-naija-provider-sdk-wrappers/0.1.0"


def _value(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _plain_mapping(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    if hasattr(value, "model_dump"):
        dumped = value.model_dump()
        if isinstance(dumped, Mapping):
            return {str(key): item for key, item in dumped.items()}
    if hasattr(value, "to_dict"):
        dumped = value.to_dict()
        if isinstance(dumped, Mapping):
            return {str(key): item for key, item in dumped.items()}
    result: dict[str, Any] = {}
    for name in ("input_tokens", "output_tokens", "total_tokens", "prompt_tokens", "completion_tokens"):
        item = getattr(value, name, None)
        if item is not None:
            result[name] = item
    return result


def _provider_options(
    request: Mapping[str, Any],
    defaults: Mapping[str, Any] | None,
    allowed: frozenset[str],
) -> dict[str, Any]:
    result = {
        str(key): value
        for key, value in dict(defaults or {}).items()
        if str(key) in allowed
    }
    supplied = request.get("provider_options") or {}
    if not isinstance(supplied, Mapping):
        raise ValueError("provider_options must be an object")
    for key, value in supplied.items():
        name = str(key)
        if name in allowed:
            result[name] = value
    return result


def _input_value(request: Mapping[str, Any]) -> Any:
    for key in ("input", "prompt"):
        value = request.get(key)
        if value not in (None, ""):
            return value
    messages = request.get("messages")
    if messages:
        return messages
    user_message = request.get("user_message")
    if user_message not in (None, ""):
        return str(user_message)
    raise ValueError("provider request requires input, prompt, messages, or user_message")


def _text_messages(request: Mapping[str, Any]) -> tuple[str | None, list[dict[str, str]]]:
    raw_messages = request.get("messages")
    if raw_messages is None:
        prompt = _input_value(request)
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("text-message provider request requires string input")
        return None, [{"role": "user", "content": prompt.strip()}]
    if isinstance(raw_messages, (str, bytes)) or not isinstance(raw_messages, Sequence):
        raise ValueError("messages must be a sequence")

    system_parts: list[str] = []
    messages: list[dict[str, str]] = []
    for item in raw_messages:
        if not isinstance(item, Mapping):
            raise ValueError("each message must be an object")
        role = str(item.get("role") or "").strip().lower()
        content = item.get("content")
        if role not in {"system", "user", "assistant"}:
            raise ValueError(f"unsupported message role: {role}")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("message content must be non-empty text")
        if role == "system":
            system_parts.append(content.strip())
        else:
            messages.append({"role": role, "content": content.strip()})
    if not messages:
        raise ValueError("provider request requires at least one non-system message")
    return ("\n\n".join(system_parts) or None), messages


def openai_responses_adapter(
    *,
    client: Any,
    model_name: str,
    model_version: str | None = None,
    default_options: Mapping[str, Any] | None = None,
) -> ProviderAdapter:
    """Wrap an already-configured OpenAI client using the Responses API."""
    allowed = frozenset({"max_output_tokens", "temperature", "top_p", "store"})

    def generate(request: Mapping[str, Any]) -> Any:
        kwargs = {
            "model": model_name,
            "input": _input_value(request),
            **_provider_options(request, default_options, allowed),
        }
        instructions = request.get("instructions")
        if isinstance(instructions, str) and instructions.strip():
            kwargs["instructions"] = instructions.strip()
        return client.responses.create(**kwargs)

    def metadata(raw: Any) -> Mapping[str, Any]:
        return {
            "wrapper_version": PROVIDER_SDK_WRAPPER_VERSION,
            "response_id": _value(raw, "id"),
            "status": _value(raw, "status"),
            "response_model": _value(raw, "model"),
            "usage": _plain_mapping(_value(raw, "usage")),
        }

    return ProviderAdapter(
        provider="openai",
        model_name=model_name,
        model_version=model_version,
        generate=generate,
        extract_text=lambda raw: str(_value(raw, "output_text") or ""),
        extract_metadata=metadata,
    )


def anthropic_messages_adapter(
    *,
    client: Any,
    model_name: str,
    max_tokens: int = 1024,
    model_version: str | None = None,
    default_options: Mapping[str, Any] | None = None,
) -> ProviderAdapter:
    """Wrap an already-configured Anthropic client using Messages API."""
    if max_tokens <= 0:
        raise ValueError("max_tokens must be positive")
    allowed = frozenset({"temperature", "top_p", "top_k", "stop_sequences"})

    def generate(request: Mapping[str, Any]) -> Any:
        system, messages = _text_messages(request)
        kwargs = {
            "model": model_name,
            "max_tokens": max_tokens,
            "messages": messages,
            **_provider_options(request, default_options, allowed),
        }
        if system:
            kwargs["system"] = system
        return client.messages.create(**kwargs)

    def text(raw: Any) -> str:
        parts: list[str] = []
        content = _value(raw, "content", []) or []
        for item in content:
            if _value(item, "type") == "text":
                value = _value(item, "text")
                if value:
                    parts.append(str(value))
        return "\n".join(parts)

    def metadata(raw: Any) -> Mapping[str, Any]:
        return {
            "wrapper_version": PROVIDER_SDK_WRAPPER_VERSION,
            "response_id": _value(raw, "id"),
            "stop_reason": _value(raw, "stop_reason"),
            "response_model": _value(raw, "model"),
            "usage": _plain_mapping(_value(raw, "usage")),
        }

    return ProviderAdapter(
        provider="anthropic",
        model_name=model_name,
        model_version=model_version,
        generate=generate,
        extract_text=text,
        extract_metadata=metadata,
    )


def gemini_interactions_adapter(
    *,
    client: Any,
    model_name: str,
    model_version: str | None = None,
    default_options: Mapping[str, Any] | None = None,
) -> ProviderAdapter:
    """Wrap a Google GenAI client using the current Interactions API."""
    allowed = frozenset({"temperature", "top_p", "max_output_tokens"})

    def generate(request: Mapping[str, Any]) -> Any:
        kwargs = {
            "model": model_name,
            "input": _input_value(request),
            **_provider_options(request, default_options, allowed),
        }
        return client.interactions.create(**kwargs)

    def metadata(raw: Any) -> Mapping[str, Any]:
        return {
            "wrapper_version": PROVIDER_SDK_WRAPPER_VERSION,
            "response_id": _value(raw, "id"),
            "status": _value(raw, "status"),
            "response_model": _value(raw, "model"),
            "usage": _plain_mapping(_value(raw, "usage")),
        }

    return ProviderAdapter(
        provider="gemini",
        model_name=model_name,
        model_version=model_version,
        generate=generate,
        extract_text=lambda raw: str(_value(raw, "output_text") or ""),
        extract_metadata=metadata,
    )


def qwen_dashscope_adapter(
    *,
    generation: Any,
    model_name: str,
    model_version: str | None = None,
    default_options: Mapping[str, Any] | None = None,
) -> ProviderAdapter:
    """Wrap DashScope ``Generation`` without importing the DashScope SDK."""
    allowed = frozenset({"temperature", "top_p", "top_k", "max_tokens", "seed"})

    def generate(request: Mapping[str, Any]) -> Any:
        _, messages = _text_messages(request)
        kwargs = {
            "model": model_name,
            "messages": messages,
            "result_format": "message",
            **_provider_options(request, default_options, allowed),
        }
        return generation.call(**kwargs)

    def text(raw: Any) -> str:
        output = _value(raw, "output", {}) or {}
        choices = _value(output, "choices", []) or []
        if not choices:
            return ""
        message = _value(choices[0], "message", {}) or {}
        content = _value(message, "content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, Sequence) and not isinstance(content, (str, bytes)):
            parts: list[str] = []
            for item in content:
                value = _value(item, "text")
                if value:
                    parts.append(str(value))
            return "\n".join(parts)
        return ""

    def metadata(raw: Any) -> Mapping[str, Any]:
        return {
            "wrapper_version": PROVIDER_SDK_WRAPPER_VERSION,
            "request_id": _value(raw, "request_id"),
            "status_code": _value(raw, "status_code"),
            "code": _value(raw, "code"),
            "usage": _plain_mapping(_value(raw, "usage")),
        }

    return ProviderAdapter(
        provider="qwen",
        model_name=model_name,
        model_version=model_version,
        generate=generate,
        extract_text=text,
        extract_metadata=metadata,
    )


def natlas_local_adapter(
    *,
    inference: Callable[..., Any],
    model_name: str = "NCAIR1/N-ATLaS",
    model_version: str | None = None,
    default_options: Mapping[str, Any] | None = None,
) -> ProviderAdapter:
    """Wrap local/Hugging Face-style N-ATLAS inference as a Trust Rail adapter."""
    allowed = frozenset({"max_new_tokens", "temperature", "top_p", "do_sample"})

    def generate(request: Mapping[str, Any]) -> Any:
        return inference(
            _input_value(request),
            **_provider_options(request, default_options, allowed),
        )

    def text(raw: Any) -> str:
        value = raw
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            if not value:
                return ""
            value = value[0]
        generated = _value(value, "generated_text", value)
        if isinstance(generated, str):
            return generated
        if isinstance(generated, Sequence) and not isinstance(generated, (str, bytes)):
            for item in reversed(generated):
                if _value(item, "role") == "assistant" and _value(item, "content"):
                    return str(_value(item, "content"))
        return ""

    return ProviderAdapter(
        provider="n-atlas",
        model_name=model_name,
        model_version=model_version,
        generate=generate,
        extract_text=text,
        extract_metadata=lambda _raw: {
            "wrapper_version": PROVIDER_SDK_WRAPPER_VERSION,
            "transport": "local_inference",
        },
    )
