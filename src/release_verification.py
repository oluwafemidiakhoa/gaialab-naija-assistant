"""Read-only, privacy-preserving verification for published dataset releases."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.dataset_management import example_sha256, file_sha256


SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")
CERTIFICATE_SCHEMA = "gaialab.release-verification.v1"


class ReleaseVerificationError(ValueError):
    """Raised when a verification request is malformed."""


def _validate_sha256(value: str | None, field: str) -> str | None:
    if value is None or not value.strip():
        return None
    normalized = value.strip().lower()
    if not SHA256_PATTERN.fullmatch(normalized):
        raise ReleaseVerificationError(f"{field} must be a 64-character SHA-256")
    return normalized


def _safe_version(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    normalized = value.strip()
    if not re.fullmatch(r"[A-Za-z0-9._-]+", normalized):
        raise ReleaseVerificationError("version contains unsafe characters")
    return normalized


def source_classification(record: dict[str, Any]) -> str:
    """Return a public classification without exposing raw source metadata."""
    if record.get("legacy_original_sha256"):
        return "recovered_legacy"
    source = str(record.get("source", "")).strip().casefold()
    if source == "synthetic":
        return "synthetic"
    if source:
        return "documented"
    return "unknown"


def _release_directories(releases_dir: Path, version: str | None) -> list[Path]:
    if version is not None:
        candidate = releases_dir / version
        return [candidate] if candidate.is_dir() else []
    if not releases_dir.is_dir():
        return []
    return sorted(
        path
        for path in releases_dir.iterdir()
        if path.is_dir() and (path / "dataset_manifest.json").is_file()
    )


def _load_release(release_dir: Path) -> dict[str, Any]:
    manifest_path = release_dir / "dataset_manifest.json"
    result: dict[str, Any] = {
        "version": release_dir.name,
        "manifest_path": manifest_path,
        "manifest_sha256": None,
        "manifest": None,
        "records": [],
        "checks": {
            "manifest_readable": False,
            "manifest_version_matches": False,
            "published_files_match_manifest": False,
            "record_count_matches": False,
        },
    }
    if not manifest_path.is_file():
        return result
    result["manifest_sha256"] = file_sha256(manifest_path)
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return result
    if not isinstance(manifest, dict):
        return result
    result["manifest"] = manifest
    result["checks"]["manifest_readable"] = True
    result["checks"]["manifest_version_matches"] = (
        manifest.get("dataset_version") == release_dir.name
    )

    files = manifest.get("files")
    all_files_match = isinstance(files, dict) and bool(files)
    if isinstance(files, dict):
        for metadata in files.values():
            if not isinstance(metadata, dict):
                all_files_match = False
                continue
            relative = str(metadata.get("path", ""))
            expected = str(metadata.get("sha256", "")).lower()
            if (
                not relative
                or Path(relative).name != relative
                or not SHA256_PATTERN.fullmatch(expected)
            ):
                all_files_match = False
                continue
            path = release_dir / relative
            if not path.is_file() or file_sha256(path) != expected:
                all_files_match = False
    result["checks"]["published_files_match_manifest"] = all_files_match

    jsonl_metadata = files.get("jsonl") if isinstance(files, dict) else None
    if isinstance(jsonl_metadata, dict):
        jsonl_name = str(jsonl_metadata.get("path", ""))
        jsonl_path = release_dir / jsonl_name
        if jsonl_path.is_file() and Path(jsonl_name).name == jsonl_name:
            try:
                records = []
                for line in jsonl_path.read_text(encoding="utf-8").splitlines():
                    if line.strip():
                        value = json.loads(line)
                        if not isinstance(value, dict):
                            raise ValueError
                        records.append(value)
                result["records"] = records
            except (json.JSONDecodeError, OSError, ValueError):
                result["records"] = []
    result["checks"]["record_count_matches"] = (
        len(result["records"]) == manifest.get("record_count")
    )
    return result


def _release_integrity(release: dict[str, Any]) -> bool:
    return all(release["checks"].values())


def _public_record_fields(record: dict[str, Any]) -> dict[str, Any]:
    approved = record.get("review_status") == "approved"
    return {
        "record_id": record.get("id"),
        "record_sha256": record.get("example_sha256"),
        "category": record.get("category"),
        "source_classification": source_classification(record),
        "license": record.get("license"),
        "review_status": record.get("review_status"),
        "revision": record.get("revision"),
        "creation_timestamp": record.get("created_at"),
        "approval_timestamp": record.get("review_date") if approved else None,
    }


def verify_release(
    releases_dir: Path,
    *,
    version: str | None = None,
    record_id: str | None = None,
    record_sha256: str | None = None,
    manifest_sha256: str | None = None,
) -> dict[str, Any]:
    """Return a sanitized verification certificate."""
    version = _safe_version(version)
    record_id = record_id.strip() if record_id and record_id.strip() else None
    record_sha256 = _validate_sha256(record_sha256, "record_sha256")
    manifest_sha256 = _validate_sha256(manifest_sha256, "manifest_sha256")
    if not any((version, record_id, record_sha256, manifest_sha256)):
        raise ReleaseVerificationError(
            "provide a version, record ID, record SHA-256, or manifest SHA-256"
        )

    releases = [_load_release(path) for path in _release_directories(releases_dir, version)]
    if manifest_sha256:
        releases = [
            release
            for release in releases
            if release["manifest_sha256"] == manifest_sha256
        ]

    base: dict[str, Any] = {
        "certificate_schema": CERTIFICATE_SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "query": {
            "version": version,
            "record_id": record_id,
            "record_sha256": record_sha256,
            "manifest_sha256": manifest_sha256,
        },
        "record_exists": False,
        "release_exists": bool(releases),
        "release_version": None,
        "manifest_sha256": None,
        "record_id": record_id,
        "record_sha256": record_sha256,
        "category": None,
        "source_classification": None,
        "license": None,
        "review_status": None,
        "revision": None,
        "creation_timestamp": None,
        "approval_timestamp": None,
        "integrity_status": "unknown",
        "integrity_checks": {},
        "superseded_by": None,
    }
    if not releases:
        return base

    # A current record must satisfy every supplied record selector.
    if record_id is not None or record_sha256 is not None:
        for release in releases:
            for record in release["records"]:
                id_matches = record_id is None or record.get("id") == record_id
                hash_matches = (
                    record_sha256 is None
                    or str(record.get("example_sha256", "")).lower() == record_sha256
                )
                if not (id_matches and hash_matches):
                    continue
                stored_hash = str(record.get("example_sha256", "")).lower()
                recomputed_hash = example_sha256(record)
                record_hash_matches = (
                    SHA256_PATTERN.fullmatch(stored_hash) is not None
                    and stored_hash == recomputed_hash
                )
                checks = {
                    **release["checks"],
                    "record_hash_matches_content": record_hash_matches,
                }
                return {
                    **base,
                    "record_exists": True,
                    "release_exists": True,
                    "release_version": release["version"],
                    "manifest_sha256": release["manifest_sha256"],
                    **_public_record_fields(record),
                    "integrity_status": (
                        "verified"
                        if _release_integrity(release) and record_hash_matches
                        else "altered"
                    ),
                    "integrity_checks": checks,
                }

    # A historical hash referenced by a current revision is preserved but no
    # longer current in this release.
    if record_sha256:
        for release in releases:
            for record in release["records"]:
                if str(record.get("supersedes_sha256", "")).lower() == record_sha256:
                    return {
                        **base,
                        "release_exists": True,
                        "release_version": release["version"],
                        "manifest_sha256": release["manifest_sha256"],
                        "record_id": record.get("id"),
                        "integrity_status": (
                            "superseded"
                            if _release_integrity(release)
                            else "altered"
                        ),
                        "integrity_checks": release["checks"],
                        "superseded_by": record.get("example_sha256"),
                    }

    # Version-only or manifest-only queries verify the release envelope.
    if record_id is None and record_sha256 is None:
        release = releases[0]
        return {
            **base,
            "release_exists": True,
            "release_version": release["version"],
            "manifest_sha256": release["manifest_sha256"],
            "integrity_status": (
                "verified" if _release_integrity(release) else "altered"
            ),
            "integrity_checks": release["checks"],
        }

    release = releases[0]
    return {
        **base,
        "release_exists": True,
        "release_version": release["version"],
        "manifest_sha256": release["manifest_sha256"],
        "integrity_checks": release["checks"],
    }


def certificate_json(certificate: dict[str, Any]) -> str:
    return json.dumps(certificate, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
