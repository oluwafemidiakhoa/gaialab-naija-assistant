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
    ReviewAutomationModelError,
    canonical_sha256,
)
from src.review_workflow import ROLE_FOR_STATE, TRANSITIONS


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
    batch_operation_id: str | None = None,
) -> HumanDecisionAuditEvent:
    """Create a separately typed event for one explicit human action."""
    event_identity: tuple[object, ...] = (
        dataset_version,
        record_id,
        record_revision,
        record_sha256,
        reviewer_identifier,
        action,
        timestamp,
    )
    if batch_operation_id is not None:
        event_identity = (*event_identity, batch_operation_id)
    payload = {
        "event_id": _event_id("human", *event_identity),
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
    if batch_operation_id is not None:
        payload["batch_operation_id"] = batch_operation_id
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
    if value.get("batch_operation_id") is None:
        value.pop("batch_operation_id", None)
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


def replay_human_review_state(
    records: Iterable[dict[str, Any]],
    root: Path,
    version: str,
) -> list[dict[str, Any]]:
    """Overlay valid human decisions in chronological order for reporting.

    The immutable record hash and revision remain authoritative. Audit events
    can update review metadata only when their integrity hash, version, record
    identity, transition, role, and per-record event chain are all valid.
    """
    state = {
        str(record.get("id", "")): dict(record)
        for record in records
    }
    path = audit_path(root, version, human=True)
    if not path.is_file():
        return [state[key] for key in sorted(state)]

    parsed: list[tuple[int, HumanDecisionAuditEvent]] = []
    seen_events: dict[str, str] = {}
    for ledger_index, row in enumerate(read_jsonl(path)):
        try:
            event = HumanDecisionAuditEvent(**row)
        except (ReviewAutomationModelError, TypeError) as exc:
            raise DatasetManagementError(
                f"invalid human audit event in {path}: {exc}"
            ) from exc
        if event.dataset_version != version:
            raise DatasetManagementError(
                f"human audit event has wrong dataset version: {event.event_id}"
            )
        prior_hash = seen_events.get(event.event_id)
        if prior_hash is not None and prior_hash != event.event_sha256:
            raise DatasetManagementError(
                f"human audit event ID conflicts: {event.event_id}"
            )
        if prior_hash is None:
            parsed.append((ledger_index, event))
            seen_events[event.event_id] = event.event_sha256

    parsed.sort(key=lambda item: (item[1].timestamp, item[0]))
    latest_status: dict[str, str] = {}
    for _, event in parsed:
        record = state.get(event.record_id)
        if record is None:
            raise DatasetManagementError(
                f"human audit event references unknown record: {event.record_id}"
            )
        if (
            event.record_sha256 != record.get("example_sha256")
            or event.record_revision != int(record.get("revision", 1))
        ):
            raise DatasetManagementError(
                f"human audit event does not match current record: {event.record_id}"
            )
        previous_event_status = latest_status.get(event.record_id)
        if (
            previous_event_status is not None
            and event.prior_status != previous_event_status
        ):
            raise DatasetManagementError(
                f"broken human audit transition chain for {event.record_id}"
            )
        if event.new_status not in TRANSITIONS.get(event.prior_status, set()):
            raise DatasetManagementError(
                f"invalid human audit transition for {event.record_id}: "
                f"{event.prior_status} -> {event.new_status}"
            )
        allowed_roles = ROLE_FOR_STATE.get(event.new_status)
        if allowed_roles and event.reviewer_role not in allowed_roles:
            raise DatasetManagementError(
                f"human audit role cannot set {event.new_status}: {event.record_id}"
            )
        record.update(
            review_status=event.new_status,
            reviewer=event.reviewer_identifier,
            review_date=event.timestamp,
            review_notes=event.decision_note,
        )
        if event.new_status == "technical_reviewed":
            record["technical_review_completed"] = True
            record["technical_review_timestamp"] = event.timestamp
        if event.new_status == "domain_reviewed":
            record["domain_review_completed"] = True
            record["domain_review_timestamp"] = event.timestamp
        if event.new_status == "approved":
            record["approval_timestamp"] = event.timestamp
            record["approved_revision"] = event.record_revision
            record["approved_record_sha256"] = event.record_sha256
        latest_status[event.record_id] = event.new_status
    return [state[key] for key in sorted(state)]
