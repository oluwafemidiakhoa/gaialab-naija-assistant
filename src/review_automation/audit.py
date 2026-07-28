"""Immutable, separately typed audit events for automated and human review."""

from __future__ import annotations

import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable

from src.dataset_management import DatasetManagementError, append_jsonl, read_jsonl
from src.review_automation.models import (
    AdvisoryRecommendation,
    AutomatedAuditEvent,
    HumanDecisionAuditEvent,
    RecommendationCategory,
    canonical_sha256,
)


AUTOMATED_AUDIT_FILE = "automated_events.jsonl"
HUMAN_AUDIT_FILE = "human_events.jsonl"


def _event_id(kind: str, *identity: object) -> str:
    value = ":".join(str(item) for item in (kind, *identity))
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"gaialab-review:{value}"))


def automated_event(
    recommendation: AdvisoryRecommendation,
) -> AutomatedAuditEvent:
    """Create a deterministic event from a stored advisory recommendation."""
    findings: tuple[str, ...] = tuple(
        dict.fromkeys(
            recommendation.language_grammar_findings
            + recommendation.safety_findings
            + recommendation.factuality_concerns
            + recommendation.cultural_context_concerns
            + recommendation.pidgin_authenticity_concerns
            + recommendation.ambiguity_findings
            + recommendation.unsupported_claim_indicators
            + recommendation.missing_citation_indicators
            + recommendation.high_risk_domain_indicators
        )
    )
    payload: dict[str, Any] = {
        "event_id": _event_id(
            "automated",
            recommendation.dataset_version,
            recommendation.record_id,
            recommendation.record_revision,
            recommendation.recommendation_hash,
        ),
        "dataset_version": recommendation.dataset_version,
        "record_id": recommendation.record_id,
        "record_revision": recommendation.record_revision,
        "record_sha256": recommendation.input_record_sha256,
        "event_type": "automated_recommendation",
        "analyzer_version": recommendation.analyzer_version,
        "prompt_version": recommendation.prompt_version,
        "provider": recommendation.provider,
        "model_name": recommendation.model_name,
        "recommendation": recommendation.recommendation,
        "confidence": recommendation.confidence_score,
        "findings_summary": findings,
        "recommendation_hash": recommendation.recommendation_hash,
        "timestamp": recommendation.generation_timestamp,
    }
    hash_payload = {
        **payload,
        "recommendation": recommendation.recommendation.value,
    }
    return AutomatedAuditEvent(
        **payload,
        event_sha256=canonical_sha256(hash_payload),
    )


def human_event(
    *,
    dataset_version: str,
    record_id: str,
    record_revision: int,
    record_sha256: str,
    reviewer_identifier: str,
    reviewer_role: str,
    action: str,
    decision_note: str,
    prior_status: str,
    new_status: str,
    related_recommendation_id: str,
    timestamp: str,
) -> HumanDecisionAuditEvent:
    """Create a separately typed event for one explicit human action."""
    payload = {
        "event_id": _event_id(
            "human",
            dataset_version,
            record_id,
            record_revision,
            record_sha256,
            reviewer_identifier,
            action,
            timestamp,
        ),
        "dataset_version": dataset_version,
        "record_id": record_id,
        "record_revision": record_revision,
        "record_sha256": record_sha256,
        "event_type": "human_decision",
        "reviewer_identifier": reviewer_identifier.strip(),
        "reviewer_role": reviewer_role,
        "action": action,
        "decision_note": decision_note.strip(),
        "prior_status": prior_status,
        "new_status": new_status,
        "related_recommendation_id": related_recommendation_id,
        "timestamp": timestamp,
    }
    return HumanDecisionAuditEvent(
        **payload,
        event_sha256=canonical_sha256(payload),
    )


def audit_path(root: Path, version: str, *, human: bool) -> Path:
    filename = HUMAN_AUDIT_FILE if human else AUTOMATED_AUDIT_FILE
    return root / version / filename


def append_audit_event(
    root: Path,
    event: AutomatedAuditEvent | HumanDecisionAuditEvent,
) -> bool:
    """Append once by event ID; return false when the same event already exists."""
    human = isinstance(event, HumanDecisionAuditEvent)
    path = audit_path(root, event.dataset_version, human=human)
    if path.is_file():
        for row in read_jsonl(path):
            if row.get("event_id") == event.event_id:
                if row.get("event_sha256") != event.event_sha256:
                    raise DatasetManagementError(
                        "audit event ID already exists with different content"
                    )
                return False
    value = asdict(event)
    recommendation = value.get("recommendation")
    if isinstance(recommendation, RecommendationCategory):
        value["recommendation"] = recommendation.value
    append_jsonl(path, value)
    return True


def append_automated_events(
    root: Path,
    recommendations: Iterable[AdvisoryRecommendation],
) -> int:
    """Append audit events for recommendations and return the number added."""
    return sum(
        append_audit_event(root, automated_event(recommendation))
        for recommendation in recommendations
    )


def audit_history(
    root: Path,
    version: str,
    record_id: str,
) -> list[dict[str, Any]]:
    """Return automated and human events in stable timestamp/event order."""
    rows: list[dict[str, Any]] = []
    for human in (False, True):
        path = audit_path(root, version, human=human)
        if path.is_file():
            rows.extend(
                row for row in read_jsonl(path)
                if row.get("record_id") == record_id
            )
    return sorted(
        rows,
        key=lambda row: (str(row.get("timestamp", "")), str(row.get("event_id", ""))),
    )
