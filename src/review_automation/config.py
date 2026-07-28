"""Validated configuration for local-first review automation."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "review_automation.yaml"
ALLOWED_RISKS = {"low", "medium", "high", "critical"}
ALLOWED_QUEUE_FIELDS = {
    "risk_severity",
    "critical_findings",
    "high_findings",
    "quality_score",
    "duplicate_likelihood",
    "record_id",
}
REQUIRED_QUEUE_ORDERING = (
    "risk_severity",
    "critical_findings",
    "high_findings",
    "quality_score",
    "duplicate_likelihood",
    "record_id",
)


class ReviewAutomationConfigError(ValueError):
    """Raised when review automation configuration is unsafe or malformed."""


@dataclass(frozen=True)
class ReviewAutomationConfig:
    risk_weights: dict[str, int]
    minimum_quality_score: int
    approve_candidate_score: int
    reject_candidate_below: int
    near_duplicate_threshold: float
    recommendation_confidence_threshold: int
    domain_review_categories: tuple[str, ...]
    enhanced_safety_categories: tuple[str, ...]
    maximum_retry_count: int
    provider_timeout_seconds: float
    queue_ordering: tuple[str, ...]
    default_provider: str
    external_provider_enabled: bool
    prompt_version: str

    def __post_init__(self) -> None:
        if not isinstance(self.risk_weights, dict):
            raise ReviewAutomationConfigError("risk_weights must be a mapping")
        if set(self.risk_weights) != ALLOWED_RISKS:
            raise ReviewAutomationConfigError(
                "risk_weights must define low, medium, high, and critical"
            )
        if any(
            isinstance(weight, bool) or not isinstance(weight, int) or weight < 0
            for weight in self.risk_weights.values()
        ):
            raise ReviewAutomationConfigError(
                "risk weights must be non-negative integers"
            )
        if not (
            self.risk_weights["low"]
            < self.risk_weights["medium"]
            < self.risk_weights["high"]
            < self.risk_weights["critical"]
        ):
            raise ReviewAutomationConfigError(
                "risk weights must increase from low to critical"
            )
        for name, score in (
            ("minimum_quality_score", self.minimum_quality_score),
            ("approve_candidate_score", self.approve_candidate_score),
            ("reject_candidate_below", self.reject_candidate_below),
            (
                "recommendation_confidence_threshold",
                self.recommendation_confidence_threshold,
            ),
        ):
            if isinstance(score, bool) or not isinstance(score, int) or not 0 <= score <= 100:
                raise ReviewAutomationConfigError(f"{name} must be from 0 to 100")
        if self.reject_candidate_below >= self.approve_candidate_score:
            raise ReviewAutomationConfigError(
                "reject threshold must be below approve threshold"
            )
        if (
            isinstance(self.near_duplicate_threshold, bool)
            or not isinstance(self.near_duplicate_threshold, (int, float))
            or not 0 < self.near_duplicate_threshold <= 1
        ):
            raise ReviewAutomationConfigError(
                "near_duplicate_threshold must be greater than 0 and at most 1"
            )
        if (
            isinstance(self.maximum_retry_count, bool)
            or not isinstance(self.maximum_retry_count, int)
            or not 0 <= self.maximum_retry_count <= 10
        ):
            raise ReviewAutomationConfigError(
                "maximum_retry_count must be from 0 to 10"
            )
        if (
            isinstance(self.provider_timeout_seconds, bool)
            or not isinstance(self.provider_timeout_seconds, (int, float))
            or not 0 < self.provider_timeout_seconds <= 300
        ):
            raise ReviewAutomationConfigError(
                "provider_timeout_seconds must be greater than 0 and at most 300"
            )
        if not self.queue_ordering or not set(self.queue_ordering) <= ALLOWED_QUEUE_FIELDS:
            raise ReviewAutomationConfigError("queue_ordering contains invalid fields")
        if len(self.queue_ordering) != len(set(self.queue_ordering)):
            raise ReviewAutomationConfigError("queue_ordering contains duplicates")
        if self.queue_ordering != REQUIRED_QUEUE_ORDERING:
            raise ReviewAutomationConfigError(
                "queue_ordering must preserve the governed deterministic priority order"
            )
        for name, categories in (
            ("domain_review_categories", self.domain_review_categories),
            ("enhanced_safety_categories", self.enhanced_safety_categories),
        ):
            if not categories or len(categories) != len(set(categories)):
                raise ReviewAutomationConfigError(
                    f"{name} must be non-empty and contain no duplicates"
                )
        if not isinstance(self.default_provider, str) or not self.default_provider.strip():
            raise ReviewAutomationConfigError("default_provider must not be empty")
        if not isinstance(self.external_provider_enabled, bool):
            raise ReviewAutomationConfigError(
                "external_provider_enabled must be boolean"
            )
        if self.default_provider != "local" and not self.external_provider_enabled:
            raise ReviewAutomationConfigError(
                "external provider requires explicit opt-in"
            )
        if not isinstance(self.prompt_version, str) or not self.prompt_version.strip():
            raise ReviewAutomationConfigError("prompt_version must not be empty")


def _required_mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ReviewAutomationConfigError(f"{field} must be a mapping")
    return value


def _required_sequence(value: Any, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        raise ReviewAutomationConfigError(f"{field} must be a list of strings")
    return tuple(value)


def _parse_bool(value: str, field: str) -> bool:
    normalized = value.strip().casefold()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ReviewAutomationConfigError(f"{field} must be true or false")


def load_review_config(
    path: Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> ReviewAutomationConfig:
    """Load YAML defaults and non-secret environment overrides."""
    environment = os.environ if environ is None else environ
    selected = path or Path(
        environment.get("GAIALAB_REVIEW_CONFIG", str(DEFAULT_CONFIG_PATH))
    )
    try:
        raw = yaml.safe_load(selected.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ReviewAutomationConfigError(
            f"review configuration unavailable: {selected}"
        ) from exc
    if not isinstance(raw, Mapping):
        raise ReviewAutomationConfigError("configuration root must be a mapping")

    provider = _required_mapping(raw.get("provider"), "provider")
    thresholds = _required_mapping(raw.get("thresholds"), "thresholds")
    values: dict[str, Any] = {
        "risk_weights": dict(_required_mapping(raw.get("risk_weights"), "risk_weights")),
        "minimum_quality_score": thresholds.get("minimum_quality_score"),
        "approve_candidate_score": thresholds.get("approve_candidate_score"),
        "reject_candidate_below": thresholds.get("reject_candidate_below"),
        "near_duplicate_threshold": thresholds.get("near_duplicate_threshold"),
        "recommendation_confidence_threshold": thresholds.get(
            "recommendation_confidence_threshold"
        ),
        "domain_review_categories": _required_sequence(
            raw.get("domain_review_categories"), "domain_review_categories"
        ),
        "enhanced_safety_categories": _required_sequence(
            raw.get("enhanced_safety_categories"), "enhanced_safety_categories"
        ),
        "maximum_retry_count": provider.get("maximum_retry_count"),
        "provider_timeout_seconds": provider.get("timeout_seconds"),
        "queue_ordering": _required_sequence(
            raw.get("queue_ordering"), "queue_ordering"
        ),
        "default_provider": provider.get("default"),
        "external_provider_enabled": provider.get("external_enabled"),
        "prompt_version": raw.get("prompt_version"),
    }

    if "GAIALAB_REVIEW_PROVIDER" in environment:
        values["default_provider"] = environment["GAIALAB_REVIEW_PROVIDER"]
    if "GAIALAB_REVIEW_EXTERNAL_ENABLED" in environment:
        values["external_provider_enabled"] = _parse_bool(
            environment["GAIALAB_REVIEW_EXTERNAL_ENABLED"],
            "GAIALAB_REVIEW_EXTERNAL_ENABLED",
        )
    if "GAIALAB_REVIEW_TIMEOUT_SECONDS" in environment:
        try:
            values["provider_timeout_seconds"] = float(
                environment["GAIALAB_REVIEW_TIMEOUT_SECONDS"]
            )
        except ValueError as exc:
            raise ReviewAutomationConfigError(
                "GAIALAB_REVIEW_TIMEOUT_SECONDS must be numeric"
            ) from exc
    if "GAIALAB_REVIEW_MAX_RETRIES" in environment:
        try:
            values["maximum_retry_count"] = int(
                environment["GAIALAB_REVIEW_MAX_RETRIES"]
            )
        except ValueError as exc:
            raise ReviewAutomationConfigError(
                "GAIALAB_REVIEW_MAX_RETRIES must be an integer"
            ) from exc
    return ReviewAutomationConfig(**values)
