"""Deterministic prioritized review queues with filtering and pagination."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from typing import Any, Iterable

from src.review_automation.config import ReviewAutomationConfig
from src.review_automation.duplicates import duplicate_likelihood, duplicate_match_map
from src.review_automation.models import canonical_sha256
from src.training_eligibility import assess_eligibility


FINAL_STATUSES = {"approved", "rejected", "superseded"}


@dataclass(frozen=True)
class QueueFilters:
    category: tuple[str, ...] = ()
    risk_level: tuple[str, ...] = ()
    review_status: tuple[str, ...] = ()
    recommendation: tuple[str, ...] = ()
    minimum_quality_score: int = 0
    maximum_quality_score: int = 100
    domain_review_required: bool | None = None
    training_eligible: bool | None = None
    include_finalized: bool = False

    def __post_init__(self) -> None:
        if not 0 <= self.minimum_quality_score <= self.maximum_quality_score <= 100:
            raise ValueError("quality score range must be within 0 to 100")


@dataclass(frozen=True)
class ReviewQueueItem:
    dataset_version: str
    record_id: str
    record_revision: int
    record_sha256: str
    category: str
    risk_level: str
    effective_risk: str
    review_status: str
    quality_score: int
    critical_findings: int
    high_findings: int
    duplicate_likelihood: int
    duplicate_record_ids: tuple[str, ...]
    recommendation: str
    technical_review_required: bool
    domain_review_required: bool
    training_eligible: bool
    eligibility_reasons: tuple[str, ...]


@dataclass(frozen=True)
class QueueSnapshot:
    snapshot_schema: str
    dataset_version: str
    generated_at: str
    page: int
    page_size: int
    total_matching: int
    total_pages: int
    excluded_finalized: int
    filters: dict[str, Any]
    group_counts: dict[str, dict[str, int]]
    items: tuple[ReviewQueueItem, ...]
    snapshot_sha256: str

    def payload(self) -> dict[str, Any]:
        value = asdict(self)
        value.pop("snapshot_sha256")
        return value

    def to_dict(self) -> dict[str, Any]:
        return {**self.payload(), "snapshot_sha256": self.snapshot_sha256}


def _assessment_map(
    assessments: Iterable[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    return {
        str(assessment.get("record_id")): assessment
        for assessment in assessments
        if assessment.get("record_id")
    }


def _recommendation_map(
    recommendations: Iterable[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    return {
        str(recommendation.get("record_id")): recommendation
        for recommendation in recommendations
        if recommendation.get("record_id")
    }


def _queue_sort_key(
    item: ReviewQueueItem,
    config: ReviewAutomationConfig,
) -> tuple[int | str, ...]:
    """Apply the validated governed ordering declared by configuration."""
    values: dict[str, int | str] = {
        "risk_severity": -config.risk_weights[item.effective_risk],
        "critical_findings": -item.critical_findings,
        "high_findings": -item.high_findings,
        "quality_score": item.quality_score,
        "duplicate_likelihood": -item.duplicate_likelihood,
        "record_id": item.record_id,
    }
    return tuple(values[field] for field in config.queue_ordering)


def build_queue(
    records: Iterable[dict[str, Any]],
    dataset_version: str,
    config: ReviewAutomationConfig,
    *,
    assessments: Iterable[dict[str, Any]] = (),
    recommendations: Iterable[dict[str, Any]] = (),
    filters: QueueFilters | None = None,
    page: int = 1,
    page_size: int = 20,
    generated_at: str,
) -> QueueSnapshot:
    """Build a deterministic, read-only snapshot of prioritized review work."""
    if page < 1:
        raise ValueError("page must be at least 1")
    if not 1 <= page_size <= 500:
        raise ValueError("page_size must be from 1 to 500")
    selected_filters = filters or QueueFilters()
    rows = sorted(list(records), key=lambda record: str(record.get("id", "")))
    assessment_by_id = _assessment_map(assessments)
    recommendation_by_id = _recommendation_map(recommendations)
    duplicates_by_record = duplicate_match_map(
        rows,
        near_threshold=config.near_duplicate_threshold,
    )
    items: list[ReviewQueueItem] = []
    excluded_finalized = 0

    for record in rows:
        status = str(record.get("review_status", "draft"))
        if status in FINAL_STATUSES and not selected_filters.include_finalized:
            excluded_finalized += 1
            continue
        assessment = assessment_by_id.get(str(record.get("id")), {})
        findings = [
            finding for finding in assessment.get("findings", [])
            if isinstance(finding, dict)
        ]
        critical = sum(finding.get("severity") == "critical" for finding in findings)
        high = sum(finding.get("severity") == "high" for finding in findings)
        risk = str(record.get("risk_level", "low"))
        effective_risk = (
            "critical" if critical else "high" if high or risk == "high" else risk
        )
        matches = duplicates_by_record.get((
            str(record.get("id", "")),
            str(record.get("example_sha256", "")),
        ), ())
        category = str(record.get("category", ""))
        technical_required = status not in {
            "technical_reviewed", "domain_reviewed", "approved"
        }
        domain_required = (
            category in config.domain_review_categories
            and status not in {"domain_reviewed", "approved"}
        )
        eligibility = assess_eligibility(record, dataset_version)
        recommendation = recommendation_by_id.get(str(record.get("id")), {})
        quality_score = int(assessment.get(
            "overall_score",
            record.get("quality_score") if record.get("quality_score") not in (None, "") else 0,
        ))
        item = ReviewQueueItem(
            dataset_version=dataset_version,
            record_id=str(record.get("id", "")),
            record_revision=int(record.get("revision", 1)),
            record_sha256=str(record.get("example_sha256", "")),
            category=category,
            risk_level=risk,
            effective_risk=effective_risk,
            review_status=status,
            quality_score=quality_score,
            critical_findings=critical,
            high_findings=high,
            duplicate_likelihood=duplicate_likelihood(matches),
            duplicate_record_ids=tuple(sorted({
                match.matched_record_id for match in matches
            })),
            recommendation=str(recommendation.get(
                "recommendation",
                assessment.get("recommended_action", "human_review"),
            )),
            technical_review_required=technical_required,
            domain_review_required=domain_required,
            training_eligible=eligibility.eligible,
            eligibility_reasons=tuple(eligibility.reasons),
        )
        if selected_filters.category and item.category not in selected_filters.category:
            continue
        if selected_filters.risk_level and item.risk_level not in selected_filters.risk_level:
            continue
        if (
            selected_filters.review_status
            and item.review_status not in selected_filters.review_status
        ):
            continue
        if (
            selected_filters.recommendation
            and item.recommendation not in selected_filters.recommendation
        ):
            continue
        if not (
            selected_filters.minimum_quality_score
            <= item.quality_score
            <= selected_filters.maximum_quality_score
        ):
            continue
        if (
            selected_filters.domain_review_required is not None
            and item.domain_review_required
            is not selected_filters.domain_review_required
        ):
            continue
        if (
            selected_filters.training_eligible is not None
            and item.training_eligible is not selected_filters.training_eligible
        ):
            continue
        items.append(item)

    items.sort(key=lambda item: _queue_sort_key(item, config))
    total_matching = len(items)
    total_pages = (
        (total_matching + page_size - 1) // page_size if total_matching else 0
    )
    start = (page - 1) * page_size
    paginated = tuple(items[start:start + page_size])
    group_counts = {
        "category": dict(sorted(Counter(item.category for item in items).items())),
        "review_status": dict(sorted(
            Counter(item.review_status for item in items).items()
        )),
    }
    payload = {
        "snapshot_schema": "gaialab.review-queue.v1",
        "dataset_version": dataset_version,
        "generated_at": generated_at,
        "page": page,
        "page_size": page_size,
        "total_matching": total_matching,
        "total_pages": total_pages,
        "excluded_finalized": excluded_finalized,
        "filters": asdict(selected_filters),
        "group_counts": group_counts,
        "items": tuple(asdict(item) for item in paginated),
    }
    snapshot_hash = canonical_sha256(payload)
    return QueueSnapshot(
        **{**payload, "items": paginated},
        snapshot_sha256=snapshot_hash,
    )
