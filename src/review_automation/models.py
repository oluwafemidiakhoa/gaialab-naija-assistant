"""Validated, deterministic models for advisory review automation."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, ClassVar


RECOMMENDATION_SCHEMA = "gaialab.advisory-review.v1"
ANALYZER_VERSION = "review-automation-1.0.0"
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class ReviewAutomationModelError(ValueError):
    """Raised when advisory or audit data violates its schema."""


class RecommendationCategory(StrEnum):
    """Allowed advisory outcomes; none is an official review decision."""

    APPROVE_CANDIDATE = "approve_candidate"
    REVISE_CANDIDATE = "revise_candidate"
    REJECT_CANDIDATE = "reject_candidate"
    ESCALATE_DOMAIN = "escalate_for_domain_review"
    ESCALATE_SAFETY = "escalate_for_safety_review"


def canonical_sha256(value: dict[str, Any]) -> str:
    """Hash stable UTF-8 JSON without platform-dependent whitespace."""
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _validate_sha256(value: str, field: str) -> None:
    if not SHA256_PATTERN.fullmatch(value):
        raise ReviewAutomationModelError(f"{field} must be a lowercase SHA-256")


def _validate_timestamp(value: str, field: str) -> None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ReviewAutomationModelError(f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ReviewAutomationModelError(f"{field} must include a timezone")


def _required_text(value: str, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ReviewAutomationModelError(f"{field} must not be empty")


@dataclass(frozen=True)
class DuplicateMatch:
    """Explain one exact, normalized, or near-duplicate relationship."""

    matched_record_id: str
    matched_record_sha256: str
    match_type: str
    similarity: float
    explanation: str

    def __post_init__(self) -> None:
        _required_text(self.matched_record_id, "matched_record_id")
        _validate_sha256(self.matched_record_sha256, "matched_record_sha256")
        if self.match_type not in {
            "exact", "normalized", "prompt", "answer", "prompt_answer", "near"
        }:
            raise ReviewAutomationModelError("invalid duplicate match_type")
        if not 0 <= self.similarity <= 1:
            raise ReviewAutomationModelError("similarity must be from 0 to 1")
        _required_text(self.explanation, "explanation")


@dataclass(frozen=True)
class SuggestedRevision:
    """A non-mutating proposal that requires an explicit human action."""

    prompt: str
    response: str
    changes_summary: tuple[str, ...]
    reasons: tuple[str, ...]
    safety_impact: str
    factuality_impact: str
    cultural_context_impact: str

    def __post_init__(self) -> None:
        _required_text(self.prompt, "suggested prompt")
        _required_text(self.response, "suggested response")
        if (
            not isinstance(self.changes_summary, tuple)
            or not self.changes_summary
            or not all(
                isinstance(item, str) and item.strip()
                for item in self.changes_summary
            )
        ):
            raise ReviewAutomationModelError("changes_summary must not be empty")
        if (
            not isinstance(self.reasons, tuple)
            or not self.reasons
            or not all(isinstance(item, str) and item.strip() for item in self.reasons)
        ):
            raise ReviewAutomationModelError("reasons must not be empty")
        for field, value in (
            ("safety_impact", self.safety_impact),
            ("factuality_impact", self.factuality_impact),
            ("cultural_context_impact", self.cultural_context_impact),
        ):
            _required_text(value, field)


@dataclass(frozen=True)
class AdvisoryRecommendation:
    """Traceable AI advice that cannot modify official review status."""

    record_id: str
    dataset_version: str
    record_revision: int
    input_record_sha256: str
    prompt_version: str
    provider: str
    model_name: str
    generation_timestamp: str
    analyzer_version: str
    summary: str
    quality_score: int
    language_grammar_findings: tuple[str, ...]
    safety_findings: tuple[str, ...]
    factuality_concerns: tuple[str, ...]
    cultural_context_concerns: tuple[str, ...]
    pidgin_authenticity_concerns: tuple[str, ...]
    ambiguity_findings: tuple[str, ...]
    unsupported_claim_indicators: tuple[str, ...]
    missing_citation_indicators: tuple[str, ...]
    high_risk_domain_indicators: tuple[str, ...]
    duplicate_matches: tuple[DuplicateMatch, ...]
    technical_review_required: bool
    domain_review_required: bool
    suggested_revision: SuggestedRevision | None
    rationale: str
    confidence_score: int
    recommendation: RecommendationCategory
    recommendation_hash: str

    HASH_FIELD: ClassVar[str] = "recommendation_hash"

    def __post_init__(self) -> None:
        _required_text(self.record_id, "record_id")
        _required_text(self.dataset_version, "dataset_version")
        if (
            isinstance(self.record_revision, bool)
            or not isinstance(self.record_revision, int)
            or self.record_revision < 1
        ):
            raise ReviewAutomationModelError("record_revision must be positive")
        _validate_sha256(self.input_record_sha256, "input_record_sha256")
        for field, value in (
            ("prompt_version", self.prompt_version),
            ("provider", self.provider),
            ("model_name", self.model_name),
            ("analyzer_version", self.analyzer_version),
            ("summary", self.summary),
            ("rationale", self.rationale),
        ):
            _required_text(value, field)
        _validate_timestamp(self.generation_timestamp, "generation_timestamp")
        if (
            isinstance(self.quality_score, bool)
            or not isinstance(self.quality_score, int)
            or not 0 <= self.quality_score <= 100
        ):
            raise ReviewAutomationModelError("quality_score must be from 0 to 100")
        if (
            isinstance(self.confidence_score, bool)
            or not isinstance(self.confidence_score, int)
            or not 0 <= self.confidence_score <= 100
        ):
            raise ReviewAutomationModelError(
                "confidence_score must be from 0 to 100"
            )
        if not isinstance(self.recommendation, RecommendationCategory):
            raise ReviewAutomationModelError("invalid recommendation category")
        finding_fields = (
            self.language_grammar_findings,
            self.safety_findings,
            self.factuality_concerns,
            self.cultural_context_concerns,
            self.pidgin_authenticity_concerns,
            self.ambiguity_findings,
            self.unsupported_claim_indicators,
            self.missing_citation_indicators,
            self.high_risk_domain_indicators,
        )
        if any(
            not isinstance(items, tuple)
            or not all(isinstance(item, str) and item.strip() for item in items)
            for items in finding_fields
        ):
            raise ReviewAutomationModelError(
                "finding collections must be tuples of non-empty strings"
            )
        if (
            not isinstance(self.duplicate_matches, tuple)
            or not all(
                isinstance(match, DuplicateMatch)
                for match in self.duplicate_matches
            )
        ):
            raise ReviewAutomationModelError(
                "duplicate_matches must contain DuplicateMatch values"
            )
        if self.suggested_revision is not None and not isinstance(
            self.suggested_revision, SuggestedRevision
        ):
            raise ReviewAutomationModelError(
                "suggested_revision must be a SuggestedRevision"
            )
        _validate_sha256(self.recommendation_hash, self.HASH_FIELD)
        if self.recommendation_hash != self.computed_hash():
            raise ReviewAutomationModelError("recommendation_hash does not match content")

    def payload(self) -> dict[str, Any]:
        """Return canonical serializable content without the integrity hash."""
        value = asdict(self)
        value.pop(self.HASH_FIELD)
        value["recommendation"] = self.recommendation.value
        return value

    def computed_hash(self) -> str:
        return canonical_sha256(self.payload())

    def to_dict(self) -> dict[str, Any]:
        return {**self.payload(), self.HASH_FIELD: self.recommendation_hash}

    @classmethod
    def create(cls, **values: Any) -> "AdvisoryRecommendation":
        """Construct and hash a recommendation after strict validation."""
        values = dict(values)
        recommendation = values.get("recommendation")
        if isinstance(recommendation, str):
            try:
                values["recommendation"] = RecommendationCategory(recommendation)
            except ValueError as exc:
                raise ReviewAutomationModelError(
                    "invalid recommendation category"
                ) from exc
        unhashed = dict(values)
        unhashed.pop(cls.HASH_FIELD, None)
        serializable = asdict_payload(unhashed)
        values[cls.HASH_FIELD] = canonical_sha256(serializable)
        return cls(**values)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "AdvisoryRecommendation":
        """Load and verify a stored recommendation without rehashing it."""
        values = dict(value)
        try:
            values["recommendation"] = RecommendationCategory(
                values["recommendation"]
            )
            values["duplicate_matches"] = tuple(
                match if isinstance(match, DuplicateMatch) else DuplicateMatch(**match)
                for match in values.get("duplicate_matches", ())
            )
            revision = values.get("suggested_revision")
            if revision is not None and not isinstance(revision, SuggestedRevision):
                revision_values = dict(revision)
                revision_values["changes_summary"] = tuple(
                    revision_values["changes_summary"]
                )
                revision_values["reasons"] = tuple(revision_values["reasons"])
                values["suggested_revision"] = SuggestedRevision(**revision_values)
            for field in (
                "language_grammar_findings",
                "safety_findings",
                "factuality_concerns",
                "cultural_context_concerns",
                "pidgin_authenticity_concerns",
                "ambiguity_findings",
                "unsupported_claim_indicators",
                "missing_citation_indicators",
                "high_risk_domain_indicators",
            ):
                values[field] = tuple(values.get(field, ()))
            return cls(**values)
        except (KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, ReviewAutomationModelError):
                raise
            raise ReviewAutomationModelError(
                "stored recommendation does not match the advisory schema"
            ) from exc


def asdict_payload(value: dict[str, Any]) -> dict[str, Any]:
    """Recursively serialize supported dataclass and enum values."""
    result: dict[str, Any] = {}
    for key, item in value.items():
        if isinstance(item, StrEnum):
            result[key] = item.value
        elif hasattr(item, "__dataclass_fields__"):
            result[key] = asdict(item)
        elif isinstance(item, tuple):
            result[key] = [
                asdict(element) if hasattr(element, "__dataclass_fields__") else element
                for element in item
            ]
        else:
            result[key] = item
    return result


@dataclass(frozen=True)
class AutomatedAuditEvent:
    """Immutable audit envelope for an automated recommendation."""

    event_id: str
    dataset_version: str
    record_id: str
    record_revision: int
    record_sha256: str
    event_type: str
    analyzer_version: str
    prompt_version: str
    provider: str
    model_name: str
    recommendation: RecommendationCategory
    confidence: int
    findings_summary: tuple[str, ...]
    recommendation_hash: str
    timestamp: str
    event_sha256: str

    def __post_init__(self) -> None:
        if self.event_type != "automated_recommendation":
            raise ReviewAutomationModelError(
                "automated event_type must be automated_recommendation"
            )
        _validate_sha256(self.record_sha256, "record_sha256")
        _validate_sha256(self.recommendation_hash, "recommendation_hash")
        _validate_sha256(self.event_sha256, "event_sha256")
        _validate_timestamp(self.timestamp, "timestamp")
        for field, value in (
            ("event_id", self.event_id),
            ("dataset_version", self.dataset_version),
            ("record_id", self.record_id),
            ("analyzer_version", self.analyzer_version),
            ("prompt_version", self.prompt_version),
            ("provider", self.provider),
            ("model_name", self.model_name),
        ):
            _required_text(value, field)
        if (
            isinstance(self.record_revision, bool)
            or not isinstance(self.record_revision, int)
            or self.record_revision < 1
        ):
            raise ReviewAutomationModelError("record_revision must be positive")
        if not isinstance(self.recommendation, RecommendationCategory):
            raise ReviewAutomationModelError("invalid recommendation category")
        if (
            isinstance(self.confidence, bool)
            or not isinstance(self.confidence, int)
            or not 0 <= self.confidence <= 100
        ):
            raise ReviewAutomationModelError("confidence must be from 0 to 100")
        if (
            not isinstance(self.findings_summary, tuple)
            or not all(
                isinstance(item, str) and item.strip()
                for item in self.findings_summary
            )
        ):
            raise ReviewAutomationModelError(
                "findings_summary must contain non-empty strings"
            )
        if self.event_sha256 != self.computed_hash():
            raise ReviewAutomationModelError("event_sha256 does not match content")

    def payload(self) -> dict[str, Any]:
        value = asdict(self)
        value.pop("event_sha256")
        value["recommendation"] = self.recommendation.value
        return value

    def computed_hash(self) -> str:
        return canonical_sha256(self.payload())


@dataclass(frozen=True)
class HumanDecisionAuditEvent:
    """Separate audit envelope for an explicit human action."""

    event_id: str
    dataset_version: str
    record_id: str
    record_revision: int
    record_sha256: str
    event_type: str
    reviewer_identifier: str
    reviewer_role: str
    action: str
    decision_note: str
    prior_status: str
    new_status: str
    related_recommendation_id: str
    timestamp: str
    event_sha256: str

    def __post_init__(self) -> None:
        if self.event_type != "human_decision":
            raise ReviewAutomationModelError(
                "human event_type must be human_decision"
            )
        _required_text(self.reviewer_identifier, "reviewer_identifier")
        _required_text(self.reviewer_role, "reviewer_role")
        for field, value in (
            ("event_id", self.event_id),
            ("dataset_version", self.dataset_version),
            ("record_id", self.record_id),
            ("action", self.action),
            ("prior_status", self.prior_status),
            ("new_status", self.new_status),
            ("related_recommendation_id", self.related_recommendation_id),
        ):
            _required_text(value, field)
        if (
            isinstance(self.record_revision, bool)
            or not isinstance(self.record_revision, int)
            or self.record_revision < 1
        ):
            raise ReviewAutomationModelError("record_revision must be positive")
        _validate_sha256(self.record_sha256, "record_sha256")
        _validate_sha256(self.event_sha256, "event_sha256")
        _validate_timestamp(self.timestamp, "timestamp")
        if self.event_sha256 != self.computed_hash():
            raise ReviewAutomationModelError("event_sha256 does not match content")

    def payload(self) -> dict[str, Any]:
        value = asdict(self)
        value.pop("event_sha256")
        return value

    def computed_hash(self) -> str:
        return canonical_sha256(self.payload())
