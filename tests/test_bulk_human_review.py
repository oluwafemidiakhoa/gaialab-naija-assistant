from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from src.dataset_management import (
    DatasetManagementError,
    import_version,
    read_jsonl,
    review_state,
    snapshot_path,
)
from src.review_automation.analyzer import ReviewAnalyzer
from src.review_automation.audit import (
    append_audit_event,
    audit_path,
    automated_event,
)
from src.review_automation.bulk import (
    CONFIRMATION_PHRASE,
    build_bulk_preview,
    execute_bulk_review,
)
from src.review_automation.config import load_review_config
from src.training_eligibility import assess_eligibility


TOPICS = (
    (
        "supplier",
        "Ask a supplier in Enugu to confirm a delivery date.",
        "Good day. Please confirm the delivery date for our Enugu order. Thank you.",
    ),
    (
        "invoice",
        "Send a polite reminder about an overdue Lagos invoice.",
        "Dear customer, this is a polite reminder that the Lagos invoice is due. "
        "Please confirm the payment date. Thank you.",
    ),
    (
        "proposal",
        "Follow up on a catering proposal sent to an Abuja office.",
        "Good afternoon. I am following up on our Abuja catering proposal. "
        "Please let us know if you need any clarification. Regards.",
    ),
)


def _record(
    index: int,
    *,
    status: str = "automated_reviewed",
    risk: str = "low",
    category: str = "small_business",
    source: str = "synthetic",
    license_name: str = "CC0-1.0",
) -> dict:
    _, prompt, response = TOPICS[index % len(TOPICS)]
    value = {
        "id": f"vbulk-{index:03d}",
        "category": category,
        "risk_level": risk,
        "messages": [
            {"role": "system", "content": "Be safe and concise."},
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": response},
        ],
        "source": source,
        "license": license_name,
        "review_status": status,
    }
    if status in {"technical_reviewed", "domain_reviewed", "approved"}:
        value["technical_review_completed"] = True
        value["technical_review_timestamp"] = "2026-07-29T10:00:00+00:00"
    if status in {"domain_reviewed", "approved"}:
        value["domain_review_completed"] = True
        value["domain_review_timestamp"] = "2026-07-29T10:01:00+00:00"
    return value


def _environment(
    tmp_path: Path,
    rows: list[dict],
    *,
    version: str = "vbulk",
) -> tuple[Path, Path, list[dict], list[dict]]:
    source = tmp_path / "source.jsonl"
    source.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )
    registry = tmp_path / "registry"
    import_version(source, registry, version)
    records = review_state(registry, version)
    analyzer = ReviewAnalyzer(load_review_config())
    recommendations = [
        analyzer.analyze(
            record,
            records=records,
            generated_at="2026-07-29T12:00:00+00:00",
        )
        for record in records
    ]
    audit_root = tmp_path / "audit"
    for recommendation in recommendations:
        append_audit_event(audit_root, automated_event(recommendation))
    return (
        registry,
        audit_root,
        records,
        [recommendation.to_dict() for recommendation in recommendations],
    )


def _preview(
    records: list[dict],
    recommendations: list[dict],
    audit_root: Path,
    *,
    action: str,
    category: str = "small_business",
    assessments: list[dict] | None = None,
    limit: int = 20,
):
    selected_assessments = assessments or [
        {
            "record_id": record["id"],
            "record_sha256": record["example_sha256"],
            "overall_score": next(
                value["quality_score"]
                for value in recommendations
                if value["record_id"] == record["id"]
            ),
            "findings": [],
        }
        for record in records
    ]
    return build_bulk_preview(
        records,
        "vbulk",
        load_review_config(),
        category=category,
        reviewer_id="reviewer-technical-01",
        reviewer_role="technical_reviewer",
        action=action,
        decision_note="I reviewed every selected record against the listed findings.",
        limit=limit,
        assessments=selected_assessments,
        recommendations=recommendations,
        audit_root=audit_root,
    )


def _execute(
    preview,
    registry: Path,
    audit_root: Path,
    recommendations: list[dict],
    *,
    confirmation: str = CONFIRMATION_PHRASE,
    dry_run: bool = False,
    assessments: list[dict] | None = None,
):
    selected_assessments = assessments or [
        {
            "record_id": item.record_id,
            "record_sha256": item.record_sha256,
            "overall_score": item.quality_score,
            "findings": [],
        }
        for item in preview.items
    ]
    return execute_bulk_review(
        preview,
        load_review_config(),
        registry_dir=registry,
        releases_dir=registry.parent / "releases",
        audit_root=audit_root,
        assessments=selected_assessments,
        recommendations=recommendations,
        confirmation=confirmation,
        authenticated_reviewer_id="reviewer-technical-01",
        dry_run=dry_run,
    )


