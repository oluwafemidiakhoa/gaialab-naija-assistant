from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.run_governed_v08_review import (
    CONFIRMATION,
    ReviewPaths,
    assert_identity,
    orchestrate,
)
from src.dataset_management import import_version, read_jsonl, review_state
from src.review_automation.analyzer import ReviewAnalyzer
from src.review_automation.audit import append_audit_event, audit_path, automated_event
from src.review_automation.config import load_review_config
from src.review_automation.refresh import refresh_review_outputs
from src.review_automation.service import load_latest_recommendations


VERSION = "v0.8-draft"
CATEGORY = "payment_received_confirmation"


def _record(index: int, *, duplicate: bool = False) -> dict:
    prompt = (
        "Please confirm that our Abuja payment was received and include a receipt reference."
        if duplicate or index == 0
        else "Write a polite confirmation that the Kano customer payment has arrived."
    )
    response = (
        "Good day. We confirm receipt of your Abuja payment. We will share the receipt reference separately. Thank you."
        if duplicate or index == 0
        else "Good day. We confirm that your Kano payment has been received. Thank you."
    )
    return {
        "id": f"v08-orchestrator-{index:03d}",
        "category": CATEGORY,
        "risk_level": "low",
        "messages": [
            {"role": "system", "content": "Be concise, factual, and safe."},
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": response},
        ],
        "source": "synthetic",
        "license": "CC0-1.0",
        "review_status": "draft",
    }


def _environment(tmp_path: Path, rows: list[dict]) -> tuple[ReviewPaths, list[dict]]:
    source = tmp_path / "source.jsonl"
    source.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    paths = ReviewPaths(
        registry=tmp_path / "registry",
        releases=tmp_path / "releases",
        audit=tmp_path / "audit",
        quality=tmp_path / "quality",
        refresh=tmp_path / "refresh",
        automated=tmp_path / "automated",
    )
    import_version(source, paths.registry, VERSION)
    records = review_state(paths.registry, VERSION)
    analyzer = ReviewAnalyzer(load_review_config())
    recommendations = [
        analyzer.analyze(
            record,
            records=records,
            generated_at="2026-08-01T09:00:00+00:00",
        )
        for record in records
    ]
    recommendation_dir = paths.automated / VERSION
    recommendation_dir.mkdir(parents=True)
    (recommendation_dir / "recommendations.jsonl").write_text(
        "".join(json.dumps(item.to_dict(), sort_keys=True) + "\n" for item in recommendations),
        encoding="utf-8",
    )
    for item in recommendations:
        append_audit_event(paths.audit, automated_event(item))
    refresh_review_outputs(
        records,
        VERSION,
        output_root=paths.refresh,
        release_root=paths.releases,
        audit_root=paths.audit,
        generated_at="2026-08-01T10:00:00+00:00",
    )
    return paths, records


def _run(tmp_path: Path, paths: ReviewPaths, **overrides):
    options = {
        "version": VERSION,
        "categories": (CATEGORY,),
        "limit": 20,
        "acknowledgement_reviewer": "olu-reviewer-001",
        "technical_reviewer": "olu-technical-001",
        "release_manager": "olu-release-001",
        "review_note_dir": tmp_path / "notes",
        "summary_output": tmp_path / "reports" / "summary.json",
        "paths": paths,
        "write": False,
        "confirmation": None,
        "stop_on_error": True,
        "stop_before_approval": False,
    }
    options.update(overrides)
    return orchestrate(**options)


def test_dry_run_projects_full_sequence_without_human_writes(tmp_path: Path) -> None:
    paths, _ = _environment(tmp_path, [_record(0)])
    human = audit_path(paths.audit, VERSION, human=True)

    summary = _run(tmp_path, paths)

    category = summary["categories"][0]
    assert category["acknowledged_count"] == 1
    assert category["technically_reviewed_count"] == 1
    assert category["approved_count"] == 1
    assert summary["human_events_before"] == summary["human_events_after"] == 0
    assert not human.exists()
    assert len(summary["commands_executed"]) == 1
    assert "analyze" in summary["commands_executed"][0]
    assert summary["training_performed"] is False
    assert summary["release_created"] is False
    assert summary["publication_performed"] is False


def test_rerun_is_append_only_and_does_not_duplicate_human_events(tmp_path: Path) -> None:
    paths, _ = _environment(tmp_path, [_record(0)])

    first = _run(tmp_path, paths)
    second = _run(tmp_path, paths)

    assert first["summary_outputs"]["json"] != second["summary_outputs"]["json"]
    assert not audit_path(paths.audit, VERSION, human=True).exists()


def test_duplicate_records_are_blocked_but_valid_records_advance(tmp_path: Path) -> None:
    paths, _ = _environment(
        tmp_path, [_record(0), _record(1, duplicate=True), _record(2)]
    )

    summary = _run(tmp_path, paths)
    report = summary["categories"][0]
    technical = next(item for item in report["stages"] if item["stage"] == "technical_review")

    assert technical["allowed_count"] == 1
    assert technical["blocked_count"] == 2
    assert report["duplicate_blocked_count"] == 2
    assert report["approved_count"] == 1


