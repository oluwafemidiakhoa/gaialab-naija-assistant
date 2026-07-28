"""Evidence-only legacy provenance auditing and approval-gated migration."""

from __future__ import annotations

import csv
import hashlib
import json
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from src.dataset_management import (
    DatasetManagementError,
    atomic_create,
    enrich_record,
    example_sha256,
    list_versions,
    read_jsonl,
    snapshot_path,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent
LEGACY_FILES = {
    "v0.4": Path("data/v0.4/v0.4_all_reviewed.jsonl"),
    "v0.5": Path("data/v0.5/v0.5_training.jsonl"),
}
LINEAGE_FILES = {
    "v0.4": (
        Path("data/raw/customer_service.jsonl"),
        Path("data/raw/nigerian_english.jsonl"),
        Path("data/raw/professional_boundaries.jsonl"),
        Path("data/raw/safety_scams.jsonl"),
    ),
    "v0.5": (
        Path("data/v0.4/v0.4_training.jsonl"),
        Path("data/v0.5/v0.5_new_examples.jsonl"),
        Path("data/v0.5/v0.5_examples.csv"),
    ),
}
VERSION_COMMITS = {
    "v0.4": "c564287aeabbcedaef1efdf88a8b92b46d683560",
    "v0.5": "51c4aa9b5d346e4eba1c5adb5b397c241bd165a9",
}
DOCUMENTARY_EVIDENCE = {
    "v0.4": (
        (Path("data/v0.4/dataset_manifest.json"), ("dataset_version",)),
        (Path("scripts/V04_DATASET_README.md"), ("reproducible", "data/raw")),
        (Path("scripts/build_v04_dataset.py"), ("input-dir", "read_examples")),
    ),
    "v0.5": (
        (Path("data/v0.5/dataset_manifest.json"), ("base_file", "new_examples_file")),
        (Path("scripts/build_v05_dataset.py"), ("DEFAULT_BASE_FILE", "DEFAULT_NEW_FILE")),
        (Path("scripts/pipeline.py"), ("v0.5 dataset workflow",)),
    ),
}
CLASSIFICATIONS = {
    "provenance_complete",
    "provenance_recoverable",
    "provenance_unknown",
    "rejected",
}
REVIEW_FIELDS = (
    "record_id",
    "version",
    "category",
    "prompt_preview",
    "response_preview",
    "discovered_source",
    "proposed_source",
    "discovered_license",
    "proposed_license",
    "ownership_basis",
    "consent_status",
    "reviewer",
    "review_status",
    "review_notes",
    "classification",
    "original_sha256",
    "evidence_references",
    "source_evidence",
    "license_evidence",
    "ownership_evidence",
    "consent_evidence",
)


class LegacyProvenanceError(DatasetManagementError):
    """Raised when legacy evidence or migration input is invalid."""


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")


def canonical_original_sha256(record: dict[str, Any]) -> str:
    """Hash the exact logical legacy object without adding metadata."""
    payload = json.dumps(
        record, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def content_fingerprint(record: dict[str, Any]) -> str:
    messages = record.get("messages", [])
    payload = json.dumps(messages, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def preview(text: str, limit: int = 120) -> str:
    normalized = " ".join(text.split())
    return normalized if len(normalized) <= limit else normalized[: limit - 1] + "…"


def _jsonl_index(path: Path, evidence_path: str | None = None) -> dict[str, list[str]]:
    index: dict[str, list[str]] = {}
    if not path.is_file():
        return index
    with path.open(encoding="utf-8-sig") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict):
                index.setdefault(content_fingerprint(record), []).append(
                    f"{evidence_path or path.as_posix()}:{line_number}#{record.get('id', '')}"
                )
    return index


def _csv_index(path: Path, evidence_path: str | None = None) -> dict[str, list[str]]:
    index: dict[str, list[str]] = {}
    if not path.is_file():
        return index
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for line_number, row in enumerate(csv.DictReader(handle), start=2):
            record = {
                "messages": [
                    {"role": "system", "content": (row.get("system") or "").strip()},
                    {"role": "user", "content": (row.get("user") or "").strip()},
                    {"role": "assistant", "content": (row.get("assistant") or "").strip()},
                ]
            }
            index.setdefault(content_fingerprint(record), []).append(
                f"{evidence_path or path.as_posix()}:{line_number}#{row.get('id', '')}"
            )
    return index


def _commit_subject(commit: str) -> str:
    """Return a commit subject when available; never invent missing evidence."""
    try:
        result = subprocess.run(
            ["git", "show", "-s", "--format=%s", commit],
            cwd=PROJECT_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def _documentary_references(
    version: str, root: Path
) -> list[str]:
    references: list[str] = []
    for relative, patterns in DOCUMENTARY_EVIDENCE[version]:
        path = root / relative
        if not path.is_file():
            continue
        lines = path.read_text(encoding="utf-8-sig").splitlines()
        for pattern in patterns:
            for line_number, line in enumerate(lines, start=1):
                if pattern.casefold() in line.casefold():
                    references.append(f"{relative.as_posix()}:{line_number}")
                    break
    return references


def audit_version(version: str, root: Path = PROJECT_ROOT) -> list[dict[str, Any]]:
    if version not in LEGACY_FILES:
        raise LegacyProvenanceError(f"unsupported legacy version: {version}")
    legacy_path = root / LEGACY_FILES[version]
    records = read_jsonl(legacy_path)
    lineage_indexes: list[dict[str, list[str]]] = []
    for relative in LINEAGE_FILES[version]:
        path = root / relative
        lineage_indexes.append(
            _csv_index(path, relative.as_posix())
            if path.suffix == ".csv"
            else _jsonl_index(path, relative.as_posix())
        )
    commit = VERSION_COMMITS[version]
    subject = _commit_subject(commit) if root.resolve() == PROJECT_ROOT else ""
    documentary_references = _documentary_references(version, root)
    audit: list[dict[str, Any]] = []

    for line_number, record in enumerate(records, start=1):
        messages = record.get("messages", [])
        malformed = (
            not isinstance(messages, list)
            or len(messages) != 3
            or any(not isinstance(message, dict) for message in messages)
        )
        fingerprint = content_fingerprint(record)
        evidence = [
            reference
            for index in lineage_indexes
            for reference in index.get(fingerprint, [])
        ]
        for reference in list(evidence):
            location, _, record_identifier = reference.partition("#")
            path_text, _, _ = location.rpartition(":")
            historical = subprocess.run(
                ["git", "cat-file", "-e", f"{commit}:{path_text}"],
                cwd=root,
                check=False,
                capture_output=True,
            )
            if historical.returncode == 0:
                evidence.append(
                    f"git:{commit}:{path_text}#{record_identifier}"
                )
        evidence.append(
            f"{LEGACY_FILES[version].as_posix()}:{line_number}#{record.get('id', '')}"
        )
        evidence.extend(documentary_references)
        if subject:
            evidence.append(f"git:{commit}:commit-message:{subject}")

        discovered_source = str(record.get("source", "")).strip()
        discovered_license = str(record.get("license", "")).strip()
        if malformed:
            classification = "rejected"
        elif (
            discovered_source
            and discovered_license
            and str(record.get("ownership_basis", "")).strip()
            and str(record.get("consent_status", "")).strip()
        ):
            classification = "provenance_complete"
        elif len(evidence) > 2:
            classification = "provenance_recoverable"
        else:
            classification = "provenance_unknown"

        audit.append(
            {
                "record_id": str(record.get("id", "")).strip(),
                "version": version,
                "category": str(record.get("category", "")).strip(),
                "prompt_preview": preview(
                    str(messages[1].get("content", "")) if not malformed else ""
                ),
                "response_preview": preview(
                    str(messages[2].get("content", "")) if not malformed else ""
                ),
                "discovered_source": discovered_source,
                "proposed_source": "",
                "discovered_license": discovered_license,
                "proposed_license": "",
                "ownership_basis": "",
                "consent_status": "",
                "reviewer": "",
                "review_status": "",
                "review_notes": "",
                "classification": classification,
                "original_sha256": canonical_original_sha256(record),
                "evidence_references": " | ".join(evidence),
                "source_evidence": "",
                "license_evidence": "",
                "ownership_evidence": "",
                "consent_evidence": "",
            }
        )
    return audit


def audit_all(root: Path = PROJECT_ROOT) -> dict[str, Any]:
    versions = {version: audit_version(version, root) for version in LEGACY_FILES}
    rows = [row for values in versions.values() for row in values]
    return {
        "audit_status": "requires_human_review",
        "policy": "No source, license, ownership, or consent value is inferred.",
        "versions": versions,
        "classification_counts": dict(
            sorted(Counter(row["classification"] for row in rows).items())
        ),
        "record_count": len(rows),
        "evidence_sources_searched": {
            version: {
                "legacy_file": LEGACY_FILES[version].as_posix(),
                "adjacent_files": [
                    path.as_posix() for path in LINEAGE_FILES[version]
                ],
                "manifests_documentation_and_scripts": [
                    path.as_posix()
                    for path, _ in DOCUMENTARY_EVIDENCE[version]
                ],
                "git_commit": VERSION_COMMITS[version],
            }
            for version in LEGACY_FILES
        },
    }


def write_review_sheets(
    output_dir: Path, root: Path = PROJECT_ROOT
) -> dict[str, Path]:
    outputs: dict[str, Path] = {}
    for version in LEGACY_FILES:
        path = output_dir / f"{version}_provenance_review.csv"
        if path.exists():
            raise LegacyProvenanceError(
                f"Refusing to overwrite review sheet: {path}"
            )
        rows = audit_version(version, root)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=REVIEW_FIELDS)
            writer.writeheader()
            writer.writerows(rows)
        outputs[version] = path
    return outputs


def _load_review_sheet(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = set(REVIEW_FIELDS) - set(reader.fieldnames or [])
        if missing:
            raise LegacyProvenanceError(
                f"{path} missing review columns: {', '.join(sorted(missing))}"
            )
        return [{key: (value or "").strip() for key, value in row.items()} for row in reader]


def _evidence_text(reference: str, root: Path) -> str | None:
    value = reference.strip()
    if not value:
        return None
    if value.startswith("git:"):
        payload = value[len("git:") :]
        commit, separator, locator = payload.partition(":")
        if not separator:
            return None
        if locator.startswith("commit-message:"):
            result = subprocess.run(
                ["git", "show", "-s", "--format=%B", commit],
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
            )
            return result.stdout if result.returncode == 0 else None
        path_text, _, record_identifier = locator.partition("#")
        result = subprocess.run(
            ["git", "show", f"{commit}:{path_text}"],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return None
        if not record_identifier:
            return result.stdout
        return next(
            (line for line in result.stdout.splitlines() if record_identifier in line),
            None,
        )
    location = value.split("#", 1)[0]
    path_text, separator, line_text = location.rpartition(":")
    if not separator or not line_text.isdigit():
        return None
    path = root / path_text
    if not path.is_file():
        return None
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    return lines[int(line_text) - 1] if 1 <= int(line_text) <= len(lines) else None


def _evidence_supported(references: str, root: Path) -> bool:
    values = [value.strip() for value in references.split("|") if value.strip()]
    return bool(values) and all(_evidence_text(value, root) is not None for value in values)


def _evidence_supports_value(reference: str, value: str, root: Path) -> bool:
    text = _evidence_text(reference, root)
    return bool(text) and value.casefold() in text.casefold()


def _existing_legacy_hashes(registry_dir: Path) -> set[str]:
    hashes: set[str] = set()
    for version in list_versions(registry_dir):
        for record in read_jsonl(snapshot_path(registry_dir, version)):
            value = str(record.get("legacy_original_sha256", "")).strip()
            if value:
                hashes.add(value)
    return hashes


def import_reviewed(
    review_sheets: Iterable[Path],
    registry_dir: Path,
    report_dir: Path,
    root: Path = PROJECT_ROOT,
) -> dict[str, Any]:
    """Import only supported, explicitly human-approved rows."""
    source_records = {
        version: {
            record["id"]: record
            for record in read_jsonl(root / path)
        }
        for version, path in LEGACY_FILES.items()
    }
    existing_hashes = _existing_legacy_hashes(registry_dir)
    seen_hashes = set(existing_hashes)
    accepted_by_version: dict[str, list[dict[str, Any]]] = {}
    counts = Counter(accepted=0, rejected=0, unresolved=0, duplicate=0)
    issues: list[dict[str, str]] = []

    for sheet in review_sheets:
        for row in _load_review_sheet(sheet):
            version = row["version"]
            record = source_records.get(version, {}).get(row["record_id"])
            if record is None:
                counts["unresolved"] += 1
                issues.append({"record_id": row["record_id"], "issue": "original_not_found"})
                continue
            actual_hash = canonical_original_sha256(record)
            if actual_hash != row["original_sha256"]:
                counts["rejected"] += 1
                issues.append({"record_id": row["record_id"], "issue": "original_hash_mismatch"})
                continue
            if row["review_status"] == "rejected":
                counts["rejected"] += 1
                continue
            required = (
                row["review_status"] == "approved"
                and bool(row["reviewer"])
                and bool(row["proposed_source"])
                and bool(row["proposed_license"])
                and bool(row["ownership_basis"])
                and bool(row["consent_status"])
                and _evidence_supported(row["evidence_references"], root)
                and _evidence_supports_value(
                    row["source_evidence"], row["proposed_source"], root
                )
                and _evidence_supports_value(
                    row["license_evidence"], row["proposed_license"], root
                )
                and _evidence_supports_value(
                    row["ownership_evidence"], row["ownership_basis"], root
                )
                and _evidence_supports_value(
                    row["consent_evidence"], row["consent_status"], root
                )
            )
            if not required:
                counts["unresolved"] += 1
                issues.append(
                    {"record_id": row["record_id"], "issue": "approval_or_evidence_incomplete"}
                )
                continue
            if actual_hash in seen_hashes:
                counts["duplicate"] += 1
                continue
            seen_hashes.add(actual_hash)
            recovered = {
                **record,
                "source": row["proposed_source"],
                "license": row["proposed_license"],
                "review_status": "approved",
                "reviewer": row["reviewer"],
                "review_date": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "quality_score": None,
                "review_notes": row["review_notes"],
                "ownership_basis": row["ownership_basis"],
                "consent_status": row["consent_status"],
                "provenance_evidence": row["evidence_references"].split(" | "),
                "source_evidence": row["source_evidence"],
                "license_evidence": row["license_evidence"],
                "ownership_evidence": row["ownership_evidence"],
                "consent_evidence": row["consent_evidence"],
                "legacy_original_sha256": actual_hash,
            }
            target_version = f"{version}-legacy-recovered"
            accepted_by_version.setdefault(target_version, []).append(
                enrich_record(recovered, target_version)
            )
            counts["accepted"] += 1

    imported_versions: list[str] = []
    for version in accepted_by_version:
        destination = snapshot_path(registry_dir, version)
        if destination.exists():
            raise LegacyProvenanceError(
                f"Refusing to overwrite recovered version: {destination}"
            )
    for version, records in sorted(accepted_by_version.items()):
        destination = snapshot_path(registry_dir, version)
        text = "".join(
            json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
            for record in records
        )
        atomic_create(destination, text)
        imported_versions.append(version)

    report = {
        "status": "completed",
        "counts": dict(counts),
        "imported_versions": imported_versions,
        "issues": issues,
        "original_files_modified": False,
    }
    atomic_create(
        report_dir / "migration_report.json",
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    return report
