"""Append-only, role-aware human review workflow."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from src.dataset_management import (
    DatasetManagementError,
    append_jsonl,
    example_sha256,
    review_log_path,
    review_state,
    utc_now,
    validate_record,
)

REVIEWER_ROLES = {
    "reviewer", "technical_reviewer", "domain_reviewer", "release_manager"
}
DOMAIN_REVIEW_CATEGORIES = {"healthcare", "banking", "government_services"}
FINAL_STATES = {"rejected", "superseded"}
TRANSITIONS = {
    "draft": {"automated_reviewed", "rejected"},
    "automated_reviewed": {"technical_reviewed", "needs_revision", "rejected"},
    "needs_revision": {"draft", "rejected"},
    "technical_reviewed": {"domain_reviewed", "approved", "needs_revision", "rejected"},
    "domain_reviewed": {"approved", "needs_revision", "rejected"},
    "approved": set(),
    "rejected": set(),
    "superseded": set(),
}
ROLE_FOR_STATE = {
    "technical_reviewed": {"technical_reviewer", "release_manager"},
    "domain_reviewed": {"domain_reviewer", "release_manager"},
    "approved": {"technical_reviewer", "domain_reviewer", "release_manager"},
    "rejected": REVIEWER_ROLES,
    "needs_revision": REVIEWER_ROLES,
}


@dataclass(frozen=True)
class ReviewEvent:
    review_event_id: str
    record_id: str
    record_sha256: str
    revision: int
    previous_status: str
    new_status: str
    reviewer_identifier: str
    reviewer_role: str
    review_timestamp: str
    quality_score: int | None
    review_notes: str
    correction_required: bool
    event_sha256: str


def _hash(value: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()).hexdigest()


def _event(payload: dict[str, Any]) -> ReviewEvent:
    return ReviewEvent(**payload, event_sha256=_hash(payload))


def review_history(registry_dir: Path, version: str, record_id: str) -> list[dict[str, Any]]:
    path = review_log_path(registry_dir, version)
    if not path.exists():
        return []
    from src.dataset_management import read_jsonl
    return [event for event in read_jsonl(path) if event.get("id") == record_id]


def transition_review(
    registry_dir: Path,
    version: str,
    record_id: str,
    new_status: str,
    reviewer_identifier: str,
    reviewer_role: str,
    *,
    quality_score: int | None = None,
    review_notes: str = "",
    correction_required: bool = False,
    now: Callable[[], str] = utc_now,
) -> ReviewEvent:
    """Validate and append a state transition without changing record content."""
    if reviewer_role not in REVIEWER_ROLES:
        raise DatasetManagementError("invalid reviewer role")
    if not reviewer_identifier.strip():
        raise DatasetManagementError("reviewer_identifier is required")
    if quality_score is not None and not 0 <= quality_score <= 100:
        raise DatasetManagementError("quality_score must be from 0 to 100")
    records = {r["id"]: r for r in review_state(registry_dir, version)}
    if record_id not in records:
        raise DatasetManagementError(f"unknown record: {record_id}")
    current = records[record_id]
    previous = current["review_status"]
    if new_status not in TRANSITIONS.get(previous, set()):
        raise DatasetManagementError(f"invalid review transition: {previous} -> {new_status}")
    allowed_roles = ROLE_FOR_STATE.get(new_status)
    if allowed_roles and reviewer_role not in allowed_roles:
        raise DatasetManagementError(f"{reviewer_role} cannot set {new_status}")
    if new_status == "approved":
        if previous not in {"technical_reviewed", "domain_reviewed"}:
            raise DatasetManagementError("technical review is required before approval")
        if current["category"] in DOMAIN_REVIEW_CATEGORIES and previous != "domain_reviewed":
            raise DatasetManagementError("domain review is required before approval")

    timestamp = now()
    updated = dict(current)
    updated.update(
        review_status=new_status,
        reviewer=reviewer_identifier.strip(),
        review_date=timestamp,
        quality_score=quality_score,
        review_notes=review_notes.strip(),
    )
    if new_status == "technical_reviewed":
        updated["technical_review_completed"] = True
        updated["technical_review_timestamp"] = timestamp
    if new_status == "domain_reviewed":
        updated["domain_review_completed"] = True
        updated["domain_review_timestamp"] = timestamp
    if new_status == "approved":
        updated.update(
            approval_timestamp=timestamp,
            approved_revision=int(updated["revision"]),
            approved_record_sha256=updated["example_sha256"],
        )
    payload = {
        "review_event_id": str(uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"{version}:{record_id}:{current['revision']}:{previous}:{new_status}:{timestamp}",
        )),
        "record_id": record_id,
        "record_sha256": current["example_sha256"],
        "revision": int(current["revision"]),
        "previous_status": previous,
        "new_status": new_status,
        "reviewer_identifier": reviewer_identifier.strip(),
        "reviewer_role": reviewer_role,
        "review_timestamp": timestamp,
        "quality_score": quality_score,
        "review_notes": review_notes.strip(),
        "correction_required": bool(correction_required),
    }
    event = _event(payload)
    append_jsonl(review_log_path(registry_dir, version), {
        "event": "review_transition",
        "id": record_id,
        "version": version,
        "timestamp": timestamp,
        "record": updated,
        "review_event": asdict(event),
    })
    return event


def create_revision(
    registry_dir: Path,
    version: str,
    record_id: str,
    messages: list[dict[str, str]],
    reviewer_identifier: str,
    *,
    now: Callable[[], str] = utc_now,
) -> dict[str, Any]:
    """Create a draft child revision; the approved parent remains unchanged."""
    if not reviewer_identifier.strip():
        raise DatasetManagementError("reviewer_identifier is required")
    records = {r["id"]: r for r in review_state(registry_dir, version)}
    current = records.get(record_id)
    if current is None:
        raise DatasetManagementError(f"unknown record: {record_id}")
    updated = dict(current)
    updated["messages"] = messages
    validate_record(updated)
    updated.update(
        revision=int(current["revision"]) + 1,
        parent_record_sha256=current["example_sha256"],
        supersedes_sha256="",
        review_status="draft",
        reviewer=reviewer_identifier.strip(),
        review_date=now(),
        approval_timestamp="",
        approved_revision=None,
        approved_record_sha256="",
    )
    updated["example_sha256"] = example_sha256(updated)
    append_jsonl(review_log_path(registry_dir, version), {
        "event": "revision_created",
        "id": record_id,
        "version": version,
        "timestamp": updated["review_date"],
        "record": updated,
    })
    return updated


def mark_parent_superseded(
    registry_dir: Path, version: str, record_id: str, reviewer_identifier: str
) -> dict[str, Any]:
    """Link an approved child to its parent after the child is approved."""
    current = {r["id"]: r for r in review_state(registry_dir, version)}.get(record_id)
    if not current or current.get("review_status") != "approved":
        raise DatasetManagementError("only an approved revision can supersede its parent")
    parent = current.get("parent_record_sha256")
    if not parent:
        raise DatasetManagementError("revision has no parent")
    updated = dict(current)
    updated["supersedes_sha256"] = parent
    append_jsonl(review_log_path(registry_dir, version), {
        "event": "parent_superseded",
        "id": record_id,
        "version": version,
        "timestamp": utc_now(),
        "reviewer_identifier": reviewer_identifier,
        "record": updated,
    })
    return updated
