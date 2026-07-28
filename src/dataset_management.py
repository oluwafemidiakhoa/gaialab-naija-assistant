"""Append-only dataset registry, review, duplicate detection, and publishing."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import re
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


REVIEW_STATUSES = {"draft", "approved", "rejected"}
RISK_LEVELS = {"low", "medium", "high"}
METADATA_FIELDS = (
    "dataset_version",
    "revision",
    "review_status",
    "reviewer",
    "review_date",
    "quality_score",
    "example_sha256",
    "created_at",
    "supersedes_sha256",
)
CSV_FIELDS = (
    "id", "dataset_version", "revision", "category", "risk_level", "system",
    "user", "assistant", "source", "license", "review_status", "reviewer",
    "review_date", "quality_score", "review_notes", "example_sha256",
    "created_at", "supersedes_sha256",
)


class DatasetManagementError(ValueError):
    """Raised when an immutable dataset operation is invalid."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def canonical_content(record: dict[str, Any]) -> dict[str, Any]:
    """Return fields whose values define the example hash."""
    return {
        "id": str(record.get("id", "")).strip(),
        "category": str(record.get("category", "")).strip(),
        "risk_level": str(record.get("risk_level", "")).strip(),
        "messages": record.get("messages", []),
        "source": str(record.get("source", "")).strip(),
        "license": str(record.get("license", "")).strip(),
    }


