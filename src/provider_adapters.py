"""Model-agnostic provider adapters for GaiaLab Naija Trust Rail.

Provider SDK/network details stay outside this module. Applications inject a
provider generation callable and a text extractor, while Trust Rail owns the
normalized candidate contract and pre-delivery verification boundary.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from typing import Any, Callable, Mapping


SUPPORTED_PROVIDER_KINDS = frozenset(
    {"openai", "anthropic", "gemini", "qwen", "n-atlas", "private", "local", "custom"}
)


@dataclass(frozen=True)
class CandidateResponse:
    provider: str
    model_name: str
    model_version: str | None
    text: str
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ProviderAdapterError(RuntimeError):
    """Raised when a provider adapter cannot produce a safe normalized candidate."""


class ProviderAdapter:
    """Injectable provider boundary without vendor SDK coupling."""

    def __init__(
        self,
        *,
        provider: str,
        model_name: str,
        generate: Callable[[Mapping[str, Any]], Any],
        extract_text: Callable[[Any], str],
        model_version: str | None = None,
        extract_metadata: Callable[[Any], Mapping[str, Any]] | None = None,
    ):
        provider_name = str(provider).strip().lower()
        if provider_name not in SUPPORTED_PROVIDER_KINDS:
            raise ValueError(f"unsupported provider kind: {provider_name}")
        if not str(model_name).strip():
            raise ValueError("model_name must not be empty")
        self.provider = provider_name
        self.model_name = str(model_name).strip()
        self.model_version = model_version
        self._generate = generate
        self._extract_text = extract_text
        self._extract_metadata = extract_metadata

    def generate_candidate(self, request: Mapping[str, Any]) -> CandidateResponse:
        try:
            raw = self._generate(dict(request))
            text = str(self._extract_text(raw) or "").strip()
            metadata = dict(self._extract_metadata(raw) if self._extract_metadata else {})
        except Exception as exc:
            raise ProviderAdapterError(
                f"provider {self.provider} generation failed: {type(exc).__name__}"
            ) from exc
        if not text:
            raise ProviderAdapterError(f"provider {self.provider} returned an empty candidate")
        return CandidateResponse(
            provider=self.provider,
            model_name=self.model_name,
            model_version=self.model_version,
            text=text,
            metadata=_sanitize_metadata(metadata),
        )


class ProviderAdapterRegistry:
    def __init__(self):
        self._adapters: dict[str, ProviderAdapter] = {}

    def register(self, name: str, adapter: ProviderAdapter) -> None:
        key = str(name).strip().lower()
        if not key:
            raise ValueError("adapter name must not be empty")
        if key in self._adapters:
            raise ValueError(f"provider adapter already registered: {key}")
        self._adapters[key] = adapter

    def get(self, name: str) -> ProviderAdapter:
        key = str(name).strip().lower()
        try:
            return self._adapters[key]
        except KeyError as exc:
            raise KeyError(f"unknown provider adapter: {key}") from exc

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._adapters))


_FORBIDDEN_METADATA_PARTS = (
    "password",
    "secret",
    "token",
    "api_key",
    "private_key",
    "authorization",
    "cookie",
)


def _sanitize_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    sanitized: dict[str, Any] = {}
    for key, value in metadata.items():
        lowered = str(key).lower()
        if any(part in lowered for part in _FORBIDDEN_METADATA_PARTS):
            continue
        if isinstance(value, Mapping):
            sanitized[str(key)] = _sanitize_metadata(value)
        elif isinstance(value, (str, int, float, bool)) or value is None:
            sanitized[str(key)] = value
    return sanitized


def candidate_hash(candidate: CandidateResponse) -> str:
    core = {
        "provider": candidate.provider,
        "model_name": candidate.model_name,
        "model_version": candidate.model_version,
        "text": candidate.text,
    }
    payload = json.dumps(core, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def verify_provider_candidate(
    *,
    adapter: ProviderAdapter,
    provider_request: Mapping[str, Any],
    trust_context: Mapping[str, Any] | None = None,
    verify_fn: Callable[[Mapping[str, Any]], dict[str, Any]],
) -> dict[str, Any]:
    """Generate one candidate and run Trust Rail before automated delivery.

    Only `ALLOW` is considered automatically deliverable. VERIFY/REWRITE/
    ESCALATE/BLOCK remain held for the caller's verification or human workflow.
    """
    candidate = adapter.generate_candidate(provider_request)
    context = dict(trust_context or {})
    trust_payload = {
        **context,
        "assistant_response": candidate.text,
        "model_name": f"{candidate.provider}/{candidate.model_name}",
        "model_version": candidate.model_version,
    }
    trust_result = verify_fn(trust_payload)
    disposition = str(trust_result.get("disposition") or "BLOCK")
    return {
        "candidate": {
            "provider": candidate.provider,
            "model_name": candidate.model_name,
            "model_version": candidate.model_version,
            "candidate_sha256": candidate_hash(candidate),
            "metadata": candidate.metadata,
        },
        "trust": trust_result,
        "delivery": {
            "automated_delivery_allowed": disposition == "ALLOW",
            "disposition": disposition,
        },
    }
