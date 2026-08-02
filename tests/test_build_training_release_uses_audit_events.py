
from __future__ import annotations
import json
from pathlib import Path

from scripts.build_training_release import (
    apply_effective_review_state,
    load_latest_review_states,
)


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    """Write dictionaries as newline-delimited JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)

    content = "".join(
        json.dumps(row, sort_keys=True) + "\n"
        for row in rows
    )

    path.write_text(content, encoding="utf-8")


def test_approved_audit_event_is_applied_to_matching_record(
    tmp_path: Path,
) -> None:
    """A valid approval event should become the record's effective state."""
    dataset_version = "v0.6"
    record_hash = "a" * 64

    record = {
        "id": "v06-writing-001",
        "example_sha256": record_hash,
        "review_status": "draft",
        "technical_review_completed": False,
    }

    audit_root = tmp_path / "review_audit"
    audit_file = (
        audit_root
        / dataset_version
        / "human_events.jsonl"
    )

    write_jsonl(
        audit_file,
        [
            {
                "event_type": "human_decision",
                "dataset_version": dataset_version,
                "record_id": record["id"],
                "record_sha256": record_hash,
                "prior_status": "technical_reviewed",
                "new_status": "approved",
                "action": "approve",
                "reviewer_role": "release_manager",
                "timestamp": "2026-07-30T01:54:05+00:00",
            }
        ],
    )

    latest_states = load_latest_review_states(
        audit_root,
        dataset_version,
    )

    assert record["id"] in latest_states

    effective_record = apply_effective_review_state(
        record,
        latest_states[record["id"]],
    )

    assert effective_record["review_status"] == "approved"
    assert effective_record["technical_review_completed"] is True

    # The immutable source record must not be modified.
    assert record["review_status"] == "draft"
    assert record["technical_review_completed"] is False


def test_audit_event_with_wrong_record_hash_is_not_applied(
    tmp_path: Path,
) -> None:
    """An approval must be ignored when its hash does not match the record."""
    dataset_version = "v0.6"

    record = {
        "id": "v06-writing-001",
        "example_sha256": "a" * 64,
        "review_status": "draft",
        "technical_review_completed": False,
    }

    audit_root = tmp_path / "review_audit"
    audit_file = (
        audit_root
        / dataset_version
        / "human_events.jsonl"
    )

    write_jsonl(
        audit_file,
        [
            {
                "event_type": "human_decision",
                "dataset_version": dataset_version,
                "record_id": record["id"],
                "record_sha256": "b" * 64,
                "prior_status": "technical_reviewed",
                "new_status": "approved",
                "action": "approve",
                "reviewer_role": "release_manager",
                "timestamp": "2026-07-30T01:54:05+00:00",
            }
        ],
    )

    latest_states = load_latest_review_states(
        audit_root,
        dataset_version,
    )

    effective_record = apply_effective_review_state(
        record,
        latest_states[record["id"]],
    )

    assert effective_record["review_status"] == "draft"
    assert effective_record["technical_review_completed"] is False


def test_latest_audit_event_wins(
    tmp_path: Path,
) -> None:
    """The most recent valid audit event should define effective status."""
    dataset_version = "v0.6"
    record_hash = "c" * 64
    record_id = "v06-writing-002"

    audit_root = tmp_path / "review_audit"
    audit_file = (
        audit_root
        / dataset_version
        / "human_events.jsonl"
    )

    write_jsonl(
        audit_file,
        [
            {
                "event_type": "human_decision",
                "dataset_version": dataset_version,
                "record_id": record_id,
                "record_sha256": record_hash,
                "prior_status": "draft",
                "new_status": "automated_reviewed",
                "action": "acknowledge_analysis",
                "reviewer_role": "technical_reviewer",
                "timestamp": "2026-07-30T01:35:19+00:00",
            },
            {
                "event_type": "human_decision",
                "dataset_version": dataset_version,
                "record_id": record_id,
                "record_sha256": record_hash,
                "prior_status": "automated_reviewed",
                "new_status": "technical_reviewed",
                "action": "technical_review",
                "reviewer_role": "technical_reviewer",
                "timestamp": "2026-07-30T01:43:27+00:00",
            },
            {
                "event_type": "human_decision",
                "dataset_version": dataset_version,
                "record_id": record_id,
                "record_sha256": record_hash,
                "prior_status": "technical_reviewed",
                "new_status": "approved",
                "action": "approve",
                "reviewer_role": "release_manager",
                "timestamp": "2026-07-30T01:54:05+00:00",
            },
        ],
    )

    latest_states = load_latest_review_states(
        audit_root,
        dataset_version,
    )

    assert latest_states[record_id]["new_status"] == "approved"
    assert (
        latest_states[record_id]["reviewer_role"]
        == "release_manager"
    )


def test_incident_backup_events_never_authorize_release_records(tmp_path: Path) -> None:
    dataset_version = "v0.8-draft"
    audit_root = tmp_path / "review_audit"
    official = audit_root / dataset_version / "human_events.jsonl"
    incident = (
        audit_root
        / dataset_version
        / "incidents"
        / "human_events_pytest_pollution.jsonl"
    )
    write_jsonl(official, [])
    write_jsonl(
        incident,
        [{
            "event_type": "human_decision",
            "dataset_version": dataset_version,
            "record_id": "must-not-advance",
            "record_sha256": "a" * 64,
            "prior_status": "technical_reviewed",
            "new_status": "approved",
            "action": "approve",
            "reviewer_role": "release_manager",
            "timestamp": "2026-08-02T10:00:00+00:00",
        }],
    )

    assert load_latest_review_states(audit_root, dataset_version) == {}