def test_dry_run_performs_no_writes_and_preserves_source_snapshot(
    tmp_path: Path,
) -> None:
    registry, audit_root, records, recommendations = _environment(
        tmp_path, [_record(0)]
    )
    preview = _preview(
        records, recommendations, audit_root, action="technical-review"
    )
    before_snapshot = snapshot_path(registry, "vbulk").read_bytes()
    before_files = {
        path.relative_to(tmp_path): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }

    result = _execute(
        preview,
        registry,
        audit_root,
        recommendations,
        dry_run=True,
    )

    after_files = {
        path.relative_to(tmp_path): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }
    assert result["dry_run"] is True
    assert result["write_performed"] is False
    assert before_files == after_files
    assert snapshot_path(registry, "vbulk").read_bytes() == before_snapshot


def test_high_risk_and_domain_review_records_are_blocked_from_bulk_approval(
    tmp_path: Path,
) -> None:
    rows = [
        _record(0, status="technical_reviewed", risk="high"),
        _record(
            1,
            status="technical_reviewed",
            category="healthcare",
        ),
    ]
    registry, audit_root, records, recommendations = _environment(tmp_path, rows)
    high = _preview(
        records,
        recommendations,
        audit_root,
        action="approve",
        category="small_business",
    )
    domain = _preview(
        records,
        recommendations,
        audit_root,
        action="approve",
        category="healthcare",
    )

    assert high.allowed_count == 0
    assert "bulk_requires_low_risk" in high.items[0].blocking_reasons
    assert domain.allowed_count == 0
    assert "domain_review_record_cannot_be_bulk_approved" in (
        domain.items[0].blocking_reasons
    )
    assert review_state(registry, "vbulk")[0]["review_status"] == (
        "technical_reviewed"
    )


def test_unresolved_critical_safety_and_duplicate_findings_are_blocked(
    tmp_path: Path,
) -> None:
    registry, audit_root, records, recommendations = _environment(
        tmp_path, [_record(0, status="technical_reviewed")]
    )
    assessments = [{
        "record_id": "vbulk-000",
        "record_sha256": records[0]["example_sha256"],
        "overall_score": 90,
        "findings": [
            {
                "check": "credential_solicitation",
                "severity": "critical",
                "message": "Unsafe credential request.",
            },
            {
                "check": "near_duplicate_prompt",
                "severity": "medium",
                "message": "Prompt duplicates another record.",
            },
            {
                "check": "provenance_evidence",
                "severity": "medium",
                "message": "Provenance evidence needs resolution.",
            },
            {
                "check": "license_review",
                "severity": "medium",
                "message": "Licence evidence needs resolution.",
            },
        ],
    }]
    preview = _preview(
        records,
        recommendations,
        audit_root,
        action="approve",
        assessments=assessments,
    )

    assert preview.allowed_count == 0
    assert set(preview.items[0].blocking_reasons) >= {
        "unresolved_critical_finding",
        "unresolved_safety_finding",
        "unresolved_duplicate_finding",
        "unresolved_provenance_finding",
        "unresolved_licensing_finding",
    }
    assert preview.items[0].unresolved_findings


def test_technical_review_and_approval_are_separate_and_control_eligibility(
    tmp_path: Path,
) -> None:
    registry, audit_root, records, recommendations = _environment(
        tmp_path, [_record(0)]
    )
    immutable_snapshot = snapshot_path(registry, "vbulk").read_bytes()
    technical_preview = _preview(
        records,
        recommendations,
        audit_root,
        action="technical-review",
    )
    technical_result = _execute(
        technical_preview, registry, audit_root, recommendations
    )
    after_technical = review_state(registry, "vbulk")[0]

    assert technical_result["records_written"] == 1
    assert after_technical["review_status"] == "technical_reviewed"
    assert not assess_eligibility(after_technical, "vbulk").eligible

    approval_preview = _preview(
        [after_technical],
        recommendations,
        audit_root,
        action="approve",
    )
    approval_result = _execute(
        approval_preview, registry, audit_root, recommendations
    )
    approved = review_state(registry, "vbulk")[0]

    assert approval_result["records_written"] == 1
    assert approved["review_status"] == "approved"
    assert assess_eligibility(approved, "vbulk").eligible
    assert approval_result["training_eligibility_after"]["vbulk-000"] is True
    assert snapshot_path(registry, "vbulk").read_bytes() == immutable_snapshot


