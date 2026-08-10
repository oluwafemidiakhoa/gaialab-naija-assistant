import hashlib
import sqlite3

import pytest

from src.operator_action_log import OperatorActionLog, OperatorActionLogError


def test_operator_actions_form_valid_hash_chain_without_raw_target(tmp_path):
    path = tmp_path / "actions.sqlite3"
    log = OperatorActionLog(path)
    first = log.append(
        operator_id="operator_a",
        key_id="key_a",
        action_type="audit.legal_hold_placed",
        target_type="audit_export",
        target_id="package_sensitive_123",
        metadata={"reason": "litigation"},
    )
    second = log.append(
        operator_id="operator_b",
        key_id="key_b",
        action_type="retention.approved",
        target_type="deletion_plan",
        target_id="plan_456",
        metadata={"approval_count": 2},
    )
    assert second["previous_action_hash"] == first["action_hash"]
    assert first["target_id_sha256"] == hashlib.sha256(b"package_sensitive_123").hexdigest()
    assert "package_sensitive_123" not in str(log.list(limit=10))
    assert log.verify_chain()["valid"] is True


def test_secret_like_metadata_is_rejected(tmp_path):
    log = OperatorActionLog(tmp_path / "actions.sqlite3")
    with pytest.raises(OperatorActionLogError, match="secret-like"):
        log.append(
            operator_id="operator_a",
            key_id="key_a",
            action_type="tenant.updated",
            target_type="tenant",
            target_id="tenant_a",
            metadata={"database_url": "should-not-be-recorded"},
        )


def test_tampered_action_payload_breaks_chain(tmp_path):
    path = tmp_path / "actions.sqlite3"
    log = OperatorActionLog(path)
    action = log.append(
        operator_id="operator_a",
        key_id="key_a",
        action_type="policy.activated",
        target_type="policy",
        target_id="policy_a",
        metadata={"status": "active"},
    )
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE operator_actions SET metadata_json = '{\"status\":\"tampered\"}' WHERE action_id = ?",
            (action["action_id"],),
        )
    result = log.verify_chain()
    assert result["valid"] is False
    assert result["reason"] == "action_hash_mismatch"


def test_deleted_tail_is_detected_by_stored_head(tmp_path):
    path = tmp_path / "actions.sqlite3"
    log = OperatorActionLog(path)
    log.append(operator_id="a", key_id=None, action_type="one", target_type="audit", target_id="1")
    second = log.append(operator_id="b", key_id=None, action_type="two", target_type="audit", target_id="2")
    with sqlite3.connect(path) as connection:
        connection.execute("DELETE FROM operator_actions WHERE action_id = ?", (second["action_id"],))
    result = log.verify_chain()
    assert result["valid"] is False
    assert result["reason"] == "stored_head_mismatch"


def test_tampered_stored_head_is_detected(tmp_path):
    path = tmp_path / "actions.sqlite3"
    log = OperatorActionLog(path)
    log.append(operator_id="a", key_id=None, action_type="one", target_type="audit", target_id="1")
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE operator_action_log_heads SET last_action_hash = ? WHERE stream_id = 'global'",
            ("f" * 64,),
        )
    result = log.verify_chain()
    assert result["valid"] is False
    assert result["reason"] == "stored_head_mismatch"
