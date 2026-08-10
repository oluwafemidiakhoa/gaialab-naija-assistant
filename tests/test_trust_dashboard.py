from __future__ import annotations

import os

import pytest

from src.audit_lifecycle import AuditLifecycleStore
from src.operator_auth import OperatorRegistry
from src.receipt_store import ReceiptStore
from src.trust_dashboard_data import authenticate_dashboard_operator, tenant_snapshot


def _receipt(verification_id: str, *, model: str, disposition: str, risk: int, language: str = "Nigerian Pidgin"):
    return {
        "verification_receipt": {
            "verification_id": verification_id,
            "tenant_id": "tenant_demo",
            "model_name": model,
            "model_version": "test",
            "language": language,
            "finding_codes": ["UNSUPPORTED_TIMELINE"] if risk else [],
            "tenant_policy_id": "policy_demo",
            "disposition": disposition,
            "risk_score": risk,
        },
        "signature": {"algorithm": "Ed25519", "key_id": "test", "signature_b64": "x"},
    }


def test_dashboard_requires_explicit_read_scope(tmp_path, monkeypatch):
    db = tmp_path / "operators.sqlite3"
    registry = OperatorRegistry(db)
    operator = registry.create_operator("Dashboard Operator")
    allowed = registry.issue_admin_key(operator["operator_id"], scopes=["dashboard:read"])
    denied = registry.issue_admin_key(operator["operator_id"], scopes=["audit:lifecycle"])
    monkeypatch.setenv("GAIALAB_OPERATOR_DB", str(db))
    monkeypatch.delenv("GAIALAB_DATABASE_URL", raising=False)

    identity = authenticate_dashboard_operator(allowed["admin_api_key"])
    assert identity["operator_id"] == operator["operator_id"]
    with pytest.raises(PermissionError):
        authenticate_dashboard_operator(denied["admin_api_key"])


def test_tenant_snapshot_aggregates_receipts_and_retention(tmp_path, monkeypatch):
    receipt_db = tmp_path / "receipts.sqlite3"
    lifecycle_db = tmp_path / "audit.sqlite3"
    store = ReceiptStore(receipt_db)
    store.save("vr_1", _receipt("vr_1", model="openai/gpt-test", disposition="ALLOW", risk=0), tenant_id="tenant_demo")
    store.save("vr_2", _receipt("vr_2", model="anthropic/claude-test", disposition="BLOCK", risk=80), tenant_id="tenant_demo")
    store.save("vr_other", _receipt("vr_other", model="openai/gpt-test", disposition="ALLOW", risk=0), tenant_id="tenant_other")

    lifecycle = AuditLifecycleStore(lifecycle_db)
    package = {"manifest": {"package_id": "pkg_1", "tenant_id": "tenant_demo"}}
    lifecycle.register_export(
        package,
        tenant_id="tenant_demo",
        created_by_key_id="gk_test",
        retention_until="2000-01-01T00:00:00+00:00",
    )
    lifecycle.add_event(
        "pkg_1",
        actor_type="operator",
        actor_id="operator_test",
        event_type="legal_hold_placed",
    )

    monkeypatch.setenv("GAIALAB_TRUST_RECEIPT_DB", str(receipt_db))
    monkeypatch.setenv("GAIALAB_AUDIT_LIFECYCLE_DB", str(lifecycle_db))
    monkeypatch.delenv("GAIALAB_DATABASE_URL", raising=False)

    snapshot = tenant_snapshot("tenant_demo")
    assert snapshot["receipt_count"] == 2
    assert snapshot["average_risk_score"] == 40.0
    assert snapshot["high_risk_count"] == 1
    assert snapshot["dispositions"] == {"BLOCK": 1, "ALLOW": 1} or snapshot["dispositions"] == {"ALLOW": 1, "BLOCK": 1}
    assert snapshot["providers"] == {"openai": 1, "anthropic": 1}
    assert snapshot["audit_export_count"] == 1
    assert snapshot["legal_hold_count"] == 1
    assert snapshot["retention_eligible_count"] == 0


def test_dashboard_does_not_expose_other_tenant_receipts(tmp_path, monkeypatch):
    receipt_db = tmp_path / "receipts.sqlite3"
    store = ReceiptStore(receipt_db)
    store.save("vr_demo", _receipt("vr_demo", model="qwen/test", disposition="ALLOW", risk=0), tenant_id="tenant_demo")
    store.save("vr_other", _receipt("vr_other", model="gemini/test", disposition="BLOCK", risk=80), tenant_id="tenant_other")
    monkeypatch.setenv("GAIALAB_TRUST_RECEIPT_DB", str(receipt_db))
    monkeypatch.delenv("GAIALAB_DATABASE_URL", raising=False)
    monkeypatch.delenv("GAIALAB_AUDIT_LIFECYCLE_DB", raising=False)

    snapshot = tenant_snapshot("tenant_demo")
    assert [item["verification_id"] for item in snapshot["receipts"]] == ["vr_demo"]