def test_stale_assessment_blocks_technical_review(tmp_path: Path) -> None:
    paths, records = _environment(tmp_path, [_record(0)])
    stale = paths.refresh / VERSION / "run-zzzz"
    stale.mkdir(parents=True)
    (stale / "quality_assessments.jsonl").write_text(
        json.dumps({
            "record_id": records[0]["id"],
            "record_sha256": "0" * 64,
            "assessed_at": "9999-01-01T00:00:00+00:00",
            "overall_score": 100,
            "findings": [],
        }) + "\n",
        encoding="utf-8",
    )

    summary = _run(tmp_path, paths)

    assert summary["categories"][0]["stale_assessment_blocked_count"] == 1
    assert summary["categories"][0]["technically_reviewed_count"] == 0
    assert summary["categories"][0]["approved_count"] == 0


def test_critical_assessment_remains_blocked(tmp_path: Path) -> None:
    paths, records = _environment(tmp_path, [_record(0)])
    critical = paths.refresh / VERSION / "run-critical"
    critical.mkdir(parents=True)
    (critical / "quality_assessments.jsonl").write_text(
        json.dumps({
            "record_id": records[0]["id"],
            "record_sha256": records[0]["example_sha256"],
            "assessed_at": "9999-01-01T00:00:00+00:00",
            "overall_score": 99,
            "findings": [{
                "check": "safety_policy",
                "severity": "critical",
                "message": "Unresolved critical safety finding.",
            }],
        }) + "\n",
        encoding="utf-8",
    )

    summary = _run(tmp_path, paths)

    report = summary["categories"][0]
    assert report["critical_blocked_count"] == 1
    assert report["technically_reviewed_count"] == 0
    assert report["approved_count"] == 0


def test_write_requires_confirmation_and_identity_must_match(tmp_path: Path) -> None:
    paths, _ = _environment(tmp_path, [_record(0)])
    with pytest.raises(ValueError, match="requires --confirm"):
        _run(tmp_path, paths, write=True)
    with pytest.raises(ValueError, match="identity mismatch"):
        assert_identity(
            {"GAIALAB_AUTHENTICATED_REVIEWER_ID": "different-reviewer"},
            "olu-reviewer-001",
        )


def test_pytest_cannot_write_to_live_human_audit_ledger(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "isolation sentinel")
    with pytest.raises(RuntimeError, match="live human audit ledger"):
        _run(
            tmp_path,
            ReviewPaths(),
            write=True,
            confirmation=CONFIRMATION,
        )


def test_preview_write_hash_mismatch_stops_without_human_events(tmp_path: Path) -> None:
    paths, _ = _environment(tmp_path, [_record(0)])

    def stale_runner(command, *, environment=None):
        return {
            "preview": {"preview_sha256": "0" * 64},
            "execution": {"records_written": 0},
        }

    summary = _run(
        tmp_path,
        paths,
        write=True,
        confirmation=CONFIRMATION,
        stop_on_error=False,
        runner=stale_runner,
    )

    assert "preview/write hash mismatch" in summary["failures"][0]["errors"][0]
    assert not audit_path(paths.audit, VERSION, human=True).exists()


def test_stop_before_approval_keeps_approval_out_of_plan(tmp_path: Path) -> None:
    paths, _ = _environment(tmp_path, [_record(0)])

    summary = _run(tmp_path, paths, stop_before_approval=True)

    report = summary["categories"][0]
    assert report["approved_count"] == 0
    assert report["stages"][-1] == {
        "stage": "approval",
        "status": "stopped_by_option",
    }


def test_latest_recommendations_are_aggregated_across_category_runs(tmp_path: Path) -> None:
    root = tmp_path / "reviews" / VERSION
    for name, record_id, timestamp in (
        ("run-a", "record-a", "2026-08-01T10:00:00+00:00"),
        ("run-b", "record-b", "2026-08-01T11:00:00+00:00"),
        ("run-c", "record-a", "2026-08-01T12:00:00+00:00"),
    ):
        directory = root / name
        directory.mkdir(parents=True)
        (directory / "recommendations.jsonl").write_text(
            json.dumps({
                "record_id": record_id,
                "generation_timestamp": timestamp,
                "marker": name,
            }) + "\n",
            encoding="utf-8",
        )

    loaded = load_latest_recommendations(VERSION, reviews_root=tmp_path / "reviews")

    assert [(row["record_id"], row["marker"]) for row in loaded] == [
        ("record-a", "run-c"),
        ("record-b", "run-b"),
    ]


def test_write_sequence_and_completed_rerun_are_idempotent(tmp_path: Path) -> None:
    paths, _ = _environment(tmp_path, [_record(0)])

    first = _run(
        tmp_path,
        paths,
        write=True,
        confirmation=CONFIRMATION,
    )
    events_after_first = read_jsonl(audit_path(paths.audit, VERSION, human=True))
    second = _run(
        tmp_path,
        paths,
        write=True,
        confirmation=CONFIRMATION,
    )
    events_after_second = read_jsonl(audit_path(paths.audit, VERSION, human=True))

    assert [event["new_status"] for event in events_after_first] == [
        "automated_reviewed",
        "technical_reviewed",
        "approved",
    ]
    assert events_after_second == events_after_first
    assert review_state(paths.registry, VERSION)[0]["review_status"] == "approved"
    assert first["categories"][0]["approved_count"] == 1
    assert second["categories"][0]["approved_count"] == 0
    assert second["human_audit_event_count"] == len(events_after_second) == 3
    assert second["final_status_counts"] == {"approved": 1}
    assert second["training_eligible_count"] == 1
