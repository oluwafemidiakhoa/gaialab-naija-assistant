"""Offline, privacy-scanned Hugging Face dataset export."""

from __future__ import annotations

import json
import re
import shutil
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

from src.dataset_management import example_sha256, file_sha256, read_jsonl
from src.release_scorecard import generate_scorecard
from src.release_verification import verify_release
from src.training_eligibility import assess_eligibility, deterministic_splits

PRIVATE_KEYS = {
    "reviewer", "reviewer_identifier", "review_notes", "ownership_basis",
    "consent_status", "evidence_path", "discovered_source", "proposed_source",
}
SECRET_PATTERN = re.compile(
    r"(?:api[_-]?key|secret|password|private[_ -]?key)\s*[:=]\s*\S+", re.I
)


class ExportError(ValueError):
    pass


def public_record(record: dict[str, Any]) -> dict[str, Any]:
    """Strip private review fields while retaining fine-tuning messages."""
    return {
        key: value for key, value in record.items()
        if key not in PRIVATE_KEYS and not key.startswith("_")
    }


def privacy_scan(value: Any, path: str = "$") -> list[str]:
    findings: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key.casefold() in PRIVATE_KEYS:
                findings.append(f"{path}.{key}: private field")
            findings.extend(privacy_scan(child, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            findings.extend(privacy_scan(child, f"{path}[{index}]"))
    elif isinstance(value, str) and SECRET_PATTERN.search(value):
        findings.append(f"{path}: possible secret")
    return findings


def _jsonl(rows: list[dict[str, Any]]) -> str:
    return "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows)


def _readme(version: str, records: list[dict[str, Any]], include_drafts: bool) -> str:
    categories = ", ".join(sorted({r["category"] for r in records})) or "None eligible"
    warning = (
        "\n> **DRAFT WARNING:** `drafts.jsonl` is unapproved and must not be mixed "
        "into training data.\n" if include_drafts else ""
    )
    return f"""# GaiaLab Naija Dataset {version}
{warning}
## Description

An offline release package of Nigerian-context assistant examples. Categories:
{categories}. Languages include Nigerian English and a distinct Nigerian Pidgin
subset pending independent speaker review.

## Sources and licence

Public source classifications and record-level licences are preserved in every
row. Synthetic does not mean culturally validated. See `dataset_card.json`.

## Intended use

Research and review of a small instruction-tuning dataset. Out of scope: medical,
legal, financial, or government decision-making and unsupervised deployment.

## Safety, review, and provenance

Only approved, integrity-valid, licensed and provenanced records enter train or
validation. Automated quality checks are advisory; human technical and required
domain reviews govern approval. Contributors must not invent provenance.

## Splits and verification

Splits are deterministic by category and risk. Benchmark prompts are held out.
Run `python scripts/dataset_platform.py verify --version {version}` and compare
`checksums.sha256`.

## Statistics

This package contains {len(records)} training-eligible records. Consult
`release_scorecard.json` for release-wide statistics and limitations.

## Citation

“GaiaLab Naija Dataset {version}”, GaiaLab contributors, release manifest hash
recorded in this package.

## Version history

- {version}: offline export of the immutable repository release.
"""


def export_package(
    version: str,
    output_dir: Path,
    *,
    releases_dir: Path = Path("data/releases"),
    include_drafts: bool = False,
) -> dict[str, Any]:
    if output_dir.exists():
        raise ExportError(f"output already exists: {output_dir}")
    release = releases_dir / version
    certificate = verify_release(releases_dir, version=version)
    if certificate["integrity_status"] != "verified":
        raise ExportError("release integrity verification failed")
    records = read_jsonl(release / f"{version}.jsonl")
    for record in records:
        if not record.get("license"):
            raise ExportError(f"{record.get('id')}: license is missing")
        if not record.get("source") or str(record["source"]).casefold() == "unknown":
            raise ExportError(f"{record.get('id')}: provenance is incomplete")
        if record.get("example_sha256") != example_sha256(record):
            raise ExportError(f"{record.get('id')}: record hash mismatch")
    decisions = [assess_eligibility(record, version) for record in records]
    eligible_ids = {decision.record_id for decision in decisions if decision.eligible}
    eligible = [public_record(r) for r in records if r["id"] in eligible_ids]
    drafts = [
        public_record(r) for r in records
        if r["id"] not in eligible_ids and r.get("review_status") == "draft"
    ] if include_drafts else []
    splits = deterministic_splits(eligible)
    public_values = [*eligible, *drafts, certificate]
    findings = privacy_scan(public_values)
    if findings:
        raise ExportError("privacy scan failed: " + "; ".join(findings))

    output_dir.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.", dir=output_dir.parent))
    try:
        files = {
            "README.md": _readme(version, eligible, include_drafts),
            "LICENSE": (
                "Dataset rows retain their record-level licence. No licence is "
                "granted for material whose provenance or licence is absent.\n"
            ),
            "train.jsonl": _jsonl(splits["training"]),
            "validation.jsonl": _jsonl(splits["validation"]),
            "benchmark.jsonl": _jsonl(splits["held_out_benchmark"]),
            "dataset_manifest.json": (release / "dataset_manifest.json").read_text(encoding="utf-8"),
            "verification_certificate.json": json.dumps(certificate, indent=2, sort_keys=True) + "\n",
        }
        if include_drafts:
            files["drafts.jsonl"] = _jsonl(drafts)
        validation_source = Path("data") / version / "generated" / "validation_report.json"
        validation = (
            json.loads(validation_source.read_text(encoding="utf-8"))
            if validation_source.is_file() else {"status": "not_available"}
        )
        files["validation_report.json"] = json.dumps(validation, indent=2, sort_keys=True) + "\n"
        quality_root = Path("evaluation/quality") / version
        quality_path = quality_root / "quality_assessments.jsonl"
        quality_runs = sorted(quality_root.glob("run-*/quality_assessments.jsonl"))
        if quality_runs:
            quality_path = quality_runs[-1]
        scorecard = generate_scorecard(
            version, records, release / "dataset_manifest.json", decisions=decisions,
            assessments=[
                assessment for assessment in (
                    read_jsonl(quality_path)
                    if quality_path.is_file()
                    else []
                )
                if assessment.get("record_id") in {record["id"] for record in records}
            ],
        )
        files["release_scorecard.json"] = json.dumps(scorecard, indent=2, sort_keys=True) + "\n"
        card = {
            "dataset_version": version,
            "record_count": len(eligible),
            "draft_count": len(drafts),
            "categories": dict(sorted(Counter(r["category"] for r in eligible).items())),
            "languages": ["Nigerian English", "Nigerian Pidgin"],
            "intended_use": "Research and supervised dataset review",
            "automatic_upload": False,
        }
        files["dataset_card.json"] = json.dumps(card, indent=2, sort_keys=True) + "\n"
        for name, text in files.items():
            (temporary / name).write_text(text, encoding="utf-8", newline="\n")
        checksums = "".join(
            f"{file_sha256(path)}  {path.name}\n"
            for path in sorted(temporary.iterdir()) if path.name != "checksums.sha256"
        )
        (temporary / "checksums.sha256").write_text(checksums, encoding="utf-8", newline="\n")
        temporary.replace(output_dir)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return {
        "output_dir": str(output_dir), "eligible_count": len(eligible),
        "draft_count": len(drafts), "privacy_findings": [],
    }
