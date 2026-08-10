from datetime import datetime, timedelta, timezone
import os
import tempfile

from src.audit_lifecycle import AuditLifecycleStore
from src.operator_auth import OperatorRegistry, require_admin_scope


def _package(tenant_id: str = "tenant_a") -> dict:
    manifest = {
        "package_id": "pkg_123",
        "version": "gaialab-naija-audit-export/0.1.0",
        "tenant_id": tenant_id,
        "filters": {},
        "entry_ids": [],
        "entry_hashes": [],
        "entry_count": 0,
        "summary": {"dispositions": {}, "models": {}, "finding_codes": {}, "integrity_failures": 0},
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    return {"manifest": manifest, "manifest_signature": None, "entries": []}


def test_operator_keys_are_separate_scoped_and_disableable():
    with tempfile.TemporaryDirectory() as directory:
        registry = OperatorRegistry(os.path.join(directory, "operators.sqlite3"))
        operator = registry.create_operator("Risk Admin")
        issued = registry.issue_admin_key(operator["operator_id"], scopes=["audit:lifecycle"])
        assert issued["admin_api_key"].startswith("gaia_admin_")
        identity = registry.authenticate(issued["admin_api_key"])
        assert identity["identity_type"] == "operator"
        require_admin_scope(identity, "audit:lifecycle")
        try:
            require_admin_scope(identity, "tenants:manage")
            assert False, "missing admin scope must be rejected"
        except PermissionError:
            pass
        registry.disable_admin_key(issued["key_id"])
        assert registry.authenticate(issued["admin_api_key"]) is None


def test_audit_lifecycle_legal_hold_blocks_retention_eligibility():
    with tempfile.TemporaryDirectory() as directory:
        store = AuditLifecycleStore(os.path.join(directory, "audit.sqlite3"))
        retention = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        record = store.register_export(
            _package(),
            tenant_id="tenant_a",
            created_by_key_id="gk_service",
            retention_until=retention,
        )
        status = store.retention_status(record["package_id"])
        assert status["retention_expired"] is True
        assert status["eligible_for_deletion"] is True

        store.add_event(
            record["package_id"],
            actor_type="operator",
            actor_id="operator_1",
            event_type="legal_hold_placed",
            metadata={"case_id": "CASE-42"},
        )
        held = store.retention_status(record["package_id"])
        assert held["legal_hold_active"] is True
        assert held["eligible_for_deletion"] is False

        store.add_event(
            record["package_id"],
            actor_type="operator",
            actor_id="operator_1",
            event_type="legal_hold_released",
            metadata={"case_id": "CASE-42"},
        )
        released = store.retention_status(record["package_id"])
        assert released["legal_hold_active"] is False
        assert released["eligible_for_deletion"] is True


def test_audit_lifecycle_events_are_append_only_and_retention_can_extend():
    with tempfile.TemporaryDirectory() as directory:
        store = AuditLifecycleStore(os.path.join(directory, "audit.sqlite3"))
        record = store.register_export(
            _package(),
            tenant_id="tenant_a",
            created_by_key_id="gk_service",
            retention_until=None,
        )
        future = (datetime.now(timezone.utc) + timedelta(days=365)).isoformat()
        store.add_event(
            record["package_id"],
            actor_type="operator",
            actor_id="operator_1",
            event_type="retention_extended",
            metadata={"retention_until": future, "reason": "regulatory review"},
        )
        store.add_event(
            record["package_id"],
            actor_type="operator",
            actor_id="operator_1",
            event_type="reviewed",
            metadata={"note": "annual control review"},
        )
        updated = store.get(record["package_id"])
        assert updated["retention_until"] == future
        assert [event["event_type"] for event in updated["events"]] == [
            "export_registered",
            "retention_extended",
            "reviewed",
        ]
