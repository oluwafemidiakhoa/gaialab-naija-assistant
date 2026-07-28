"""Provider-neutral structured analysis with safe local fallback support."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol


class ReviewProviderError(RuntimeError):
    """A redacted provider failure that never includes provider response text."""


@dataclass(frozen=True)
class ProviderRequest:
    """Minimum data needed for advisory analysis; excludes private metadata."""

    prompt_version: str
    prompt_template: str
    record_id: str
    category: str
    risk_level: str
    user_text: str
    assistant_text: str

    def to_dict(self) -> dict[str, str]:
        return {
            "prompt_version": self.prompt_version,
            "prompt_template": self.prompt_template,
            "record_id": self.record_id,
            "category": self.category,
            "risk_level": self.risk_level,
            "user_text": self.user_text,
            "assistant_text": self.assistant_text,
        }


class ReviewProvider(Protocol):
    """Provider contract for structured advisory output."""

    name: str
    model_name: str
    externally_generated: bool

    def generate(self, request: ProviderRequest) -> Mapping[str, Any]: ...


class MockReviewProvider:
    """Deterministic provider for tests and offline integration exercises."""

    name = "mock"
    model_name = "mock-structured-review"
    externally_generated = False

    def __init__(
        self,
        response: Mapping[str, Any] | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self.response = dict(response or {})
        self.error = error
        self.calls = 0

    def generate(self, request: ProviderRequest) -> Mapping[str, Any]:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return dict(self.response)


class CallableJSONProvider:
    """Opt-in adapter for a caller-supplied external JSON function.

    The repository provides no network client and makes no external call unless a
    caller explicitly supplies and enables this adapter.
    """

    externally_generated = True

    def __init__(
        self,
        evaluator: Callable[[dict[str, str]], str | Mapping[str, Any]],
        *,
        name: str,
        model_name: str,
        timeout_seconds: float,
        maximum_retry_count: int,
    ) -> None:
        if not callable(evaluator):
            raise TypeError("evaluator must be callable")
        if not name.strip() or not model_name.strip():
            raise ValueError("provider name and model_name are required")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if maximum_retry_count < 0:
            raise ValueError("maximum_retry_count must not be negative")
        self._evaluator = evaluator
        self.name = name.strip()
        self.model_name = model_name.strip()
        self.timeout_seconds = timeout_seconds
        self.maximum_retry_count = maximum_retry_count

    def _attempt(self, request: ProviderRequest) -> Mapping[str, Any]:
        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(self._evaluator, request.to_dict())
        try:
            result = future.result(timeout=self.timeout_seconds)
        except FutureTimeout as exc:
            future.cancel()
            raise ReviewProviderError("provider timed out") from exc
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
        if isinstance(result, str):
            try:
                result = json.loads(result)
            except json.JSONDecodeError as exc:
                raise ReviewProviderError("provider returned malformed JSON") from exc
        if not isinstance(result, Mapping):
            raise ReviewProviderError("provider output must be a JSON object")
        return result

    def generate(self, request: ProviderRequest) -> Mapping[str, Any]:
        last_error = "provider failed"
        for _ in range(self.maximum_retry_count + 1):
            try:
                return self._attempt(request)
            except ReviewProviderError as exc:
                last_error = str(exc)
            except Exception as exc:  # Provider details and secrets are redacted.
                last_error = f"provider failed ({type(exc).__name__})"
        raise ReviewProviderError(last_error)
