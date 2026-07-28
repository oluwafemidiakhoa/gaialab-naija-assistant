from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from src.dataset_management import enrich_record, import_version, publish_version
from src.release_verification import (
    ReleaseVerificationError,
    certificate_json,
    verify_release,
)


def record(
    record_id: str = "v06-test-001",
    *,
    supersedes_sha256: str = "",
) -> dict:
    return {
        "id": record_id,
        "category": "banking",
        "risk_level": "medium",
        "messages": [
            {"role": "system", "content": "Be safe."},
            {"role": "user", "content": "How can I confirm this transfer?"},
            {
                "role": "assistant",
                "content": "Check through your bank's official channel.",
            },
        ],
        "source": "synthetic",
        "license": "CC0-1.0",
        "review_status": "approved",
        "reviewer": "private-reviewer-name",
        "review_date": "2026-07-28T10:00:00+00:00",
        "quality_score": 4.5,
        "review_notes": "Private review notes.",
        "supersedes_sha256": supersedes_sha256,
    }


def write_jsonl(path: Path, records: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(value) + "\n" for value in records), encoding="utf-8"
    )


def release_fixture(
    tmp_path: Path,
    *,
    source_record: dict | None = None,
) -> tuple[Path, dict]:
    releases = tmp_path / "releases"
    registry = tmp_path / "registry"
    source = tmp_path / "source.jsonl"
    raw = source_record or record()
    write_jsonl(source, [raw])
    import_version(source, registry, "v0.6")
    publish_version(registry, "v0.6", releases)
    published = json.loads(
        (releases / "v0.6/v0.6.jsonl").read_text(encoding="utf-8").strip()
    )
    return releases, published


def test_valid_record_certificate_is_sanitized(tmp_path: Path) -> None:
    releases, published = release_fixture(tmp_path)

    certificate = verify_release(
        releases,
        version="v0.6",
        record_id="v06-test-001",
        record_sha256=published["example_sha256"],
    )

    assert certificate["record_exists"] is True
    assert certificate["release_version"] == "v0.6"
    assert certificate["category"] == "banking"
    assert certificate["source_classification"] == "synthetic"
    assert certificate["license"] == "CC0-1.0"
    assert certificate["review_status"] == "approved"
    assert certificate["revision"] == 1
    assert certificate["approval_timestamp"] == "2026-07-28T10:00:00+00:00"
    assert certificate["integrity_status"] == "verified"
    serialized = certificate_json(certificate)
    assert "private-reviewer-name" not in serialized
    assert "Private review notes" not in serialized
    assert "How can I confirm this transfer?" not in serialized
    assert "reviewer" not in certificate
    assert "messages" not in certificate


def test_manifest_sha256_verifies_release(tmp_path: Path) -> None:
    releases, _ = release_fixture(tmp_path)
    manifest_path = releases / "v0.6/dataset_manifest.json"
    import hashlib

    digest = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    certificate = verify_release(releases, manifest_sha256=digest)

    assert certificate["record_exists"] is False
    assert certificate["release_exists"] is True
    assert certificate["release_version"] == "v0.6"
    assert certificate["manifest_sha256"] == digest
    assert certificate["integrity_status"] == "verified"


def test_invalid_sha256_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ReleaseVerificationError, match="64-character"):
        verify_release(tmp_path, record_sha256="not-a-sha")


def test_altered_record_fails_integrity(tmp_path: Path) -> None:
    releases, published = release_fixture(tmp_path)
    path = releases / "v0.6/v0.6.jsonl"
    published["category"] = "altered-category"
    path.write_text(json.dumps(published) + "\n", encoding="utf-8")

    certificate = verify_release(
        releases, version="v0.6", record_id="v06-test-001"
    )

    assert certificate["record_exists"] is True
    assert certificate["integrity_status"] == "altered"
    assert certificate["integrity_checks"]["published_files_match_manifest"] is False
    assert certificate["integrity_checks"]["record_hash_matches_content"] is False


def test_superseded_hash_resolves_to_current_revision(tmp_path: Path) -> None:
    old_hash = "a" * 64
    releases, published = release_fixture(
        tmp_path, source_record=record(supersedes_sha256=old_hash)
    )

    certificate = verify_release(
        releases, version="v0.6", record_sha256=old_hash
    )

    assert certificate["record_exists"] is False
    assert certificate["record_id"] == "v06-test-001"
    assert certificate["integrity_status"] == "superseded"
    assert certificate["superseded_by"] == published["example_sha256"]


def test_unknown_record_returns_unknown_without_private_data(tmp_path: Path) -> None:
    releases, _ = release_fixture(tmp_path)

    certificate = verify_release(
        releases, version="v0.6", record_id="v06-unknown"
    )

    assert certificate["record_exists"] is False
    assert certificate["release_exists"] is True
    assert certificate["integrity_status"] == "unknown"
    assert certificate["review_status"] is None


def test_cli_verifies_by_record_id(tmp_path: Path) -> None:
    releases, _ = release_fixture(tmp_path)

    result = subprocess.run(
        [
            sys.executable,
            "scripts/dataset_platform.py",
            "verify",
            "--record-id",
            "v06-test-001",
            "--releases-dir",
            str(releases),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    certificate = json.loads(result.stdout)
    assert certificate["integrity_status"] == "verified"
