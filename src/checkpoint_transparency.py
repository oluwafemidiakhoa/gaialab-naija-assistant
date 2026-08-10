"""Portable transparency records for signed operator checkpoints.

The transparency ledger is intentionally separate from Trust Rail persistence.
It contains only already-public checkpoint evidence: checkpoint count/head/time,
checkpoint signature material, and hashes needed to detect ledger rewriting.

Operational independence comes from storing the resulting JSONL ledger and its
latest head outside the Trust Rail database and administrative boundary.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from src.operator_checkpoint import verify_checkpoint


TRANSPARENCY_RECORD_VERSION = "gaialab-naija-checkpoint-transparency/0.1.0"
TRANSPARENCY_ENTRY_VERSION = "gaialab-naija-checkpoint-transparency-entry/0.1.0"
GENESIS_TRANSPARENCY_HASH = "0" * 64

_CHECKPOINT_FIELDS = frozenset(
    {
        "checkpoint_id",
        "version",
        "stream_id",
        "action_count",
        "action_head_sha256",
        "created_at",
    }
)
_SIGNATURE_FIELDS = frozenset(
    {"version", "algorithm", "key_id", "public_key_b64", "signature_b64"}
)
_RECORD_FIELDS = frozenset(
    {
        "publication_id",
        "version",
        "checkpoint_package_sha256",
        "checkpoint",
        "signature",
    }
)
_ENTRY_FIELDS = frozenset(
    {
        "version",
        "sequence",
        "previous_entry_sha256",
        "appended_at",
        "record",
        "entry_sha256",
    }
)


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _sha256(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _is_sha256(value: Any) -> bool:
    text = str(value or "")
    return len(text) == 64 and all(character in "0123456789abcdef" for character in text)


def _project_package(package: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    checkpoint = package.get("checkpoint")
    signature = package.get("signature")
    if not isinstance(checkpoint, Mapping) or not isinstance(signature, Mapping):
        raise ValueError("checkpoint package must contain checkpoint and signature objects")
    if set(checkpoint) != _CHECKPOINT_FIELDS:
        raise ValueError("checkpoint package contains unsupported checkpoint fields")
    if set(signature) != _SIGNATURE_FIELDS:
        raise ValueError("checkpoint package contains unsupported signature fields")
    return {
        "checkpoint": {key: checkpoint[key] for key in sorted(_CHECKPOINT_FIELDS)},
        "signature": {key: signature[key] for key in sorted(_SIGNATURE_FIELDS)},
    }


def _trusted_key_result(key_id: str, trusted_key_ids: Collection[str] | None) -> dict[str, Any] | None:
    if trusted_key_ids is None:
        return None
    trusted = {str(value).strip() for value in trusted_key_ids if str(value).strip()}
    if key_id not in trusted:
        return {
            "valid": False,
            "reason": "untrusted_checkpoint_signing_key",
            "key_id": key_id,
        }
    return None


def create_transparency_record(
    checkpoint_package: Mapping[str, Any],
    *,
    trusted_key_ids: Collection[str] | None = None,
) -> dict[str, Any]:
    """Create a deterministic public record from one valid signed checkpoint."""
    projected = _project_package(checkpoint_package)
    signed = verify_checkpoint(projected)
    if not signed.get("valid"):
        raise ValueError(f"checkpoint is not valid: {signed.get('reason')}")
    key_id = str(signed.get("key_id") or "")
    trust_failure = _trusted_key_result(key_id, trusted_key_ids)
    if trust_failure is not None:
        raise ValueError(f"checkpoint signer is not trusted: {key_id}")

    package_sha256 = _sha256(projected)
    core = {
        "version": TRANSPARENCY_RECORD_VERSION,
        "checkpoint_package_sha256": package_sha256,
        **projected,
    }
    return {
        "publication_id": "optrans_" + _sha256(core)[:32],
        **core,
    }


def verify_transparency_record(
    record: Mapping[str, Any],
    *,
    trusted_key_ids: Collection[str] | None = None,
) -> dict[str, Any]:
    """Verify a public transparency record without database access."""
    if not isinstance(record, Mapping) or set(record) != _RECORD_FIELDS:
        return {"valid": False, "reason": "invalid_transparency_record_shape"}
    if record.get("version") != TRANSPARENCY_RECORD_VERSION:
        return {"valid": False, "reason": "unsupported_transparency_record_version"}
    checkpoint = record.get("checkpoint")
    signature = record.get("signature")
    if not isinstance(checkpoint, Mapping) or not isinstance(signature, Mapping):
        return {"valid": False, "reason": "invalid_transparency_record_shape"}
    if set(checkpoint) != _CHECKPOINT_FIELDS or set(signature) != _SIGNATURE_FIELDS:
        return {"valid": False, "reason": "invalid_transparency_record_shape"}

    package = {
        "checkpoint": {key: checkpoint[key] for key in sorted(_CHECKPOINT_FIELDS)},
        "signature": {key: signature[key] for key in sorted(_SIGNATURE_FIELDS)},
    }
    package_sha256 = _sha256(package)
    if record.get("checkpoint_package_sha256") != package_sha256:
        return {"valid": False, "reason": "checkpoint_package_hash_mismatch"}

    core = {
        "version": TRANSPARENCY_RECORD_VERSION,
        "checkpoint_package_sha256": package_sha256,
        **package,
    }
    expected_id = "optrans_" + _sha256(core)[:32]
    if record.get("publication_id") != expected_id:
        return {"valid": False, "reason": "publication_id_mismatch"}

    signed = verify_checkpoint(package)
    if not signed.get("valid"):
        return {
            "valid": False,
            "reason": "checkpoint_signature_invalid",
            "checkpoint_reason": signed.get("reason"),
        }
    key_id = str(signed.get("key_id") or "")
    trust_failure = _trusted_key_result(key_id, trusted_key_ids)
    if trust_failure is not None:
        return trust_failure
    return {
        "valid": True,
        "reason": "transparency_record_valid",
        "publication_id": expected_id,
        "checkpoint_id": checkpoint["checkpoint_id"],
        "checkpoint_package_sha256": package_sha256,
        "key_id": key_id,
        "action_count": signed.get("action_count"),
        "action_head_sha256": signed.get("action_head_sha256"),
    }


def _entry_core(
    *,
    sequence: int,
    previous_entry_sha256: str,
    appended_at: str,
    record: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "version": TRANSPARENCY_ENTRY_VERSION,
        "sequence": sequence,
        "previous_entry_sha256": previous_entry_sha256,
        "appended_at": appended_at,
        "record": dict(record),
    }


def create_transparency_entry(
    record: Mapping[str, Any],
    *,
    sequence: int,
    previous_entry_sha256: str,
    appended_at: str | None = None,
    trusted_key_ids: Collection[str] | None = None,
) -> dict[str, Any]:
    """Create one hash-chained ledger entry around a valid checkpoint record."""
    if sequence < 1:
        raise ValueError("transparency sequence must be positive")
    if not _is_sha256(previous_entry_sha256):
        raise ValueError("previous transparency entry hash is invalid")
    verification = verify_transparency_record(record, trusted_key_ids=trusted_key_ids)
    if not verification.get("valid"):
        raise ValueError(f"transparency record is not valid: {verification.get('reason')}")
    timestamp = appended_at or datetime.now(timezone.utc).isoformat()
    if not str(timestamp).strip():
        raise ValueError("appended_at must not be empty")
    core = _entry_core(
        sequence=sequence,
        previous_entry_sha256=previous_entry_sha256,
        appended_at=str(timestamp),
        record=record,
    )
    return {**core, "entry_sha256": _sha256(core)}


def _read_entries(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    if not path.exists():
        return [], None
    entries: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                return [], {"valid": False, "reason": "invalid_transparency_json", "line": number}
            if not isinstance(value, dict):
                return [], {"valid": False, "reason": "invalid_transparency_entry_shape", "line": number}
            entries.append(value)
    return entries, None


def verify_transparency_log(
    path: Path,
    *,
    trusted_key_ids: Collection[str] | None = None,
    expected_head_sha256: str | None = None,
) -> dict[str, Any]:
    """Verify ordering, hash chaining, signatures, and optional externally pinned head."""
    entries, error = _read_entries(path)
    if error is not None:
        return error

    previous = GENESIS_TRANSPARENCY_HASH
    publication_ids: set[str] = set()
    checkpoint_ids: set[str] = set()
    for index, entry in enumerate(entries, start=1):
        if set(entry) != _ENTRY_FIELDS or entry.get("version") != TRANSPARENCY_ENTRY_VERSION:
            return {"valid": False, "reason": "invalid_transparency_entry_shape", "sequence": index}
        try:
            sequence = int(entry["sequence"])
        except (TypeError, ValueError):
            return {"valid": False, "reason": "invalid_transparency_sequence", "sequence": index}
        if sequence != index:
            return {
                "valid": False,
                "reason": "transparency_sequence_gap",
                "expected_sequence": index,
                "actual_sequence": sequence,
            }
        if entry.get("previous_entry_sha256") != previous:
            return {"valid": False, "reason": "transparency_previous_hash_mismatch", "sequence": index}
        if not str(entry.get("appended_at") or "").strip():
            return {"valid": False, "reason": "invalid_transparency_entry_shape", "sequence": index}
        record = entry.get("record")
        if not isinstance(record, Mapping):
            return {"valid": False, "reason": "invalid_transparency_record_shape", "sequence": index}
        verified = verify_transparency_record(record, trusted_key_ids=trusted_key_ids)
        if not verified.get("valid"):
            return {
                "valid": False,
                "reason": "invalid_transparency_record",
                "sequence": index,
                "record_reason": verified.get("reason"),
            }
        publication_id = str(record.get("publication_id") or "")
        checkpoint_id = str(verified.get("checkpoint_id") or "")
        if publication_id in publication_ids or checkpoint_id in checkpoint_ids:
            return {"valid": False, "reason": "duplicate_transparency_checkpoint", "sequence": index}
        publication_ids.add(publication_id)
        checkpoint_ids.add(checkpoint_id)

        core = _entry_core(
            sequence=sequence,
            previous_entry_sha256=str(entry["previous_entry_sha256"]),
            appended_at=str(entry["appended_at"]),
            record=record,
        )
        computed = _sha256(core)
        if entry.get("entry_sha256") != computed:
            return {"valid": False, "reason": "transparency_entry_hash_mismatch", "sequence": index}
        previous = computed

    if expected_head_sha256 is not None and previous != expected_head_sha256:
        return {
            "valid": False,
            "reason": "unexpected_transparency_head",
            "expected_head_sha256": expected_head_sha256,
            "actual_head_sha256": previous,
            "entry_count": len(entries),
        }
    return {
        "valid": True,
        "reason": "transparency_log_valid",
        "entry_count": len(entries),
        "head_sha256": previous,
        "publication_ids": sorted(publication_ids),
        "checkpoint_ids": sorted(checkpoint_ids),
    }


def append_transparency_record(
    path: Path,
    record: Mapping[str, Any],
    *,
    trusted_key_ids: Collection[str] | None = None,
    appended_at: str | None = None,
) -> dict[str, Any]:
    """Append one verified checkpoint record; existing ledger bytes are never rewritten."""
    verification = verify_transparency_record(record, trusted_key_ids=trusted_key_ids)
    if not verification.get("valid"):
        raise ValueError(f"transparency record is not valid: {verification.get('reason')}")

    current = verify_transparency_log(path, trusted_key_ids=trusted_key_ids)
    if not current.get("valid"):
        raise ValueError(f"existing transparency log is not valid: {current.get('reason')}")
    if verification["publication_id"] in set(current.get("publication_ids") or []):
        raise ValueError("checkpoint is already published")
    if verification["checkpoint_id"] in set(current.get("checkpoint_ids") or []):
        raise ValueError("checkpoint is already published")

    sequence = int(current["entry_count"]) + 1
    entry = create_transparency_entry(
        record,
        sequence=sequence,
        previous_entry_sha256=str(current["head_sha256"]),
        appended_at=appended_at,
        trusted_key_ids=trusted_key_ids,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return {
        "published": True,
        "sequence": sequence,
        "publication_id": verification["publication_id"],
        "checkpoint_id": verification["checkpoint_id"],
        "key_id": verification["key_id"],
        "entry_sha256": entry["entry_sha256"],
        "head_sha256": entry["entry_sha256"],
    }
