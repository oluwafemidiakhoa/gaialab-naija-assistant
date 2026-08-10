import base64
import os
import tempfile

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from src.key_registry import SigningKeyRegistry, SigningKeyRegistryError
from src.receipt_store import ReceiptConflictError, ReceiptStore
from src.tenant_auth import TenantRegistry


def _public_key_b64(private_key: Ed25519PrivateKey) -> str:
    raw = private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return base64.b64encode(raw).decode("ascii")


def test_signing_key_registry_rotation_and_revocation():
    with tempfile.TemporaryDirectory() as directory:
        registry = SigningKeyRegistry(os.path.join(directory, "keys.sqlite3"))
        first = Ed25519PrivateKey.generate()
        second = Ed25519PrivateKey.generate()

        first_record = registry.register(_public_key_b64(first), label="primary")
        assert first_record["status"] == "active"
        registry.transition(first_record["key_id"], "retired", reason="rotation")
        try:
            registry.assert_can_sign(first_record["key_id"])
            assert False, "retired key must not be allowed to sign"
        except SigningKeyRegistryError:
            pass

        second_record = registry.register(_public_key_b64(second), label="rotation-2")
        assert registry.assert_can_sign(second_record["key_id"])["status"] == "active"
        registry.transition(second_record["key_id"], "revoked", reason="test compromise")
        assert registry.get(second_record["key_id"])["status"] == "revoked"
        assert [event["event_type"] for event in registry.events(first_record["key_id"])] == [
            "registered",
            "activated",
            "retired",
        ]


def test_tenant_api_keys_are_hashed_scoped_and_disableable():
    with tempfile.TemporaryDirectory() as directory:
        registry = TenantRegistry(os.path.join(directory, "tenants.sqlite3"))
        tenant = registry.create_tenant("Example Bank")
        issued = registry.issue_api_key(tenant["tenant_id"], label="server")
        identity = registry.authenticate(issued["api_key"])
        assert identity["tenant_id"] == tenant["tenant_id"]
        assert identity["tenant_name"] == "Example Bank"
        registry.disable_api_key(issued["key_id"])
        assert registry.authenticate(issued["api_key"]) is None


def test_receipt_store_enforces_tenant_ownership():
    with tempfile.TemporaryDirectory() as directory:
        store = ReceiptStore(os.path.join(directory, "receipts.sqlite3"))
        envelope = {"verification_receipt": {"verification_id": "v1"}}
        assert store.save("v1", envelope, tenant_id="tenant_a") is True
        assert store.get("v1", tenant_id="tenant_a") == envelope
        assert store.get("v1", tenant_id="tenant_b") is None
        try:
            store.save("v1", envelope, tenant_id="tenant_b")
            assert False, "same receipt ID must not be rebound to another tenant"
        except ReceiptConflictError:
            pass
