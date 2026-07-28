from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

from src.dataset_management import read_jsonl
from src.legacy_provenance import (
    LEGACY_FILES,
    PROJECT_ROOT,
    REVIEW_FIELDS,
    VERSION_COMMITS,
    audit_all,
    audit_version,
    canonical_original_sha256,
    import_reviewed,
    write_review_sheets,
)
from src import legacy_provenance


def legacy_record(record_id: str = "v04-test-001") -> dict:
    return {
        "id": record_id,
        "category": "customer_service",
        "risk_level": "low",
        "messages": [
            {"role": "system", "content": "Be safe."},
            {"role": "user", "content": "Where is my order?"},
            {"role": "assistant", "content": "Please share the order reference."},
        ],
    }


def write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(record) + "\n" for record in records),
        encoding="utf-8",
    )


def write_sheet(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REVIEW_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def base_review_row(record: dict, version: str) -> dict[str, str]:
    row = {field: "" for field in REVIEW_FIELDS}
    row.update(
        record_id=record["id"],
        version=version,
        category=record["category"],
        classification="provenance_recoverable",
        original_sha256=canonical_original_sha256(record),
    )
    return row


def fixture_root(tmp_path: Path, record: dict) -> Path:
    write_jsonl(tmp_path / LEGACY_FILES["v0.4"], [record])
    write_jsonl(tmp_path / LEGACY_FILES["v0.5"], [record])
    return tmp_path


def file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_audit_never_invents_provenance() -> None:
    report = audit_all()
    rows = [
        row for version_rows in report["versions"].values() for row in version_rows
    ]

    assert len(rows) == 97
    assert report["classification_counts"] == {"provenance_recoverable": 97}
    assert "data/v0.4/dataset_manifest.json" in report[
        "evidence_sources_searched"
    ]["v0.4"]["manifests_documentation_and_scripts"]
    for row in rows:
        assert row["discovered_source"] == ""
        assert row["proposed_source"] == ""
        assert row["discovered_license"] == ""
        assert row["proposed_license"] == ""
        assert row["ownership_basis"] == ""
        assert row["consent_status"] == ""
        assert row["source_evidence"] == ""
        assert row["license_evidence"] == ""


def test_review_preparation_does_not_modify_originals(tmp_path: Path) -> None:
    before = {
        version: file_digest(PROJECT_ROOT / path)
        for version, path in LEGACY_FILES.items()
    }

    outputs = write_review_sheets(tmp_path)

    assert set(outputs) == {"v0.4", "v0.5"}
    after = {
        version: file_digest(PROJECT_ROOT / path)
        for version, path in LEGACY_FILES.items()
    }
    assert after == before


def test_audit_tracks_exact_line_and_git_evidence() -> None:
    row = audit_version("v0.4")[0]
    references = row["evidence_references"]

    assert "data/raw/" in references
    assert ":2#" in references
    assert "data/v0.4/dataset_manifest.json:2" in references
    assert f"git:{VERSION_COMMITS['v0.4']}" in references


def test_missing_git_history_is_not_treated_as_evidence(monkeypatch) -> None:
    def unavailable(*args, **kwargs):
        raise FileNotFoundError("git unavailable")

    monkeypatch.setattr(legacy_provenance.subprocess, "run", unavailable)
    assert legacy_provenance._commit_subject("missing") == ""


def test_import_rejects_missing_human_approval(tmp_path: Path) -> None:
    record = legacy_record()
    root = fixture_root(tmp_path / "root", record)
    row = base_review_row(record, "v0.4")
    row["evidence_references"] = "evidence.txt:1"
    (root / "evidence.txt").write_text("lineage only\n", encoding="utf-8")
    sheet = tmp_path / "review.csv"
    write_sheet(sheet, [row])

    report = import_reviewed(
        [sheet], tmp_path / "registry", tmp_path / "report", root
    )

    assert report["counts"]["accepted"] == 0
    assert report["counts"]["unresolved"] == 1
    assert not (tmp_path / "registry/versions").exists()


def test_import_requires_evidence_to_contain_each_proposed_value(
    tmp_path: Path,
) -> None:
    record = legacy_record()
    root = fixture_root(tmp_path / "root", record)
    (root / "evidence.txt").write_text("unrelated text\n", encoding="utf-8")
    row = base_review_row(record, "v0.4")
    row.update(
        review_status="approved",
        reviewer="human-reviewer",
        proposed_source="Original human draft",
        proposed_license="CC0-1.0",
        ownership_basis="sole creator",
        consent_status="not applicable",
        evidence_references="evidence.txt:1",
        source_evidence="evidence.txt:1",
        license_evidence="evidence.txt:1",
        ownership_evidence="evidence.txt:1",
        consent_evidence="evidence.txt:1",
    )
    sheet = tmp_path / "review.csv"
    write_sheet(sheet, [row])

    report = import_reviewed(
        [sheet], tmp_path / "registry", tmp_path / "report", root
    )

    assert report["counts"]["accepted"] == 0
    assert report["counts"]["unresolved"] == 1


def test_duplicate_protection_and_original_hash_preservation(tmp_path: Path) -> None:
    record = legacy_record()
    root = fixture_root(tmp_path / "root", record)
    evidence = (
        "Original human draft; CC0-1.0; sole creator; consent recorded"
    )
    (root / "evidence.txt").write_text(evidence + "\n", encoding="utf-8")
    rows = []
    for version in ("v0.4", "v0.5"):
        row = base_review_row(record, version)
        row.update(
            review_status="approved",
            reviewer="human-reviewer",
            proposed_source="Original human draft",
            proposed_license="CC0-1.0",
            ownership_basis="sole creator",
            consent_status="consent recorded",
            evidence_references="evidence.txt:1",
            source_evidence="evidence.txt:1",
            license_evidence="evidence.txt:1",
            ownership_evidence="evidence.txt:1",
            consent_evidence="evidence.txt:1",
        )
        rows.append(row)
    sheet = tmp_path / "review.csv"
    write_sheet(sheet, rows)

    report = import_reviewed(
        [sheet], tmp_path / "registry", tmp_path / "report", root
    )

    assert report["counts"]["accepted"] == 1
    assert report["counts"]["duplicate"] == 1
    imported = read_jsonl(
        tmp_path / "registry/versions/v0.4-legacy-recovered/records.jsonl"
    )[0]
    assert imported["legacy_original_sha256"] == canonical_original_sha256(record)
    assert imported["example_sha256"]