def example_sha256(record: dict[str, Any]) -> str:
    payload = json.dumps(
        canonical_content(record), ensure_ascii=False, sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_create(path: Path, text: str) -> None:
    """Create a file atomically and refuse to replace any existing path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise DatasetManagementError(f"Refusing to overwrite existing file: {path}")
    descriptor, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temp_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        if path.exists():
            raise DatasetManagementError(f"Refusing to overwrite existing file: {path}")
        temporary.replace(path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def append_jsonl(path: Path, value: dict[str, Any]) -> None:
    """Append one fsynced event; existing events are never rewritten."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise DatasetManagementError(f"File not found: {path}")
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise DatasetManagementError(f"{path}:{number}: invalid JSON") from exc
            if not isinstance(value, dict):
                raise DatasetManagementError(f"{path}:{number}: expected object")
            records.append(value)
    return records


def validate_record(record: dict[str, Any]) -> None:
    content = canonical_content(record)
    for field in ("id", "category", "source", "license"):
        if not content[field]:
            raise DatasetManagementError(f"{field} must not be empty")
    if content["risk_level"] not in RISK_LEVELS:
        raise DatasetManagementError("risk_level must be low, medium, or high")
    messages = content["messages"]
    if not isinstance(messages, list) or len(messages) != 3:
        raise DatasetManagementError("messages must contain system, user, assistant")
    expected = ("system", "user", "assistant")
    for message, role in zip(messages, expected):
        if (
            not isinstance(message, dict)
            or message.get("role") != role
            or not isinstance(message.get("content"), str)
            or not message["content"].strip()
        ):
            raise DatasetManagementError(f"invalid {role} message")


def enrich_record(
    record: dict[str, Any],
    version: str,
    *,
    created_at: str | None = None,
) -> dict[str, Any]:
    validate_record(record)
    enriched = {
        **record,
        "dataset_version": version,
        "revision": int(record.get("revision", 1)),
        "review_status": record.get("review_status", record.get("status", "draft")),
        "reviewer": str(record.get("reviewer", "")),
        "review_date": str(record.get("review_date", "")),
        "quality_score": record.get("quality_score"),
        "created_at": record.get("created_at") or created_at or utc_now(),
        "supersedes_sha256": str(record.get("supersedes_sha256", "")),
    }
    if enriched["review_status"] not in REVIEW_STATUSES:
        raise DatasetManagementError("invalid review_status")
    score = enriched["quality_score"]
    if score not in (None, "") and (
        isinstance(score, bool) or not isinstance(score, (int, float)) or not 0 <= score <= 5
    ):
        raise DatasetManagementError("quality_score must be between 0 and 5")
    enriched["example_sha256"] = example_sha256(enriched)
    return enriched


def snapshot_path(registry_dir: Path, version: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9._-]+", version):
        raise DatasetManagementError("version contains unsafe characters")
    return registry_dir / "versions" / version / "records.jsonl"


def import_version(input_path: Path, registry_dir: Path, version: str) -> Path:
    """Import a version exactly once as an immutable enriched snapshot."""
    destination = snapshot_path(registry_dir, version)
    records = read_jsonl(input_path)
    timestamp = utc_now()
    enriched = [enrich_record(record, version, created_at=timestamp) for record in records]
    ids = [record["id"] for record in enriched]
    if len(ids) != len(set(ids)):
        raise DatasetManagementError("record IDs must be unique within a version")
    text = "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in enriched)
    atomic_create(destination, text)
    append_jsonl(
        registry_dir / "registry_events.jsonl",
        {
            "event": "version_imported",
            "version": version,
            "record_count": len(enriched),
            "source_path": str(input_path),
            "source_sha256": file_sha256(input_path),
            "snapshot_sha256": file_sha256(destination),
            "timestamp": timestamp,
        },
    )
    return destination


def list_versions(registry_dir: Path) -> list[str]:
    root = registry_dir / "versions"
    if not root.exists():
        return []
    return sorted(p.name for p in root.iterdir() if (p / "records.jsonl").is_file())


def review_log_path(registry_dir: Path, version: str) -> Path:
    return registry_dir / "reviews" / f"{version}.jsonl"


def review_state(registry_dir: Path, version: str) -> list[dict[str, Any]]:
    records = {r["id"]: r for r in read_jsonl(snapshot_path(registry_dir, version))}
    path = review_log_path(registry_dir, version)
    if path.exists():
        for event in read_jsonl(path):
            records[event["id"]] = event["record"]
    return [records[key] for key in sorted(records)]


def review_record(
    registry_dir: Path,
    version: str,
    record_id: str,
    status: str,
    reviewer: str,
    quality_score: float | None,
    notes: str,
    *,
    edited_messages: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Append a review event; approved content can only be superseded."""
    if status not in REVIEW_STATUSES:
        raise DatasetManagementError("invalid review status")
    if not reviewer.strip():
        raise DatasetManagementError("reviewer is required")
    if quality_score is not None and not 0 <= quality_score <= 5:
        raise DatasetManagementError("quality_score must be between 0 and 5")
    current = {r["id"]: r for r in review_state(registry_dir, version)}.get(record_id)
    if current is None:
        raise DatasetManagementError(f"unknown record: {record_id}")

    changed = edited_messages is not None and edited_messages != current["messages"]
    if current["review_status"] == "approved" and not changed:
        raise DatasetManagementError("approved records are immutable")

    timestamp = utc_now()
    updated = dict(current)
    if changed:
        updated["messages"] = edited_messages
        validate_record(updated)
        updated["supersedes_sha256"] = current["example_sha256"]
        updated["revision"] = int(current["revision"]) + 1
        updated["review_status"] = "draft" if current["review_status"] == "approved" else status
    else:
        updated["review_status"] = status
    updated.update(
        reviewer=reviewer.strip(),
        review_date=timestamp,
        quality_score=quality_score,
        review_notes=notes.strip(),
    )
    updated["example_sha256"] = example_sha256(updated)
    event = {
        "event": "record_reviewed",
        "id": record_id,
        "version": version,
        "timestamp": timestamp,
        "record": updated,
    }
    append_jsonl(review_log_path(registry_dir, version), event)
    return updated


def _tokens(text: str) -> Counter[str]:
    words = re.findall(r"[a-z0-9']+", text.casefold())
    return Counter(words + [f"{a}_{b}" for a, b in zip(words, words[1:])])


def _cosine(left: Counter[str], right: Counter[str]) -> float:
    common = left.keys() & right.keys()
    dot = sum(left[token] * right[token] for token in common)
    denominator = math.sqrt(sum(v * v for v in left.values())) * math.sqrt(
        sum(v * v for v in right.values())
    )
    return dot / denominator if denominator else 0.0


def semantic_duplicates(
    registry_dir: Path, threshold: float = 0.82
) -> list[dict[str, Any]]:
    """Find similar prompts across all versions and preserved record revisions."""
    if not 0 < threshold <= 1:
        raise DatasetManagementError("threshold must be between 0 and 1")
    items: list[tuple[str, dict[str, Any], Counter[str]]] = []
    seen: set[tuple[str, str]] = set()
    for version in list_versions(registry_dir):
        records = read_jsonl(snapshot_path(registry_dir, version))
        reviews = review_log_path(registry_dir, version)
        if reviews.exists():
            records.extend(event["record"] for event in read_jsonl(reviews))
        for record in records:
            identity = (version, record["example_sha256"])
            if identity in seen:
                continue
            seen.add(identity)
            prompt = record["messages"][1]["content"]
            items.append((version, record, _tokens(prompt)))
    matches: list[dict[str, Any]] = []
    for index, (version_a, record_a, vector_a) in enumerate(items):
        for version_b, record_b, vector_b in items[index + 1 :]:
            similarity = _cosine(vector_a, vector_b)
            if similarity >= threshold:
                matches.append(
                    {
                        "version_a": version_a,
                        "id_a": record_a["id"],
                        "sha256_a": record_a["example_sha256"],
                        "version_b": version_b,
                        "id_b": record_b["id"],
                        "sha256_b": record_b["example_sha256"],
                        "similarity": round(similarity, 6),
                    }
                )
    return sorted(matches, key=lambda item: (-item["similarity"], item["id_a"], item["id_b"]))


def dataset_statistics(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    values = list(records)
    scores = [
        float(r["quality_score"]) for r in values if r.get("quality_score") not in (None, "")
    ]
    return {
        "record_count": len(values),
        "category_counts": dict(sorted(Counter(r["category"] for r in values).items())),
        "risk_level_counts": dict(sorted(Counter(r["risk_level"] for r in values).items())),
        "review_status_counts": dict(
            sorted(Counter(r["review_status"] for r in values).items())
        ),
        "reviewed_records": sum(bool(r.get("reviewer")) for r in values),
        "mean_quality_score": round(sum(scores) / len(scores), 4) if scores else None,
        "unique_example_hashes": len({r["example_sha256"] for r in values}),
    }


def _record_to_csv(record: dict[str, Any]) -> dict[str, Any]:
    messages = {message["role"]: message["content"] for message in record["messages"]}
    return {
        **{field: record.get(field, "") for field in CSV_FIELDS},
        "system": messages["system"],
        "user": messages["user"],
        "assistant": messages["assistant"],
    }


def publish_version(registry_dir: Path, version: str, release_dir: Path) -> dict[str, Path]:
    """Publish a write-once release in JSONL, CSV, statistics, and manifest formats."""
    records = review_state(registry_dir, version)
    release_root = release_dir / version
    if release_root.exists():
        raise DatasetManagementError(f"Release already exists: {release_root}")
    jsonl_path = release_root / f"{version}.jsonl"
    csv_path = release_root / f"{version}.csv"
    stats_path = release_root / "dataset_statistics.json"
    duplicates_path = release_root / "semantic_duplicates.json"
    manifest_path = release_root / "dataset_manifest.json"
    jsonl = "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in records)
    atomic_create(jsonl_path, jsonl)

    csv_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(dir=csv_path.parent, suffix=".csv")
    os.close(descriptor)
    temporary = Path(temp_name)
    try:
        with temporary.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
            writer.writeheader()
            writer.writerows(_record_to_csv(record) for record in records)
        if csv_path.exists():
            raise DatasetManagementError(f"Refusing to overwrite: {csv_path}")
        temporary.replace(csv_path)
    finally:
        temporary.unlink(missing_ok=True)

    statistics = dataset_statistics(records)
    atomic_create(stats_path, json.dumps(statistics, indent=2, sort_keys=True) + "\n")
    duplicates = semantic_duplicates(registry_dir)
    atomic_create(
        duplicates_path,
        json.dumps(duplicates, indent=2, sort_keys=True) + "\n",
    )
    manifest = {
        "dataset_version": version,
        "created_at": utc_now(),
        "immutable_release": True,
        "record_count": len(records),
        "metadata_fields": list(METADATA_FIELDS),
        "semantic_duplicate_method": "local unigram_bigram_cosine",
        "semantic_duplicate_threshold": 0.82,
        "semantic_duplicate_count_across_versions": len(duplicates),
        "files": {},
    }
    for name, path in (
        ("jsonl", jsonl_path),
        ("csv", csv_path),
        ("statistics", stats_path),
        ("semantic_duplicates", duplicates_path),
    ):
        manifest["files"][name] = {"path": path.name, "sha256": file_sha256(path)}
    atomic_create(manifest_path, json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return {
        "jsonl": jsonl_path,
        "csv": csv_path,
        "statistics": stats_path,
        "semantic_duplicates": duplicates_path,
        "manifest": manifest_path,
    }
