from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import sqlite3

import pytest

from src.audit_lifecycle import AuditLifecycleStore
from src.receipt_signing import generate_signing_keypair, verify_receipt_signature
from src.receipt_store import ReceiptStore
from src.retention_deletion import (
    RetentionDeletionError,
    RetentionDeletionStore,
    create_signed_deletion_plan,
)


def _register_expired_export(path, *, package_id="package_1"):
    lifecycle = AuditLifecycleStore(path)
    retention_until = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    lifecycle.register_export(
        {"manifest": {"package_id": package_id, "tenant_id": "tenant_1"}},
        tenant_id="tenant_1",
        created_by_key_id="service_key_1",
        retention_until=retention_until,
    )
    return lifecycle


def _create_plan(path, lifecycle, *, operator_id="operator_a"):
    keys = generate_signing_keypair()
    store = RetentionDeletionStore(path)
    plan = create_signed_deletion_plan(
        authorization_store=store,
        lifecycle_store=lifecycle,
        package_id="package_1",
        operator_id=operator_id,
        signing_key_b64=keys["private_key_b64"],
    )
    return store, plan


def test_deletion_requires_two_distinct_operator_approvals_and_preserves_receipts(tmp_path):
    path = tmp_path / "audit.sqlite3"
    lifecycle = _register_expired_export(path)
    receipts = ReceiptStore(path)
    receipts.save(
        "verification_1",
        {"verification_receipt": {"verification_id": "verification_1"}, "signature": None},
        tenant_id="tenant_1",
    )
    store, plan = _create_plan(path, lifecycle)

    first = store.approve(plan["plan_id"], "operator_a")
    duplicate = store.approve(plan["plan_id"], "operator_a")
    assert first["approval_count"] == 1
    assert duplicate["approval_count"] == 1
    with pytest.raises(RetentionDeletionError, match="two distinct"):
        store.execute(plan["plan_id"], "operator_a")

    approved = store.approve(plan["plan_id"], "operator_b")
    assert approved["approval_count"] == 2
    assert approved["ready_to_execute"] is True

    executed = store.execute(plan["plan_id"], "operator_b")
    assert executed["executed"] is True
    assert lifecycle.get("package_1") is None
    assert receipts.get("verification_1", tenant_id="tenant_1") is not None
    execution = [event for event in executed["events"] if event["event_type"] == "executed"][-1]
    assert execution["metadata"]["deleted_audit_exports"] == 1
    assert execution["metadata"]["deleted_verification_receipts"] == 0
    assert verify_receipt_signature(
        executed["eligibility_snapshot"],
        executed["evidence_signature"],
    )["valid"] is True


def test_active_legal_hold_blocks_deletion_planning(tmp_path):
    path = tmp_path / "audit.sqlite3"
    lifecycle = _register_expired_export(path)
    lifecycle.add_event(
        "package_1",
        actor_type="operator",
        actor_id="operator_legal",
        event_type="legal_hold_placed",
    )
    keys = generate_signing_keypair()
    with pytest.raises(RetentionDeletionError, match="not eligible"):
        create_signed_deletion_plan(
            authorization_store=RetentionDeletionStore(path),
            lifecycle_store=lifecycle,
            package_id="package_1",
            operator_id="operator_a",
            signing_key_b64=keys["private_key_b64"],
        )


def test_legal_hold_added_after_planning_blocks_execution(tmp_path):
    path = tmp_path / "audit.sqlite3"
    lifecycle = _register_expired_export(path)
    store, plan = _create_plan(path, lifecycle)
    store.approve(plan["plan_id"], "operator_a")
    store.approve(plan["plan_id"], "operator_b")
    lifecycle.add_event(
        "package_1",
        actor_type="operator",
        actor_id="operator_legal",
        event_type="legal_hold_placed",
    )
    with pytest.raises(RetentionDeletionError, match="no longer eligible"):
        store.execute(plan["plan_id"], "operator_b")
    assert lifecycle.get("package_1") is not None


def test_cancelled_plan_cannot_be_approved_or_executed(tmp_path):
    path = tmp_path / "audit.sqlite3"
    lifecycle = _register_expired_export(path)
    store, plan = _create_plan(path, lifecycle)
    cancelled = store.cancel(plan["plan_id"], "operator_a", reason="policy review")
    assert cancelled["cancelled"] is True
    with pytest.raises(RetentionDeletionError, match="closed"):
        store.approve(plan["plan_id"], "operator_b")
    with pytest.raises(RetentionDeletionError, match="cancelled"):
        store.execute(plan["plan_id"], "operator_b")


def test_tampered_eligibility_evidence_blocks_execution(tmp_path):
    path = tmp_path / "audit.sqlite3"
    lifecycle = _register_expired_export(path)
    store, plan = _create_plan(path, lifecycle)
    store.approve(plan["plan_id"], "operator_a")
    store.approve(plan["plan_id"], "operator_b")

    with sqlite3.connect(path) as connection:
        snapshot = json.loads(
            connection.execute(
                "SELECT eligibility_snapshot_json FROM retention_deletion_plans WHERE plan_id = ?",
                (plan["plan_id"],),
            ).fetchone()[0]
        )
        snapshot["manifest_sha256"] = "tampered"
        connection.execute(
            "UPDATE retention_deletion_plans SET eligibility_snapshot_json = ? WHERE plan_id = ?",
            (json.dumps(snapshot, sort_keys=True, separators=(",", ":")), plan["plan_id"]),
        )

    with pytest.raises(RetentionDeletionError, match="signature is invalid"):
        store.execute(plan["plan_id"], "operator_b")
    assert lifecycle.get("package_1") is not None
