import json
from pathlib import Path

import pytest

from src.dataset_management import example_sha256, import_version, publish_version
from src.huggingface_export import ExportError, export_package, privacy_scan


def release(tmp_path: Path) -> Path:
    row = {
        "id": "v06-test-001", "category": "business_writing", "risk_level": "low",
        "messages": [
            {"role": "system", "content": "Help."},
            {"role": "user", "content": "Write an invoice reminder."},
            {"role": "assistant", "content": "Good day. Kindly settle invoice 10. Thank you."},
        ],
        "source": "synthetic", "license": "CC0-1.0", "review_status": "approved",
        "technical_review_completed": True,
    }
    source = tmp_path / "source.jsonl"
    source.write_text(json.dumps(row) + "\n")
    registry = tmp_path / "registry"
    import_version(source, registry, "v0.6")
    releases = tmp_path / "releases"
    publish_version(registry, "v0.6", releases)
    return releases


def test_export_contents_and_no_overwrite(tmp_path):
    releases = release(tmp_path)
    output = tmp_path / "hf"
    result = export_package("v0.6", output, releases_dir=releases)
    expected = {
        "README.md", "LICENSE", "dataset_card.json", "train.jsonl",
        "validation.jsonl", "benchmark.jsonl", "dataset_manifest.json",
        "release_scorecard.json", "validation_report.json",
        "verification_certificate.json", "checksums.sha256",
    }
    assert expected == {p.name for p in output.iterdir()}
    assert result["privacy_findings"] == []
    with pytest.raises(ExportError, match="already exists"):
        export_package("v0.6", output, releases_dir=releases)


def test_drafts_are_separate_and_warned(tmp_path):
    releases = release(tmp_path)
    # Imported record is approved, so this exercises the explicit file contract.
    output = tmp_path / "hf"
    export_package("v0.6", output, releases_dir=releases, include_drafts=True)
    assert (output / "drafts.jsonl").is_file()
    assert "DRAFT WARNING" in (output / "README.md").read_text(encoding="utf-8")


def test_failed_integrity_rejected(tmp_path):
    releases = release(tmp_path)
    (releases / "v0.6" / "v0.6.jsonl").write_text("altered\n")
    with pytest.raises(ExportError, match="integrity"):
        export_package("v0.6", tmp_path / "hf", releases_dir=releases)


@pytest.mark.parametrize(("field", "message"), [
    ("license", "license is missing"),
    ("source", "provenance is incomplete"),
])
def test_missing_metadata_rejected(tmp_path, monkeypatch, field, message):
    releases = release(tmp_path)
    path = releases / "v0.6" / "v0.6.jsonl"
    row = json.loads(path.read_text())
    row[field] = ""
    row["example_sha256"] = example_sha256(row)
    path.write_text(json.dumps(row) + "\n")
    monkeypatch.setattr(
        "src.huggingface_export.verify_release",
        lambda *args, **kwargs: {"integrity_status": "verified"},
    )
    with pytest.raises(ExportError, match=message):
        export_package("v0.6", tmp_path / "hf", releases_dir=releases)


def test_private_field_scan():
    assert privacy_scan({"reviewer_identifier": "person"})
    assert privacy_scan({"text": "api_key=secret-value"})
