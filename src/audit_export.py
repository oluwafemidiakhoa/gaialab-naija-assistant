"""Tenant-scoped audit export packages for GaiaLab Naija Trust Rail."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Mapping, Sequence

from src.receipt_signing import sign_receipt, verify_receipt_signature
from src.receipt_store import ReceiptStore

AUDIT_EXPORT_VERSION = "gaialab-naija-audit-export/0.2.0"


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _sha256(payload: Any) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _is_sha256(value: Any) -> bool:
    text = str(value or "")
    return len(text) == 64 and all(character in "0123456789abcdef" for character in text.lower())


def _normalize_dispositions(values: Sequence[str] | None) -> set[str] | None:
    if not values:
        return None
    allowed = {"ALLOW", "VERIFY", "REWRITE", "ESCALATE", "BLOCK"}
    normalized = {str(value).upper() for value in values}
    unknown = normalized - allowed
    if unknown:
        raise ValueError(f"unknown dispositions: {', '.join(sorted(unknown))}")
    return normalized


def _matches(record: Mapping[str, Any], dispositions: set[str] | None) -> bool:
    if dispositions is None:
        return True
    receipt = record["envelope"].get("verification_receipt") or {}
    return receipt.get("disposition") in dispositions


def _receipt_envelope(receipt: Mapping[str, Any], signature: Mapping[str, Any] | None) -> dict[str, Any]:
    return {
        "verification_receipt": dict(receipt),
        "signature": dict(signature) if signature is not None else None,
    }


def _summary_from_receipts(receipts: Sequence[Mapping[str, Any]], *, integrity_failures: int) -> dict[str, Any]:
    disposition_counts: dict[str, int] = {}
    model_counts: dict[str, int] = {}
    finding_counts: dict[str, int] = {}
    for receipt in receipts:
        disposition = str(receipt.get("disposition") or "UNKNOWN")
        model_name = str(receipt.get("model_name") or "unknown")
        disposition_counts[disposition] = disposition_counts.get(disposition, 0) + 1
        model_counts[model_name] = model_counts.get(model_name, 0) + 1
        finding_codes = receipt.get("finding_codes") or []
        if isinstance(finding_codes, (str, bytes)) or not isinstance(finding_codes, Sequence):
            raise ValueError("finding_codes must be a sequence")
        for code in finding_codes:
            finding_counts[str(code)] = finding_counts.get(str(code), 0) + 1
    return {
        "dispositions": dict(sorted(disposition_counts.items())),
        "models": dict(sorted(model_counts.items())),
        "finding_codes": dict(sorted(finding_counts.items())),
        "integrity_failures": int(integrity_failures),
    }


def create_audit_package_from_store(
    *,
    receipt_store: Any,
    tenant_id: str,
    created_from: str | None = None,
    created_to: str | None = None,
    dispositions: Sequence[str] | None = None,
    limit: int = 10000,
    signing_key_b64: str | None = None,
) -> dict[str, Any]:
    selected_dispositions = _normalize_dispositions(dispositions)
    records = receipt_store.list_for_tenant(
        tenant_id,
        created_from=created_from,
        created_to=created_to,
        limit=limit,
    )
    records = [record for record in records if _matches(record, selected_dispositions)]

    entries: list[dict[str, Any]] = []
    receipts: list[Mapping[str, Any]] = []
    integrity_failures = 0

    for record in records:
        envelope = record["envelope"]
        receipt = envelope.get("verification_receipt") or {}
        signature = envelope.get("signature")
        if not isinstance(receipt, Mapping):
            raise ValueError("receipt store returned an invalid verification receipt")
        if signature is not None and not isinstance(signature, Mapping):
            raise ValueError("receipt store returned an invalid receipt signature")

        stored_payload_sha256 = str(record.get("payload_sha256") or "")
        actual_payload_sha256 = _sha256(_receipt_envelope(receipt, signature))
        payload_integrity_valid = stored_payload_sha256 == actual_payload_sha256
        signature_valid: bool | None = None
        if signature is not None:
            signature_valid = bool(verify_receipt_signature(receipt, signature)["valid"])
        if not payload_integrity_valid or signature_valid is False:
            integrity_failures += 1

        receipts.append(receipt)
        entries.append(
            {
                "verification_id": record["verification_id"],
                "stored_at": record["created_at"],
                "payload_sha256": stored_payload_sha256,
                "payload_integrity_valid": payload_integrity_valid,
                "signature_valid": signature_valid,
                "verification_receipt": dict(receipt),
                "signature": dict(signature) if signature is not None else None,
            }
        )

    manifest_core = {
        "version": AUDIT_EXPORT_VERSION,
        "tenant_id": tenant_id,
        "filters": {
            "created_from": created_from,
            "created_to": created_to,
            "dispositions": sorted(selected_dispositions) if selected_dispositions else None,
            "limit": limit,
        },
        "entry_ids": [entry["verification_id"] for entry in entries],
        "entry_hashes": [entry["payload_sha256"] for entry in entries],
        "entry_count": len(entries),
        "summary": _summary_from_receipts(receipts, integrity_failures=integrity_failures),
    }
    manifest = {
        "package_id": _sha256(manifest_core),
        **manifest_core,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    signature = sign_receipt(manifest_core, signing_key_b64) if signing_key_b64 else None

    return {
        "manifest": manifest,
        "manifest_signature": signature,
        "entries": entries,
        "privacy": {
            "raw_prompts_included": False,
            "raw_authoritative_state_included": False,
            "raw_evidence_included": False,
        },
    }


def create_audit_package(
    *,
    receipt_store_path: str,
    tenant_id: str,
    created_from: str | None = None,
    created_to: str | None = None,
    dispositions: Sequence[str] | None = None,
    limit: int = 10000,
    signing_key_b64: str | None = None,
) -> dict[str, Any]:
    """Backward-compatible SQLite wrapper used by local scripts/tests."""
    return create_audit_package_from_store(
        receipt_store=ReceiptStore(receipt_store_path),
        tenant_id=tenant_id,
        created_from=created_from,
        created_to=created_to,
        dispositions=dispositions,
        limit=limit,
        signing_key_b64=signing_key_b64,
    )


def verify_audit_package(package: Mapping[str, Any]) -> dict[str, Any]:
    """Verify an audit package from canonical evidence rather than stored booleans."""
    manifest = dict(package.get("manifest") or {})
    entries = list(package.get("entries") or [])
    if not manifest:
        return {"valid": False, "reason": "missing_manifest"}
    if manifest.get("version") != AUDIT_EXPORT_VERSION:
        return {"valid": False, "reason": "unsupported_audit_export_version"}
    tenant_id = str(manifest.get("tenant_id") or "")
    if not tenant_id:
        return {"valid": False, "reason": "invalid_manifest_shape"}

    core = {key: value for key, value in manifest.items() if key not in {"package_id", "generated_at"}}
    expected_id = _sha256(core)
    if manifest.get("package_id") != expected_id:
        return {"valid": False, "reason": "package_id_mismatch"}
    if core.get("entry_count") != len(entries):
        return {"valid": False, "reason": "entry_count_mismatch"}

    entry_ids = [entry.get("verification_id") for entry in entries]
    entry_hashes = [entry.get("payload_sha256") for entry in entries]
    if entry_ids != core.get("entry_ids") or entry_hashes != core.get("entry_hashes"):
        return {"valid": False, "reason": "entry_manifest_mismatch"}
    if len(set(entry_ids)) != len(entry_ids):
        return {"valid": False, "reason": "duplicate_entry_id"}

    signature = package.get("manifest_signature")
    signature_result = None
    if signature:
        signature_result = verify_receipt_signature(core, signature)
        if not signature_result["valid"]:
            return {"valid": False, "reason": "invalid_manifest_signature"}

    verified_receipts: list[Mapping[str, Any]] = []
    signed_receipts = 0
    unsigned_receipts = 0
    for index, entry in enumerate(entries):
        if not isinstance(entry, Mapping):
            return {"valid": False, "reason": "invalid_entry_shape", "entry_index": index}
        verification_id = str(entry.get("verification_id") or "")
        payload_sha256 = str(entry.get("payload_sha256") or "")
        receipt = entry.get("verification_receipt")
        receipt_signature = entry.get("signature")
        if not verification_id or not _is_sha256(payload_sha256) or not isinstance(receipt, Mapping):
            return {"valid": False, "reason": "invalid_entry_shape", "entry_index": index}
        if receipt_signature is not None and not isinstance(receipt_signature, Mapping):
            return {"valid": False, "reason": "invalid_entry_shape", "entry_index": index}
        if receipt.get("verification_id") != verification_id:
            return {
                "valid": False,
                "reason": "entry_verification_id_mismatch",
                "entry_index": index,
                "verification_id": verification_id,
            }
        if receipt.get("tenant_id") != tenant_id:
            return {
                "valid": False,
                "reason": "entry_tenant_mismatch",
                "entry_index": index,
                "verification_id": verification_id,
            }

        recomputed_payload_sha256 = _sha256(_receipt_envelope(receipt, receipt_signature))
        if recomputed_payload_sha256 != payload_sha256:
            return {
                "valid": False,
                "reason": "entry_payload_hash_mismatch",
                "entry_index": index,
                "verification_id": verification_id,
                "expected_payload_sha256": payload_sha256,
                "recomputed_payload_sha256": recomputed_payload_sha256,
            }

        if receipt_signature is None:
            unsigned_receipts += 1
        else:
            signed_receipts += 1
            receipt_signature_result = verify_receipt_signature(receipt, receipt_signature)
            if not receipt_signature_result["valid"]:
                return {
                    "valid": False,
                    "reason": "receipt_signature_failure",
                    "entry_index": index,
                    "verification_id": verification_id,
                    "signature_reason": receipt_signature_result.get("reason"),
                }
        verified_receipts.append(receipt)

    try:
        recomputed_summary = _summary_from_receipts(verified_receipts, integrity_failures=0)
    except ValueError:
        return {"valid": False, "reason": "invalid_entry_shape"}
    if core.get("summary") != recomputed_summary:
        return {
            "valid": False,
            "reason": "summary_mismatch",
            "recomputed_summary": recomputed_summary,
        }

    return {
        "valid": True,
        "reason": "audit_package_valid",
        "package_id": expected_id,
        "signed": signature is not None,
        "signature": signature_result,
        "entry_count": len(entries),
        "integrity": {
            "payload_hashes_recomputed": True,
            "receipt_signatures_recomputed": True,
            "stored_integrity_flags_trusted": False,
            "signed_receipts": signed_receipts,
            "unsigned_receipts": unsigned_receipts,
        },
    }
