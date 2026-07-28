from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.dataset_management import DatasetManagementError, import_version
from src.review_workflow import create_revision, mark_parent_superseded, transition_review


def _registry(tmp_path: Path, category: str = "business_writing") -> Path:
    row = {
        "id": "v06-test-001", "category": category, "risk_level": "low",
        "messages": [
            {"role": "system", "content": "Be helpful."},
            {"role": "user", "content": "Write a reminder."},
            {"role": "assistant", "content": "Please pay the outstanding invoice."},
        ],
        "source": "synthetic", "license": "CC-BY-4.0",
    }
    source = tmp_path / "source.jsonl"
    source.write_text(json.dumps(row) + "\n", encoding="utf-8")
    registry = tmp_path / "registry"
    import_version(source, registry, "v0.6")
    return registry


def _step(registry: Path, status: str, role: str = "technical_reviewer"):
    return transition_review(
        registry, "v0.6", "v06-test-001", status, "human-01", role,
        now=lambda: f"2026-01-01T00:00:0{len(status) % 10}+00:00",
    )


def test_permitted_low_risk_approval_path(tmp_path):
    registry = _registry(tmp_path)
    _step(registry, "automated_reviewed", "reviewer")
    _step(registry, "technical_reviewed")
    event = _step(registry, "approved")
    assert event.new_status == "approved"
    assert len(event.event_sha256) == 64


def test_invalid_transition_rejected(tmp_path):
    with pytest.raises(DatasetManagementError, match="invalid review transition"):
        _step(_registry(tmp_path), "approved")


def test_domain_review_required(tmp_path):
    registry = _registry(tmp_path, "healthcare")
    _step(registry, "automated_reviewed", "reviewer")
    _step(registry, "technical_reviewed")
    with pytest.raises(DatasetManagementError, match="domain review"):
        _step(registry, "approved")
    _step(registry, "domain_reviewed", "domain_reviewer")
    assert _step(registry, "approved", "domain_reviewer").new_status == "approved"


def test_approved_record_is_immutable_and_revision_is_draft(tmp_path):
    registry = _registry(tmp_path)
    _step(registry, "automated_reviewed", "reviewer")
    _step(registry, "technical_reviewed")
    _step(registry, "approved")
    messages = [
        {"role": "system", "content": "Be helpful."},
        {"role": "user", "content": "Write a kind reminder."},
        {"role": "assistant", "content": "Kindly settle the outstanding invoice."},
    ]
    revision = create_revision(registry, "v0.6", "v06-test-001", messages, "human-01")
    assert revision["revision"] == 2
    assert revision["review_status"] == "draft"
    assert revision["parent_record_sha256"]


def test_rejection_is_final(tmp_path):
    registry = _registry(tmp_path)
    _step(registry, "rejected", "reviewer")
    with pytest.raises(DatasetManagementError):
        _step(registry, "draft", "reviewer")


def test_approved_child_can_link_superseded_parent(tmp_path):
    registry = _registry(tmp_path)
    _step(registry, "automated_reviewed", "reviewer")
    _step(registry, "technical_reviewed")
    _step(registry, "approved")
    current = create_revision(
        registry, "v0.6", "v06-test-001",
        [
            {"role": "system", "content": "Be helpful."},
            {"role": "user", "content": "Write a revised reminder."},
            {"role": "assistant", "content": "Kindly settle the revised invoice."},
        ],
        "human-01",
    )
    parent = current["parent_record_sha256"]
    _step(registry, "automated_reviewed", "reviewer")
    _step(registry, "technical_reviewed")
    _step(registry, "approved")
    linked = mark_parent_superseded(registry, "v0.6", "v06-test-001", "human-01")
    assert linked["supersedes_sha256"] == parent
