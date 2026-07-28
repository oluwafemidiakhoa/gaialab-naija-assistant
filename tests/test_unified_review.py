from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from src.dataset_management import (
    DatasetManagementError,
    example_sha256,
    import_version,
    review_state,
    snapshot_path,
)
from src.review_automation.analyzer import ReviewAnalyzer
from src.review_automation.audit import append_audit_event, automated_event
from src.review_automation.config import load_review_config
from src.review_automation.guided import (
    PilotProgress,
    approval_blockers,
    filter_identity,
    pilot_summary,
    queue_summary,
    record_action_and_advance,
    review_next,
)
from src.review_automation.queue import QueueFilters, build_queue
from src.review_automation.release_state import (
    publication_readiness,
    release_status,
)
from src.review_automation.revisions import (
    apply_human_decision,
    apply_revision_action,
)


def _record(record_id: str, *, status: str = "draft") -> dict:
    return {
        "id": record_id,
        "category": "business_writing",
        "risk_level": "low",
        "messages": [
            {"role": "system", "content": "Be safe."},
            {"role": "user", "content": f"Write follow-up {record_id}."},
            {"role": "assistant", "content": "Try this"},
        ],
        "source": "synthetic",
        "license": "CC0-1.0",
        "review_status": status,
    }


def _registry(tmp_path: Path, count: int = 3) -> Path:
    source = tmp_path / "source.jsonl"
    source.write_text(
        "".join(json.dumps(_record(f"vpilot-{index:03d}")) + "\n"
                for index in range(count)),
        encoding="utf-8",
    )
    registry = tmp_path / "registry"
    import_version(source, registry, "vpilot")
    return registry


def _recommendation(registry: Path, record_id: str = "vpilot-000"):
    records = review_state(registry, "vpilot")
    record = next(row for row in records if row["id"] == record_id)
    return ReviewAnalyzer(load_review_config()).analyze(
        record,
        records=records,
        generated_at="2026-07-28T12:00:00+00:00",
    )


def _snapshot(registry: Path, recommendations=()):
    records = review_state(registry, "vpilot")
    return build_queue(
        records,
        "vpilot",
        load_review_config(),
        recommendations=recommendations,
        page_size=500,
        generated_at="2026-07-28T12:00:00+00:00",
    )


