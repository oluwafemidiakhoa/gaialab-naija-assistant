import base64
import hashlib
import json
import os
import tempfile

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, NoEncryption

from src.audit_export import create_audit_package, create_audit_package_from_store, verify_audit_package
from src.receipt_signing import sign_receipt
from src.receipt_store import ReceiptStore


def _private_key_b64() -> str:
    key = Ed25519PrivateKey.generate()
    raw = key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    return base64.b64encode(raw).decode("ascii")


def _canonical_sha256(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _refresh_unsigned_manifest(package: dict) -> None:
    package["manifest"]["entry_ids"] = [entry["verification_id"] for entry in package["entries"]]
    package["manifest"]["entry_hashes"] = [entry["payload_sha256"] for entry in package["entries"]]
    package["manifest"]["entry_count"] = len(package["entries"])
    core = {
        key: value
        for key, value in package["manifest"].items()
        if key not in {"package_id", "generated_at"}
    }
    package["manifest"]["package_id"] = _canonical_sha256(core)


def _receipt(tenant_id: str, verification_id: str, disposition: str, model: str) -> dict:
    return {
        "verification_id": verification_id,
        "tenant_id": tenant_id,
        "model_name": model,
        "model_version": "test",
        "language": "en-NG",
        "finding_codes": ["UNSUPPORTED_TIMELINE"] if disposition != "ALLOW" else [],
        "tenant_policy_id": "policy_test",
        "tenant_policy_hash": "hash",
        "tenant_policy_evaluation_id": "evaluation",
        "engine_receipt_id": "engine",
        "claim_extraction_id": "extract",
        "reconciliation_id": "reconcile",
        "disposition": disposition,
        "risk_score": 35 if disposition != "ALLOW" else 0,
        "api_version": "v1",
    }


def _store_receipt(store: ReceiptStore, tenant_id: str, verification_id: str, disposition: str, model: str) -> None:
    receipt = _receipt(tenant_id, verification_id, disposition, model)
    key = _private_key_b64()
    envelope = {"verification_receipt": receipt, "signature": sign_receipt(receipt, key)}
    store.save(verification_id, envelope, tenant_id=tenant_id)


def test_audit_export_is_tenant_scoped_and_filterable():
    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, "receipts.sqlite3")
        store = ReceiptStore(path)
        _store_receipt(store, "tenant_a", "v1", "BLOCK", "model-a")
        _store_receipt(store, "tenant_a", "v2", "ALLOW", "model-b")
        _store_receipt(store, "tenant_b", "v3", "BLOCK", "model-c")

        package = create_audit_package(
            receipt_store_path=path,
            tenant_id="tenant_a",
            dispositions=["BLOCK"],
            signing_key_b64=_private_key_b64(),
        )
        assert package["manifest"]["entry_count"] == 1
        assert package["entries"][0]["verification_id"] == "v1"
        assert package["manifest"]["summary"]["dispositions"] == {"BLOCK": 1}
        assert package["privacy"]["raw_prompts_included"] is False
        result = verify_audit_package(package)
        assert result["valid"] is True
        assert result["integrity"]["payload_hashes_recomputed"] is True
        assert result["integrity"]["receipt_signatures_recomputed"] is True
        assert result["integrity"]["stored_integrity_flags_trusted"] is False


def test_audit_manifest_detects_entry_tampering():
    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, "receipts.sqlite3")
        store = ReceiptStore(path)
        _store_receipt(store, "tenant_a", "v1", "ESCALATE", "model-a")
        package = create_audit_package(receipt_store_path=path, tenant_id="tenant_a")
        package["entries"][0]["payload_sha256"] = "0" * 64
        result = verify_audit_package(package)
        assert result["valid"] is False
        assert result["reason"] == "entry_manifest_mismatch"


def test_empty_audit_package_is_valid_and_deterministic_for_filters():
    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, "receipts.sqlite3")
        package = create_audit_package(
            receipt_store_path=path,
            tenant_id="tenant_a",
            dispositions=["BLOCK"],
        )
        assert package["manifest"]["entry_count"] == 0
        assert verify_audit_package(package)["valid"] is True


