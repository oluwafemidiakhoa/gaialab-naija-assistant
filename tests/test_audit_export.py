import base64
import os
import tempfile

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, NoEncryption

from src.audit_export import create_audit_package, verify_audit_package
from src.receipt_signing import sign_receipt
from src.receipt_store import ReceiptStore


def _private_key_b64() -> str:
    key = Ed25519PrivateKey.generate()
    raw = key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    return base64.b64encode(raw).decode("ascii")


def _store_receipt(store: ReceiptStore, tenant_id: str, verification_id: str, disposition: str, model: str) -> None:
    receipt = {
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
        assert verify_audit_package(package)["valid"] is True


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
