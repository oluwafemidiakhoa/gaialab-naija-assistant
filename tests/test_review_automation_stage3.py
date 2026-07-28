from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from app.ai_assisted_review import (
    available_decisions,
    current_recommendation,
    dataset_summary,
)
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
from src.review_automation.config import DEFAULT_CONFIG_PATH, load_review_config
from src.review_automation.refresh import refresh_review_outputs
from src.review_automation.revisions import (
    apply_human_decision,
    apply_revision_action,
)
from src.review_automation.service import write_analysis_run


def _registry(tmp_path: Path, *, response: str | None = None) -> Path:
    row = {
        "id": "vstage3-001",
        "category": "small_business",
        "risk_level": "low",
        "messages": [
            {"role": "system", "content": "Be safe and concise."},
            {"role": "user", "content": "Write a polite supplier follow-up."},
            {
                "role": "assistant",
                "content": response or (
                    "Good day. Please confirm the delivery date. Thank you."
                ),
            },
        ],
        "source": "synthetic",
        "license": "CC0-1.0",
    }
    source = tmp_path / "source.jsonl"
    source.write_text(json.dumps(row) + "\n", encoding="utf-8")
    registry = tmp_path / "registry"
    import_version(source, registry, "vstage3")
    return registry


def _recommendation(registry: Path):
    row = review_state(registry, "vstage3")[0]
    return ReviewAnalyzer(load_review_config()).analyze(
        row,
        records=[row],
        generated_at="2026-07-28T12:00:00+00:00",
    )


def test_automated_audit_is_deterministic_separate_and_idempotent(
    tmp_path: Path,
) -> None:
    registry = _registry(tmp_path)
    recommendation = _recommendation(registry)
    first = automated_event(recommendation)
    second = automated_event(recommendation)
    assert first == second
    audit_root = tmp_path / "audit"
    assert append_audit_event(audit_root, first)
    assert not append_audit_event(audit_root, second)
    assert len(read_jsonl(audit_path(
        audit_root, "vstage3", human=False
    ))) == 1
    assert not audit_path(audit_root, "vstage3", human=True).exists()


def test_analysis_run_contains_audit_and_appends_central_event(
    tmp_path: Path,
) -> None:
    registry = _registry(tmp_path)
    recommendation = _recommendation(registry)
    summary = {
        "dataset_version": "vstage3",
        "generated_at": "2026-07-28T12:00:00+00:00",
        "recommendation_count": 1,
        "skipped_existing_count": 0,
        "provider": "local",
        "recommendation_counts": {
            recommendation.recommendation.value: 1,
        },
    }
    outputs = write_analysis_run(
        [recommendation],
        summary,
        tmp_path / "reviews",
        audit_root=tmp_path / "audit",
    )
    assert outputs["automated_audit"].is_file()
    assert read_jsonl(outputs["automated_audit"])[0]["event_type"] == (
        "automated_recommendation"
    )
    assert audit_path(tmp_path / "audit", "vstage3", human=False).is_file()


def test_human_approval_requires_confirmation_and_existing_gates(
    tmp_path: Path,
) -> None:
    registry = _registry(tmp_path)
    audit_root = tmp_path / "audit"
    recommendation = _recommendation(registry)
    append_audit_event(audit_root, automated_event(recommendation))
    apply_human_decision(
        registry,
        audit_root,
        "vstage3",
        "vstage3-001",
        "acknowledge_analysis",
        "reviewer-01",
        "reviewer",
        recommendation=recommendation,
    )
    apply_human_decision(
        registry,
        audit_root,
        "vstage3",
        "vstage3-001",
        "technical_review",
        "reviewer-02",
        "technical_reviewer",
        recommendation=recommendation,
        quality_score=90,
    )
    with pytest.raises(DatasetManagementError, match="confirmation"):
        apply_human_decision(
            registry,
            audit_root,
            "vstage3",
            "vstage3-001",
            "approve",
            "reviewer-02",
            "technical_reviewer",
            recommendation=recommendation,
        )
    result = apply_human_decision(
        registry,
        audit_root,
        "vstage3",
        "vstage3-001",
        "approve",
        "reviewer-02",
        "technical_reviewer",
        recommendation=recommendation,
        confirm_approval=True,
    )
    assert result["new_status"] == "approved"
    human_rows = read_jsonl(audit_path(audit_root, "vstage3", human=True))
    assert [row["event_type"] for row in human_rows] == ["human_decision"] * 3
    assert all(row["related_recommendation_id"] for row in human_rows)


