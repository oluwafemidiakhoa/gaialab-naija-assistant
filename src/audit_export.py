"""Tenant-scoped audit export packages for GaiaLab Naija Trust Rail."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Mapping, Sequence

from src.receipt_signing import sign_receipt, verify_receipt_signature
from src.receipt_store import ReceiptStore

AUDIT_EXPORT_VERSION = "gaialab-naija-audit-export/0.1.0"


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _sha256(payload: Any) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


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
    selected_dispositions = _normalize_dispositions(dispositions)
    records = ReceiptStore(receipt_store_path).list_for_tenant(
        tenant_id,
        created_from=created_from,
        created_to=created_to,
        limit=limit,
    )
    records = [record for record in records if _matches(record, selected_dispositions)]

    entries: list[dict[str, Any]] = []
    disposition_counts: dict[str, int] = {}
    model_counts: dict[str, int] = {}
    finding_counts: dict[str, int] = {}
    integrity_failures = 0

    for record in records:
        envelope = record["envelope"]
        receipt = envelope.get("verification_receipt") or {}
        signature = envelope.get("signature")
        signature_valid: bool | None = None
        if signature:
            signature_valid = bool(verify_receipt_signature(receipt, signature)["valid"])
        if not record["payload_integrity_valid"] or signature_valid is False:
            integrity_failures += 1

        disposition = str(receipt.get("disposition") or "UNKNOWN")
        model_name = str(receipt.get("model_name") or "unknown")
        disposition_counts[disposition] = disposition_counts.get(disposition, 0) + 1
        model_counts[model_name] = model_counts.get(model_name, 0) + 1
        for code in receipt.get("finding_codes") or []:
            finding_counts[str(code)] = finding_counts.get(str(code), 0) + 1

        entries.append(
            {
                "verification_id": record["verification_id"],
                "stored_at": record["created_at"],
                "payload_sha256": record["payload_sha256"],
                "payload_integrity_valid": record["payload_integrity_valid"],
                "signature_valid": signature_valid,
                "verification_receipt": receipt,
                "signature": signature,
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
        "summary": {
            "dispositions": dict(sorted(disposition_counts.items())),
            "models": dict(sorted(model_counts.items())),
            "finding_codes": dict(sorted(finding_counts.items())),
            "integrity_failures": integrity_failures,
        },
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


def verify_audit_package(package: Mapping[str, Any]) -> dict[str, Any]:
    manifest = dict(package.get("manifest") or {})
    entries = list(package.get("entries") or [])
    if not manifest:
        return {"valid": False, "reason": "missing_manifest"}

    core = {key: value for key, value in manifest.items() if key not in {"package_id", "generated_at"}}
    expected_id = _sha256(core)
    if manifest.get("package_id") != expected_id:
        return {"valid": False, "reason": "package_id_mismatch"}

    entry_ids = [entry.get("verification_id") for entry in entries]
    entry_hashes = [entry.get("payload_sha256") for entry in entries]
    if entry_ids != core.get("entry_ids") or entry_hashes != core.get("entry_hashes"):
        return {"valid": False, "reason": "entry_manifest_mismatch"}

    signature = package.get("manifest_signature")
    signature_result = None
    if signature:
        signature_result = verify_receipt_signature(core, signature)
        if not signature_result["valid"]:
            return {"valid": False, "reason": "invalid_manifest_signature"}

    if any(entry.get("payload_integrity_valid") is False for entry in entries):
        return {"valid": False, "reason": "stored_payload_integrity_failure"}
    if any(entry.get("signature_valid") is False for entry in entries):
        return {"valid": False, "reason": "receipt_signature_failure"}

    return {
        "valid": True,
        "reason": "audit_package_valid",
        "package_id": expected_id,
        "signed": signature is not None,
        "signature": signature_result,
        "entry_count": len(entries),
    }
