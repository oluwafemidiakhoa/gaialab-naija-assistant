"""Deterministic guided-review navigation and pilot progress helpers."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from typing import Any, Iterable

from src.review_automation.models import AdvisoryRecommendation, canonical_sha256
from src.review_automation.queue import QueueFilters, QueueSnapshot, ReviewQueueItem
from src.training_eligibility import ALLOWED_LICENSES, assess_eligibility


PILOT_ACTIONS = {
    "approve",
    "request_revision",
    "reject",
    "escalate",
    "accept_suggested_revision",
    "edit_suggested_revision",
    "discard_suggested_revision",
    "skip",
    "acknowledge_analysis",
    "technical_review",
    "domain_review",
}


@dataclass(frozen=True)
class PilotProgress:
    """Session-local navigation state; official decisions live elsewhere."""

    target: int = 5
    processed_record_ids: tuple[str, ...] = ()
    actions: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if not 1 <= self.target <= 100:
            raise ValueError("pilot target must be from 1 to 100")
        if len(self.processed_record_ids) != len(set(self.processed_record_ids)):
            raise ValueError("pilot record IDs must be unique")
        if any(action not in PILOT_ACTIONS for _, action in self.actions):
            raise ValueError("pilot action is invalid")

    @property
    def completed(self) -> int:
        return len(self.processed_record_ids)

    @property
    def remaining(self) -> int:
        return max(0, self.target - self.completed)

    @property
    def complete(self) -> bool:
        return self.completed >= self.target

    def record(self, record_id: str, action: str) -> "PilotProgress":
        """Return new session state after an explicit action or skip."""
        if action not in PILOT_ACTIONS:
            raise ValueError("pilot action is invalid")
        if self.complete or record_id in self.processed_record_ids:
            return self
        return PilotProgress(
            target=self.target,
            processed_record_ids=(*self.processed_record_ids, record_id),
            actions=(*self.actions, (record_id, action)),
        )


def filter_identity(
    version: str,
    filters: QueueFilters,
    target: int,
) -> str:
    """Hash the active filters so changed filters reset only pilot navigation."""
    return canonical_sha256({
        "version": version,
        "filters": asdict(filters),
        "target": target,
    })


def record_action_and_advance(
    progress: PilotProgress,
    record_id: str,
    action: str,
) -> PilotProgress:
    """Update navigation only after the official action succeeds."""
    return progress.record(record_id, action)


def review_next(
    snapshot: QueueSnapshot,
    progress: PilotProgress,
) -> ReviewQueueItem | None:
    """Select the highest-priority unprocessed item without changing state."""
    if progress.complete:
        return None
    processed = set(progress.processed_record_ids)
    return next(
        (item for item in snapshot.items if item.record_id not in processed),
        None,
    )


def pilot_summary(
    progress: PilotProgress,
    records: Iterable[dict[str, Any]],
    *,
    version: str,
    domain_review_categories: Iterable[str],
) -> dict[str, Any]:
    """Summarize navigation actions and current governed record state."""
    rows = list(records)
    action_counts = Counter(action for _, action in progress.actions)
    domain_categories = set(domain_review_categories)
    return {
        "pilot_target": progress.target,
        "completed": progress.completed,
        "remaining": progress.remaining,
        "approved": action_counts["approve"],
        "revision_requested": action_counts["request_revision"],
        "rejected": action_counts["reject"],
        "escalated": action_counts["escalate"],
        "skipped": action_counts["skip"],
        "newly_training_eligible": sum(
            assess_eligibility(record, version).eligible
            for record in rows
            if record.get("id") in progress.processed_record_ids
        ),
        "remaining_domain_review_backlog": sum(
            record.get("category") in domain_categories
            and not (
                record.get("domain_review_completed")
                or record.get("domain_review_timestamp")
            )
            for record in rows
        ),
    }


def queue_summary(snapshot: QueueSnapshot) -> dict[str, int]:
    """Build dashboard cards from the active deterministic queue."""
    recommendations = Counter(item.recommendation for item in snapshot.items)
    return {
        "total_matching": snapshot.total_matching,
        "approve_candidates": recommendations["approve_candidate"],
        "revise_candidates": recommendations["revise_candidate"],
        "escalations": sum(
            count for name, count in recommendations.items()
            if name.startswith("escalate_")
        ),
        "critical_findings": sum(item.critical_findings for item in snapshot.items),
        "high_risk_records": sum(
            item.effective_risk in {"critical", "high"} for item in snapshot.items
        ),
        "technical_review_backlog": sum(
            item.technical_review_required for item in snapshot.items
        ),
        "domain_review_backlog": sum(
            item.domain_review_required for item in snapshot.items
        ),
        "training_eligible": sum(item.training_eligible for item in snapshot.items),
    }


def approval_blockers(
    record: dict[str, Any],
    recommendation: AdvisoryRecommendation,
) -> tuple[str, ...]:
    """Explain why the current record cannot yet be approved."""
    blockers: list[str] = []
    status = str(record.get("review_status", "draft"))
    if status not in {"technical_reviewed", "domain_reviewed"}:
        blockers.append("technical_review_incomplete")
    if recommendation.domain_review_required and status != "domain_reviewed":
        blockers.append("domain_review_incomplete")
    source = str(record.get("source", "")).strip()
    if not source or source.casefold() in {"unknown", "provenance_unknown"}:
        blockers.append("provenance_incomplete")
    license_name = str(record.get("license", "")).strip()
    if not license_name:
        blockers.append("license_missing")
    elif license_name not in ALLOWED_LICENSES:
        blockers.append("license_not_allowed")
    if recommendation.quality_score < 60:
        blockers.append("quality_below_minimum")
    if recommendation.safety_findings or recommendation.high_risk_domain_indicators:
        blockers.append("unresolved_safety_or_high_risk_findings")
    return tuple(dict.fromkeys(blockers))