def test_verifier_ignores_exported_integrity_booleans_and_recomputes_evidence():
    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, "receipts.sqlite3")
        store = ReceiptStore(path)
        _store_receipt(store, "tenant_a", "v1", "BLOCK", "model-a")
        package = create_audit_package(receipt_store_path=path, tenant_id="tenant_a")
        package["entries"][0]["payload_integrity_valid"] = False
        package["entries"][0]["signature_valid"] = False

        result = verify_audit_package(package)
        assert result["valid"] is True
        assert result["integrity"]["stored_integrity_flags_trusted"] is False


def test_forged_true_flags_do_not_hide_receipt_tampering():
    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, "receipts.sqlite3")
        store = ReceiptStore(path)
        _store_receipt(store, "tenant_a", "v1", "BLOCK", "model-a")
        package = create_audit_package(receipt_store_path=path, tenant_id="tenant_a")
        package["entries"][0]["verification_receipt"]["model_version"] = "tampered"
        package["entries"][0]["payload_integrity_valid"] = True
        package["entries"][0]["signature_valid"] = True

        result = verify_audit_package(package)
        assert result["valid"] is False
        assert result["reason"] == "entry_payload_hash_mismatch"


def test_attacker_updated_hashes_cannot_hide_invalid_receipt_signature():
    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, "receipts.sqlite3")
        store = ReceiptStore(path)
        _store_receipt(store, "tenant_a", "v1", "BLOCK", "model-a")
        package = create_audit_package(receipt_store_path=path, tenant_id="tenant_a")
        entry = package["entries"][0]
        entry["verification_receipt"]["model_version"] = "tampered"
        envelope = {
            "verification_receipt": entry["verification_receipt"],
            "signature": entry["signature"],
        }
        entry["payload_sha256"] = _canonical_sha256(envelope)
        entry["payload_integrity_valid"] = True
        entry["signature_valid"] = True
        _refresh_unsigned_manifest(package)

        result = verify_audit_package(package)
        assert result["valid"] is False
        assert result["reason"] == "receipt_signature_failure"


def test_verifier_fails_closed_when_receipt_signature_is_missing():
    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, "receipts.sqlite3")
        store = ReceiptStore(path)
        _store_receipt(store, "tenant_a", "v1", "ALLOW", "model-a")
        package = create_audit_package(receipt_store_path=path, tenant_id="tenant_a")
        package["entries"][0]["signature"] = None
        package["entries"][0]["signature_valid"] = True

        result = verify_audit_package(package)
        assert result["valid"] is False
        assert result["reason"] == "missing_or_invalid_receipt_signature"


def test_verifier_rejects_cross_tenant_receipt_transplant():
    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, "receipts.sqlite3")
        store = ReceiptStore(path)
        _store_receipt(store, "tenant_a", "v1", "BLOCK", "model-a")
        package = create_audit_package(receipt_store_path=path, tenant_id="tenant_a")
        package["entries"][0]["verification_receipt"]["tenant_id"] = "tenant_b"

        result = verify_audit_package(package)
        assert result["valid"] is False
        assert result["reason"] == "entry_tenant_mismatch"


def test_verifier_rejects_manifest_signature_tampering():
    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, "receipts.sqlite3")
        store = ReceiptStore(path)
        _store_receipt(store, "tenant_a", "v1", "ALLOW", "model-a")
        package = create_audit_package(
            receipt_store_path=path,
            tenant_id="tenant_a",
            signing_key_b64=_private_key_b64(),
        )
        package["manifest_signature"]["signature_b64"] = base64.b64encode(b"x" * 64).decode("ascii")

        result = verify_audit_package(package)
        assert result["valid"] is False
        assert result["reason"] == "invalid_manifest_signature"


def test_export_creation_recomputes_backend_payload_integrity():
    receipt = _receipt("tenant_a", "v1", "BLOCK", "model-a")
    signature = sign_receipt(receipt, _private_key_b64())
    envelope = {"verification_receipt": receipt, "signature": signature}

    class Backend:
        def list_for_tenant(self, tenant_id, **kwargs):
            assert tenant_id == "tenant_a"
            return [
                {
                    "verification_id": "v1",
                    "created_at": "2026-08-10T00:00:00+00:00",
                    "payload_sha256": _canonical_sha256(envelope),
                    "payload_integrity_valid": False,
                    "envelope": envelope,
                }
            ]

    package = create_audit_package_from_store(receipt_store=Backend(), tenant_id="tenant_a")
    assert package["entries"][0]["payload_integrity_valid"] is True
    assert package["manifest"]["summary"]["integrity_failures"] == 0
    assert verify_audit_package(package)["valid"] is True