def test_rejection_revision_and_escalation_require_a_note(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    recommendation = _recommendation(registry)
    append_audit_event(tmp_path / "audit", automated_event(recommendation))
    with pytest.raises(DatasetManagementError, match="decision note"):
        apply_human_decision(
            registry,
            tmp_path / "audit",
            "vstage3",
            "vstage3-001",
            "reject",
            "reviewer-01",
            "reviewer",
            recommendation=recommendation,
        )


def test_human_action_rejects_an_unaudited_recommendation(
    tmp_path: Path,
) -> None:
    registry = _registry(tmp_path)
    with pytest.raises(DatasetManagementError, match="automated audit"):
        apply_human_decision(
            registry,
            tmp_path / "audit",
            "vstage3",
            "vstage3-001",
            "acknowledge_analysis",
            "reviewer-01",
            "reviewer",
            recommendation=_recommendation(registry),
        )


def test_suggestion_acceptance_creates_child_and_preserves_snapshot(
    tmp_path: Path,
) -> None:
    registry = _registry(tmp_path, response="Try this")
    recommendation = _recommendation(registry)
    assert recommendation.suggested_revision is not None
    append_audit_event(tmp_path / "audit", automated_event(recommendation))
    source_snapshot = snapshot_path(registry, "vstage3")
    before = source_snapshot.read_bytes()
    result = apply_revision_action(
        registry,
        tmp_path / "audit",
        "vstage3",
        "vstage3-001",
        "accept_suggested_revision",
        "reviewer-01",
        "reviewer",
        recommendation=recommendation,
        decision_note="Accepted punctuation improvement.",
        now=lambda: "2026-07-28T12:01:00+00:00",
    )
    assert result["new_revision"] == 2
    assert result["new_status"] == "draft"
    assert source_snapshot.read_bytes() == before
    current = review_state(registry, "vstage3")[0]
    assert current["parent_record_sha256"] == recommendation.input_record_sha256


def test_refresh_is_write_once_and_never_builds_a_release(
    tmp_path: Path,
) -> None:
    registry = _registry(tmp_path)
    records = review_state(registry, "vstage3")
    source_snapshot = snapshot_path(registry, "vstage3")
    before = source_snapshot.read_bytes()
    output_root = tmp_path / "refresh"
    release_root = tmp_path / "releases"
    first = refresh_review_outputs(
        records,
        "vstage3",
        output_root=output_root,
        release_root=release_root,
        generated_at="2026-07-28T12:00:00+00:00",
    )
    second = refresh_review_outputs(
        records,
        "vstage3",
        output_root=output_root,
        release_root=release_root,
        generated_at="2026-07-28T12:00:00+00:00",
    )
    assert first["outputs"]["eligibility_decisions"].is_file()
    eligibility = read_jsonl(first["outputs"]["eligibility_decisions"])[0]
    assert not eligibility["eligible"]
    assert "not_approved" in eligibility["reasons"]
    assert first["outputs"]["review_progress"] != second["outputs"]["review_progress"]
    assert not first["release_created"]
    assert not release_root.exists()
    assert source_snapshot.read_bytes() == before


def test_refresh_cli_writes_reports_without_status_changes(
    tmp_path: Path,
) -> None:
    registry = _registry(tmp_path)
    snapshot = snapshot_path(registry, "vstage3")
    before = snapshot.read_bytes()
    output = tmp_path / "refresh"
    command = [
        sys.executable,
        "scripts/review_automation.py",
        "--config",
        str(DEFAULT_CONFIG_PATH),
        "refresh",
        "--version",
        "vstage3",
        "--registry",
        str(registry),
        "--releases",
        str(tmp_path / "releases"),
        "--output-dir",
        str(output),
    ]
    completed = subprocess.run(
        command,
        cwd=Path(__file__).resolve().parents[1],
        check=True,
        capture_output=True,
        text=True,
    )
    result = json.loads(completed.stdout)
    assert result["official_status_changes"] == 0
    assert not result["release_created"]
    assert Path(result["outputs"]["review_progress"]).is_file()
    assert snapshot.read_bytes() == before


def test_streamlit_helpers_preserve_human_review_gates(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    record = review_state(registry, "vstage3")[0]
    recommendation = _recommendation(registry)
    assert available_decisions(
        "technical_reviewed", domain_review_required=True
    )[0] == "domain_review"
    assert "approve" not in available_decisions(
        "technical_reviewed", domain_review_required=True
    )
    loaded = current_recommendation([recommendation.to_dict()], record)
    assert loaded == recommendation
    summary = dataset_summary([record], [], "vstage3")
    assert summary["draft"] == 1
    assert summary["approved"] == 0
