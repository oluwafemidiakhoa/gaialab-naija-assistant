"""Human-gated decisions and non-mutating advisory revision handling."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from src.dataset_management import (
    DatasetManagementError,
    read_jsonl,
    review_state,
    utc_now,
)
from src.review_automation.audit import (
    append_audit_event,
    audit_path,
    human_event,
)
from src.review_automation.models import AdvisoryRecommendation
from src.review_workflow import REVIEWER_ROLES, create_revision, transition_review


DECISION_TRANSITIONS = {
    "acknowledge_analysis": "automated_reviewed",
    "technical_review": "technical_reviewed",
    "domain_review": "domain_reviewed",
    "approve": "approved",
    "request_revision": "needs_revision",
    "reject": "rejected",
    "escalate": "needs_revision",
}
NOTE_REQUIRED_ACTIONS = {
    "request_revision",
    "reject",
    "escalate",
    "accept_suggested_revision",
    "edit_suggested_revision",
}
REVISION_ACTIONS = {
    "accept_suggested_revision",
    "edit_suggested_revision",
    "discard_suggested_revision",
}


def _current_record(
    registry_dir: Path,
    version: str,
    record_id: str,
) -> dict:
    record = {
        row["id"]: row for row in review_state(registry_dir, version)
    }.get(record_id)
    if record is None:
        raise DatasetManagementError(f"unknown record: {record_id}")
    return record


def _validate_human(
    reviewer_identifier: str,
    reviewer_role: str,
    *,
    action: str,
    decision_note: str,
) -> None:
    if not reviewer_identifier.strip():
        raise DatasetManagementError("reviewer_identifier is required")
    if reviewer_role not in REVIEWER_ROLES:
        raise DatasetManagementError("invalid reviewer role")
    if action in NOTE_REQUIRED_ACTIONS and not decision_note.strip():
        raise DatasetManagementError(
            f"decision note is required for {action.replace('_', ' ')}"
        )


def _validate_recommendation(
    recommendation: AdvisoryRecommendation,
    record: dict,
    version: str,
) -> None:
    if (
        recommendation.dataset_version != version
        or recommendation.record_id != record["id"]
        or recommendation.record_revision != int(record["revision"])
        or recommendation.input_record_sha256 != record["example_sha256"]
    ):
        raise DatasetManagementError(
            "recommendation does not match the current record revision"
        )


def _require_audited_recommendation(
    audit_root: Path,
    recommendation: AdvisoryRecommendation,
) -> None:
    path = audit_path(
        audit_root,
        recommendation.dataset_version,
        human=False,
    )
    if not path.is_file():
        raise DatasetManagementError(
            "recommendation must be stored in the automated audit before human action"
        )
    if not any(
        row.get("recommendation_hash") == recommendation.recommendation_hash
        and row.get("record_sha256") == recommendation.input_record_sha256
        for row in read_jsonl(path)
    ):
        raise DatasetManagementError(
            "recommendation must be stored in the automated audit before human action"
        )


def apply_human_decision(
    registry_dir: Path,
    audit_root: Path,
    version: str,
    record_id: str,
    action: str,
    reviewer_identifier: str,
    reviewer_role: str,
    *,
    recommendation: AdvisoryRecommendation,
    decision_note: str = "",
    quality_score: int | None = None,
    confirm_approval: bool = False,
    now: Callable[[], str] = utc_now,
) -> dict:
    """Apply an explicit human decision through the existing governed workflow."""
    if action not in DECISION_TRANSITIONS:
        raise DatasetManagementError("unsupported human decision")
    _validate_human(
        reviewer_identifier,
        reviewer_role,
        action=action,
        decision_note=decision_note,
    )
    if action == "approve" and not confirm_approval:
        raise DatasetManagementError("approval requires explicit confirmation")
    current = _current_record(registry_dir, version, record_id)
    _validate_recommendation(recommendation, current, version)
    _require_audited_recommendation(audit_root, recommendation)
    timestamp = now()
    new_status = DECISION_TRANSITIONS[action]
    event = transition_review(
        registry_dir,
        version,
        record_id,
        new_status,
        reviewer_identifier,
        reviewer_role,
        quality_score=quality_score,
        review_notes=decision_note,
        correction_required=action in {"request_revision", "escalate"},
        now=lambda: timestamp,
    )
    audit = human_event(
        dataset_version=version,
        record_id=record_id,
        record_revision=event.revision,
        record_sha256=event.record_sha256,
        reviewer_identifier=reviewer_identifier,
        reviewer_role=reviewer_role,
        action=action,
        decision_note=decision_note,
        prior_status=event.previous_status,
        new_status=event.new_status,
        related_recommendation_id=recommendation.recommendation_hash,
        timestamp=timestamp,
    )
    append_audit_event(audit_root, audit)
    return {
        "action": action,
        "prior_status": event.previous_status,
        "new_status": event.new_status,
        "review_event_sha256": event.event_sha256,
        "human_audit_sha256": audit.event_sha256,
    }


def apply_revision_action(
    registry_dir: Path,
    audit_root: Path,
    version: str,
    record_id: str,
    action: str,
    reviewer_identifier: str,
    reviewer_role: str,
    *,
    recommendation: AdvisoryRecommendation,
    decision_note: str = "",
    edited_prompt: str | None = None,
    edited_response: str | None = None,
    now: Callable[[], str] = utc_now,
) -> dict:
    """Accept, edit, or discard a suggestion only after an explicit human action."""
    if action not in REVISION_ACTIONS:
        raise DatasetManagementError("unsupported revision action")
    _validate_human(
        reviewer_identifier,
        reviewer_role,
        action=action,
        decision_note=decision_note,
    )
    current = _current_record(registry_dir, version, record_id)
    _validate_recommendation(recommendation, current, version)
    _require_audited_recommendation(audit_root, recommendation)
    suggestion = recommendation.suggested_revision
    if suggestion is None:
        raise DatasetManagementError("recommendation has no suggested revision")
    if (
        action == "edit_suggested_revision"
        and (edited_prompt is None or edited_response is None)
    ):
        raise DatasetManagementError(
            "edited prompt and response are required for an edited revision"
        )
    timestamp = now()
    updated = current
    if action != "discard_suggested_revision":
        prompt = (
            edited_prompt.strip()
            if action == "edit_suggested_revision" and edited_prompt is not None
            else suggestion.prompt
        )
        response = (
            edited_response.strip()
            if action == "edit_suggested_revision" and edited_response is not None
            else suggestion.response
        )
        if not prompt or not response:
            raise DatasetManagementError("revision prompt and response are required")
        system = next(
            message["content"] for message in current["messages"]
            if message["role"] == "system"
        )
        updated = create_revision(
            registry_dir,
            version,
            record_id,
            [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
                {"role": "assistant", "content": response},
            ],
            reviewer_identifier,
            now=lambda: timestamp,
        )
    audit = human_event(
        dataset_version=version,
        record_id=record_id,
        record_revision=int(current["revision"]),
        record_sha256=current["example_sha256"],
        reviewer_identifier=reviewer_identifier,
        reviewer_role=reviewer_role,
        action=action,
        decision_note=decision_note,
        prior_status=current["review_status"],
        new_status=str(updated["review_status"]),
        related_recommendation_id=recommendation.recommendation_hash,
        timestamp=timestamp,
    )
    append_audit_event(audit_root, audit)
    return {
        "action": action,
        "record_id": record_id,
        "prior_revision": int(current["revision"]),
        "new_revision": int(updated["revision"]),
        "new_status": str(updated["review_status"]),
        "record_sha256": str(updated["example_sha256"]),
        "human_audit_sha256": audit.event_sha256,
    }