def test_review_next_is_deterministic_advances_and_skips(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    snapshot = _snapshot(registry)
    progress = PilotProgress(target=2)
    first = review_next(snapshot, progress)
    assert first is not None
    same = review_next(snapshot, progress)
    assert same.record_id == first.record_id
    progress = record_action_and_advance(progress, first.record_id, "skip")
    second = review_next(snapshot, progress)
    assert second is not None and second.record_id != first.record_id
    progress = record_action_and_advance(
        progress, second.record_id, "request_revision"
    )
    assert progress.complete
    assert review_next(snapshot, progress) is None


def test_pilot_limit_summary_and_queue_cards(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    records = review_state(registry, "vpilot")
    snapshot = _snapshot(registry)
    progress = PilotProgress(target=1).record("vpilot-000", "skip")
    summary = pilot_summary(
        progress,
        records,
        version="vpilot",
        domain_review_categories=(),
    )
    assert summary["completed"] == 1
    assert summary["remaining"] == 0
    assert summary["skipped"] == 1
    cards = queue_summary(snapshot)
    assert cards["total_matching"] == 3
    assert cards["technical_review_backlog"] == 3


def test_recommendation_filter_and_finalized_default(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    recommendation = _recommendation(registry)
    rows = [recommendation.to_dict()]
    snapshot = build_queue(
        review_state(registry, "vpilot"),
        "vpilot",
        load_review_config(),
        recommendations=rows,
        filters=QueueFilters(
            recommendation=(recommendation.recommendation.value,)
        ),
        page_size=500,
        generated_at="2026-07-28T12:00:00+00:00",
    )
    assert [item.record_id for item in snapshot.items] == ["vpilot-000"]
    assert not QueueFilters().include_finalized


def test_approval_blockers_explain_technical_and_domain_gates(
    tmp_path: Path,
) -> None:
    registry = _registry(tmp_path)
    record = review_state(registry, "vpilot")[0]
    recommendation = _recommendation(registry)
    assert "technical_review_incomplete" in approval_blockers(
        record, recommendation
    )
    domain_record = {**record, "category": "healthcare"}
    domain_record["example_sha256"] = example_sha256(domain_record)
    domain_recommendation = ReviewAnalyzer(load_review_config()).analyze(
        domain_record,
        records=[domain_record],
        generated_at="2026-07-28T12:00:00+00:00",
    )
    assert "domain_review_incomplete" in approval_blockers(
        domain_record, domain_recommendation
    )


def test_reject_confirmation_and_escalation_target_are_required(
    tmp_path: Path,
) -> None:
    registry = _registry(tmp_path)
    audit = tmp_path / "audit"
    recommendation = _recommendation(registry)
    append_audit_event(audit, automated_event(recommendation))
    with pytest.raises(DatasetManagementError, match="confirmation"):
        apply_human_decision(
            registry, audit, "vpilot", "vpilot-000", "reject",
            "reviewer-1", "reviewer", recommendation=recommendation,
            decision_note="Unsafe response.",
        )
    with pytest.raises(DatasetManagementError, match="escalation target"):
        apply_human_decision(
            registry, audit, "vpilot", "vpilot-000", "escalate",
            "reviewer-1", "reviewer", recommendation=recommendation,
            decision_note="Needs specialist review.",
        )


def test_human_edited_suggestion_creates_revision_without_mutation(
    tmp_path: Path,
) -> None:
    registry = _registry(tmp_path)
    audit = tmp_path / "audit"
    recommendation = _recommendation(registry)
    append_audit_event(audit, automated_event(recommendation))
    snapshot = snapshot_path(registry, "vpilot")
    before = snapshot.read_bytes()
    original_suggestion = recommendation.suggested_revision
    result = apply_revision_action(
        registry,
        audit,
        "vpilot",
        "vpilot-000",
        "edit_suggested_revision",
        "reviewer-1",
        "reviewer",
        recommendation=recommendation,
        decision_note="Human-edited for clarity.",
        edited_prompt="Write a polite delivery follow-up.",
        edited_response="Good day. Please confirm the delivery date. Thank you.",
    )
    assert result["new_revision"] == 2
    assert snapshot.read_bytes() == before
    current = review_state(registry, "vpilot")[0]
    assert current["messages"][1]["content"] == (
        "Write a polite delivery follow-up."
    )
    assert recommendation.suggested_revision == original_suggestion


def test_release_state_never_infers_published_and_v07_is_not_created(
    tmp_path: Path,
) -> None:
    state = release_status(
        "v0.7",
        registry_dir=tmp_path / "registry",
        releases_dir=tmp_path / "releases",
        candidate_root=tmp_path / "candidates",
        publication_registry=tmp_path / "publication.jsonl",
    )
    assert state == {
        "version": "v0.7",
        "exists_locally": False,
        "local_dataset_version": False,
        "release_candidate_exists": False,
        "verified": False,
        "approved_for_publication": False,
        "published": False,
        "status": "not_created",
        "publication_evidence_count": 0,
        "publication_inferred_from_folder": False,
    }


def test_local_release_folder_does_not_mean_published(tmp_path: Path) -> None:
    releases = tmp_path / "releases" / "vpilot"
    releases.mkdir(parents=True)
    (releases / "vpilot.jsonl").write_text("{}\n", encoding="utf-8")
    state = release_status(
        "vpilot",
        registry_dir=tmp_path / "registry",
        releases_dir=tmp_path / "releases",
        candidate_root=tmp_path / "candidates",
        publication_registry=tmp_path / "publication.jsonl",
    )
    assert state["exists_locally"]
    assert state["status"] == "under_review"
    assert not state["published"]


def test_publication_state_requires_explicit_registry_evidence(
    tmp_path: Path,
) -> None:
    releases = tmp_path / "releases" / "vpilot"
    releases.mkdir(parents=True)
    (releases / "vpilot.jsonl").write_text("{}\n", encoding="utf-8")
    candidates = tmp_path / "candidates" / "vpilot"
    candidates.mkdir(parents=True)
    (candidates / "release_candidate_manifest.json").write_text(
        "{}\n", encoding="utf-8"
    )
    events = tmp_path / "publication.jsonl"
    events.write_text(
        "\n".join(json.dumps({
            "version": "vpilot",
            "event": event,
        }) for event in (
            "release_verified",
            "publication_approved",
            "dataset_published",
        )) + "\n",
        encoding="utf-8",
    )
    state = release_status(
        "vpilot",
        registry_dir=tmp_path / "registry",
        releases_dir=tmp_path / "releases",
        candidate_root=tmp_path / "candidates",
        publication_registry=events,
    )
    assert state["release_candidate_exists"]
    assert state["verified"]
    assert state["approved_for_publication"]
    assert state["published"]
    assert state["status"] == "published"


def test_publication_readiness_is_read_only_and_reports_blockers(
    tmp_path: Path,
) -> None:
    registry = _registry(tmp_path)
    before = sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*"))
    report = publication_readiness(
        "vpilot",
        registry_dir=registry,
        releases_dir=tmp_path / "releases",
        candidate_root=tmp_path / "candidates",
        publication_registry=tmp_path / "publication.jsonl",
        assessments=[],
    )
    after = sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*"))
    assert before == after
    assert not report["ready_for_publication"]
    assert "human_review_incomplete" in report["blocking_reasons"]
    assert "release_candidate_missing" in report["blocking_reasons"]
    assert not report["upload_performed"]
    assert not report["git_operation_performed"]


def test_streamlit_filter_identity_is_deterministic() -> None:
    filters = QueueFilters(category=("business_writing",))
    assert filter_identity("v0.6", filters, 5) == filter_identity(
        "v0.6", filters, 5
    )


def test_release_status_cli_is_read_only_for_missing_v07(tmp_path: Path) -> None:
    command = [
        sys.executable,
        "scripts/review_automation.py",
        "release-status",
        "--version",
        "v0.7",
        "--registry",
        str(tmp_path / "registry"),
        "--releases",
        str(tmp_path / "releases"),
        "--candidate-root",
        str(tmp_path / "candidates"),
        "--publication-registry",
        str(tmp_path / "publication.jsonl"),
    ]
    completed = subprocess.run(
        command,
        cwd=Path(__file__).resolve().parents[1],
        check=True,
        capture_output=True,
        text=True,
    )
    result = json.loads(completed.stdout)
    assert result["status"] == "not_created"
    assert not result["published"]
    assert list(tmp_path.iterdir()) == []


def test_publication_readiness_cli_has_no_upload_or_git_side_effect(
    tmp_path: Path,
) -> None:
    registry = _registry(tmp_path)
    project = Path(__file__).resolve().parents[1]
    git_index = project / ".git" / "index"
    index_before = git_index.read_bytes()
    files_before = sorted(
        path.relative_to(tmp_path) for path in tmp_path.rglob("*")
    )
    command = [
        sys.executable,
        "scripts/review_automation.py",
        "publication-readiness",
        "--version",
        "vpilot",
        "--registry",
        str(registry),
        "--releases",
        str(tmp_path / "releases"),
        "--candidate-root",
        str(tmp_path / "candidates"),
        "--publication-registry",
        str(tmp_path / "publication.jsonl"),
    ]
    completed = subprocess.run(
        command,
        cwd=project,
        check=True,
        capture_output=True,
        text=True,
    )
    result = json.loads(completed.stdout)
    files_after = sorted(
        path.relative_to(tmp_path) for path in tmp_path.rglob("*")
    )
    assert files_after == files_before
    assert git_index.read_bytes() == index_before
    assert not result["upload_performed"]
    assert not result["git_operation_performed"]
