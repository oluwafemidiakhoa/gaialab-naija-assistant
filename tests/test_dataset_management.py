from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.dataset_management import (
    DatasetManagementError,
    dataset_statistics,
    example_sha256,
    import_version,
    publish_version,
    read_jsonl,
    review_record,
    review_state,
    semantic_duplicates,
)


def record(record_id: str, prompt: str = "How do I confirm this payment?") -> dict:
    return {
        "id": record_id,
        "category": "banking",
        "risk_level": "medium",
        "messages": [
            {"role": "system", "content": "Be safe."},
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": "Check through an official channel."},
        ],
        "source": "synthetic",
        "license": "CC0-1.0",
        "status": "draft",
        "review_notes": "",
    }


def write_jsonl(path: Path, records: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(value) + "\n" for value in records), encoding="utf-8"
    )


def test_import_enriches_every_record_and_refuses_overwrite(tmp_path: Path) -> None:
    source = tmp_path / "source.jsonl"
    registry = tmp_path / "registry"
    write_jsonl(source, [record("v06-test-001")])

    snapshot = import_version(source, registry, "v0.6")
    imported = read_jsonl(snapshot)[0]

    assert imported["dataset_version"] == "v0.6"
    assert imported["revision"] == 1
    assert imported["review_status"] == "draft"
    assert imported["reviewer"] == ""
    assert imported["review_date"] == ""
    assert imported["quality_score"] is None
    assert imported["example_sha256"] == example_sha256(imported)
    assert len(imported["example_sha256"]) == 64

    with pytest.raises(DatasetManagementError, match="overwrite"):
        import_version(source, registry, "v0.6")


def test_approved_record_is_immutable_and_edit_creates_draft_revision(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.jsonl"
    registry = tmp_path / "registry"
    write_jsonl(source, [record("v06-test-001")])
    import_version(source, registry, "v0.6")

    approved = review_record(
        registry, "v0.6", "v06-test-001", "approved", "reviewer-1", 4.5, "Good."
    )
    with pytest.raises(DatasetManagementError, match="immutable"):
        review_record(
            registry, "v0.6", "v06-test-001", "rejected", "reviewer-2", 2, "No."
        )

    edited = [dict(message) for message in approved["messages"]]
    edited[2]["content"] = "Check the payment through your bank's official channel."
    revision = review_record(
        registry,
        "v0.6",
        "v06-test-001",
        "approved",
        "reviewer-2",
        4.0,
        "Edited.",
        edited_messages=edited,
    )

    assert revision["revision"] == 2
    assert revision["review_status"] == "draft"
    assert revision["supersedes_sha256"] == approved["example_sha256"]
    assert revision["example_sha256"] != approved["example_sha256"]
    assert len(read_jsonl(registry / "reviews/v0.6.jsonl")) == 2


def test_semantic_duplicates_compare_all_versions(tmp_path: Path) -> None:
    registry = tmp_path / "registry"
    first = tmp_path / "first.jsonl"
    second = tmp_path / "second.jsonl"
    write_jsonl(first, [record("v06-one", "Please confirm whether my payment arrived")])
    write_jsonl(second, [record("v07-two", "Please confirm whether my payment arrived")])
    import_version(first, registry, "v0.6")
    import_version(second, registry, "v0.7")

    duplicates = semantic_duplicates(registry, threshold=0.9)

    assert len(duplicates) == 1
    assert duplicates[0]["version_a"] == "v0.6"
    assert duplicates[0]["version_b"] == "v0.7"
    assert duplicates[0]["similarity"] == 1.0


def test_publish_writes_all_formats_and_release_is_write_once(tmp_path: Path) -> None:
    registry = tmp_path / "registry"
    source = tmp_path / "source.jsonl"
    releases = tmp_path / "releases"
    write_jsonl(source, [record("v06-test-001")])
    import_version(source, registry, "v0.6")

    outputs = publish_version(registry, "v0.6", releases)

    assert set(outputs) == {
        "jsonl", "csv", "statistics", "semantic_duplicates", "manifest"
    }
    manifest = json.loads(outputs["manifest"].read_text(encoding="utf-8"))
    assert manifest["immutable_release"] is True
    assert manifest["record_count"] == 1
    assert set(manifest["files"]) == {
        "jsonl", "csv", "statistics", "semantic_duplicates"
    }
    with pytest.raises(DatasetManagementError, match="already exists"):
        publish_version(registry, "v0.6", releases)


def test_statistics_include_review_metadata(tmp_path: Path) -> None:
    registry = tmp_path / "registry"
    source = tmp_path / "source.jsonl"
    write_jsonl(source, [record("v06-test-001"), record("v06-test-002", "Another")])
    import_version(source, registry, "v0.6")
    review_record(
        registry, "v0.6", "v06-test-001", "approved", "reviewer-1", 5, "Ready."
    )

    statistics = dataset_statistics(review_state(registry, "v0.6"))

    assert statistics["record_count"] == 2
    assert statistics["review_status_counts"] == {"approved": 1, "draft": 1}
    assert statistics["reviewed_records"] == 1
    assert statistics["mean_quality_score"] == 5.0
