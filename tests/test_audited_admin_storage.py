import pytest

from src.audited_admin_storage import AuditedAuditLifecycleStore, AuditedRetentionDeletionStore
from src.operator_action_log import OperatorActionLog


class _LifecycleStore:
    def __init__(self, fail=False): self.fail = fail
    def add_event(self, package_id, *, actor_type, actor_id, event_type, metadata=None):
        if self.fail: raise RuntimeError("mutation failed")
        return {"package_id": package_id, "event_type": event_type}


class _RetentionStore:
    def __init__(self, fail=False): self.fail = fail
    def approve(self, plan_id, operator_id):
        if self.fail: raise RuntimeError("approval failed")
        return {"plan_id": plan_id, "approval_count": 2}
    def execute(self, plan_id, operator_id, *, now=None):
        if self.fail: raise RuntimeError("execution failed")
        return {"plan_id": plan_id, "events": [{"event_type": "executed", "metadata": {"deleted_audit_exports": 1, "deleted_verification_receipts": 0}}]}


def test_lifecycle_success_records_requested_and_completed(tmp_path):
    log = OperatorActionLog(tmp_path / "actions.sqlite3")
    store = AuditedAuditLifecycleStore(_LifecycleStore(), log)
    store.add_event("package_1", actor_type="operator", actor_id="operator_a", event_type="legal_hold_placed", metadata={"case": "x"})
    actions = log.list(limit=10)
    assert [row["action_type"] for row in actions] == [
        "audit.lifecycle.legal_hold_placed.requested",
        "audit.lifecycle.legal_hold_placed.completed",
    ]
    assert "package_1" not in str(actions)
    assert log.verify_chain()["valid"] is True


def test_failed_lifecycle_mutation_preserves_requested_action(tmp_path):
    log = OperatorActionLog(tmp_path / "actions.sqlite3")
    store = AuditedAuditLifecycleStore(_LifecycleStore(fail=True), log)
    with pytest.raises(RuntimeError, match="mutation failed"):
        store.add_event("package_1", actor_type="operator", actor_id="operator_a", event_type="legal_hold_placed")
    actions = log.list(limit=10)
    assert [row["action_type"] for row in actions] == ["audit.lifecycle.legal_hold_placed.requested"]


def test_retention_approval_and_execution_are_audited(tmp_path):
    log = OperatorActionLog(tmp_path / "actions.sqlite3")
    store = AuditedRetentionDeletionStore(_RetentionStore(), log)
    store.approve("plan_1", "operator_a")
    store.execute("plan_1", "operator_b")
    actions = log.list(limit=10)
    assert [row["action_type"] for row in actions] == [
        "retention.approval.requested",
        "retention.approval.completed",
        "retention.execute.requested",
        "retention.execute.completed",
    ]
    assert actions[-1]["metadata"]["deleted_verification_receipts"] == 0
    assert log.verify_chain()["valid"] is True


def test_failed_retention_execution_keeps_requested_action(tmp_path):
    log = OperatorActionLog(tmp_path / "actions.sqlite3")
    store = AuditedRetentionDeletionStore(_RetentionStore(fail=True), log)
    with pytest.raises(RuntimeError, match="execution failed"):
        store.execute("plan_1", "operator_a")
    actions = log.list(limit=10)
    assert [row["action_type"] for row in actions] == ["retention.execute.requested"]