def test_each_record_gets_separate_batch_linked_immutable_audit_event(
    tmp_path: Path,
) -> None:
    registry, audit_root, records, recommendations = _environment(
        tmp_path, [_record(0), _record(1)]
    )
    preview = _preview(
        records,
        recommendations,
        audit_root,
        action="technical-review",
    )
    result = _execute(preview, registry, audit_root, recommendations)
    human_events = read_jsonl(audit_path(audit_root, "vbulk", human=True))

    assert result["records_written"] == 2
    assert len(human_events) == 2
    assert len({event["event_sha256"] for event in human_events}) == 2
    assert {event["record_id"] for event in human_events} == {
        "vbulk-000",
        "vbulk-001",
    }
    assert {
        event["batch_operation_id"] for event in human_events
    } == {preview.batch_operation_id}
    assert all(event["related_recommendation_id"] for event in human_events)
    required = {
        "reviewer_identifier",
        "reviewer_role",
        "action",
        "decision_note",
        "prior_status",
        "new_status",
        "record_revision",
        "record_sha256",
        "related_recommendation_id",
        "timestamp",
        "event_sha256",
        "batch_operation_id",
    }
    assert all(required <= set(event) for event in human_events)


def test_batch_selection_is_deterministic_by_record_id(tmp_path: Path) -> None:
    registry, audit_root, records, recommendations = _environment(
        tmp_path, [_record(2), _record(0), _record(1)]
    )
    first = _preview(
        records,
        recommendations,
        audit_root,
        action="technical-review",
        limit=2,
    )
    second = _preview(
        list(reversed(records)),
        list(reversed(recommendations)),
        audit_root,
        action="technical-review",
        limit=2,
    )

    assert [item.record_id for item in first.items] == [
        "vbulk-000",
        "vbulk-001",
    ]
    assert first.preview_sha256 == second.preview_sha256
    assert first.batch_operation_id == second.batch_operation_id
    assert snapshot_path(registry, "vbulk").is_file()


def test_confirmation_phrase_and_authenticated_identity_are_required(
    tmp_path: Path,
) -> None:
    registry, audit_root, records, recommendations = _environment(
        tmp_path, [_record(0)]
    )
    preview = _preview(
        records, recommendations, audit_root, action="technical-review"
    )

    with pytest.raises(DatasetManagementError, match="requires --confirm"):
        _execute(
            preview,
            registry,
            audit_root,
            recommendations,
            confirmation="yes",
        )
    with pytest.raises(DatasetManagementError, match="authenticated reviewer"):
        execute_bulk_review(
            preview,
            load_review_config(),
            registry_dir=registry,
            releases_dir=tmp_path / "releases",
            audit_root=audit_root,
            recommendations=recommendations,
            confirmation=CONFIRMATION_PHRASE,
            authenticated_reviewer_id="somebody-else",
            dry_run=False,
        )
    assert not audit_path(audit_root, "vbulk", human=True).exists()


def test_ai_approve_candidate_cannot_bypass_human_review_gates(
    tmp_path: Path,
) -> None:
    registry, audit_root, records, recommendations = _environment(
        tmp_path, [_record(0, status="draft")]
    )
    assert recommendations[0]["recommendation"] == "approve_candidate"
    preview = _preview(
        records, recommendations, audit_root, action="approve"
    )

    assert preview.allowed_count == 0
    assert any(
        reason.startswith("invalid_transition:draft->approved")
        for reason in preview.items[0].blocking_reasons
    )
    assert "technical_review_incomplete" in preview.items[0].blocking_reasons
    assert review_state(registry, "vbulk")[0]["review_status"] == "draft"


def test_cli_defaults_to_dry_run_and_writes_nothing(tmp_path: Path) -> None:
    registry, audit_root, _, recommendations = _environment(
        tmp_path, [_record(0)]
    )
    reviews_root = tmp_path / "reviews"
    recommendation_path = reviews_root / "vbulk" / "recommendations.jsonl"
    recommendation_path.parent.mkdir(parents=True)
    recommendation_path.write_text(
        "".join(json.dumps(value) + "\n" for value in recommendations),
        encoding="utf-8",
    )
    note_file = tmp_path / "note.txt"
    note_file.write_text(
        "I reviewed each selected low-risk record.", encoding="utf-8"
    )
    before = snapshot_path(registry, "vbulk").read_bytes()
    command = [
        sys.executable,
        "scripts/review_automation.py",
        "bulk-human-review",
        "--version",
        "vbulk",
        "--registry",
        str(registry),
        "--releases",
        str(tmp_path / "releases"),
        "--category",
        "small_business",
        "--reviewer-id",
        "reviewer-technical-01",
        "--reviewer-role",
        "technical_reviewer",
        "--action",
        "technical-review",
        "--note-file",
        str(note_file),
        "--limit",
        "1",
        "--audit-dir",
        str(audit_root),
        "--reviews-root",
        str(reviews_root),
        "--quality-root",
        str(tmp_path / "quality"),
    ]

    completed = subprocess.run(
        command,
        cwd=Path(__file__).resolve().parents[1],
        check=True,
        capture_output=True,
        text=True,
    )
    result = json.loads(completed.stdout)

    assert result["execution"]["dry_run"] is True
    assert result["execution"]["write_performed"] is False
    assert "bulk_human_review_preview" in completed.stderr
    assert snapshot_path(registry, "vbulk").read_bytes() == before
    assert not audit_path(audit_root, "vbulk", human=True).exists()
