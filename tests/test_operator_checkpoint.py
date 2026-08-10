from __future__ import annotations

import copy

import pytest

from src.operator_action_log import GENESIS_HASH, OperatorActionLog
from src.operator_checkpoint import create_checkpoint, verify_checkpoint, verify_checkpoint_against_log
from src.receipt_signing import generate_signing_keypair


def _append(store: OperatorActionLog, *, suffix: str) -> dict:
    return store.append(
        operator_id="operator_test",
        key_id="admin_test",
        action_type=f"test.action.{suffix}",
        target_type="test_target",
        target_id=f"target-{suffix}",
        metadata={"case": suffix},
    )


def test_empty_chain_checkpoint_is_signed_and_key_pinned(tmp_path) -> None:
    store = OperatorActionLog(tmp_path / "actions.sqlite3")
    keys = generate_signing_keypair()
    package = create_checkpoint(store, keys["private_key_b64"], created_at="2026-08-10T18:00:00+00:00")

    assert package["checkpoint"]["action_count"] == 0
    assert package["checkpoint"]["action_head_sha256"] == GENESIS_HASH
    result = verify_checkpoint(package, expected_key_id=keys["key_id"])
    assert result["valid"] is True
    assert result["key_id"] == keys["key_id"]


def test_wrong_expected_signer_is_rejected(tmp_path) -> None:
    store = OperatorActionLog(tmp_path / "actions.sqlite3")
    keys = generate_signing_keypair()
    other = generate_signing_keypair()
    package = create_checkpoint(store, keys["private_key_b64"])

    result = verify_checkpoint(package, expected_key_id=other["key_id"])
    assert result == {
        "valid": False,
        "reason": "unexpected_signing_key",
        "key_id": keys["key_id"],
    }


def test_checkpoint_matches_current_chain_and_later_becomes_valid_ancestor(tmp_path) -> None:
    store = OperatorActionLog(tmp_path / "actions.sqlite3")
    keys = generate_signing_keypair()
    first = _append(store, suffix="one")
    package = create_checkpoint(store, keys["private_key_b64"])

    current = verify_checkpoint_against_log(package, store, expected_key_id=keys["key_id"])
    assert current["valid"] is True
    assert current["reason"] == "checkpoint_matches_current_chain"
    assert current["action_head_sha256"] == first["action_hash"]

    _append(store, suffix="two")
    ancestor = verify_checkpoint_against_log(package, store, expected_key_id=keys["key_id"])
    assert ancestor["valid"] is True
    assert ancestor["reason"] == "checkpoint_is_valid_ancestor"
    assert ancestor["current_count"] == 2


def test_checkpoint_content_tamper_is_detected(tmp_path) -> None:
    store = OperatorActionLog(tmp_path / "actions.sqlite3")
    keys = generate_signing_keypair()
    _append(store, suffix="one")
    package = create_checkpoint(store, keys["private_key_b64"])

    tampered = copy.deepcopy(package)
    tampered["checkpoint"]["action_count"] = 7
    result = verify_checkpoint(tampered)
    assert result["valid"] is False
    assert result["reason"] == "checkpoint_id_mismatch"


def test_unsupported_stream_cannot_be_created_or_verified(tmp_path) -> None:
    store = OperatorActionLog(tmp_path / "actions.sqlite3")
    keys = generate_signing_keypair()
    with pytest.raises(ValueError, match="only the global"):
        create_checkpoint(store, keys["private_key_b64"], stream_id="tenant-a")

    package = create_checkpoint(store, keys["private_key_b64"])
    package["checkpoint"]["stream_id"] = "tenant-a"
    assert verify_checkpoint(package)["reason"] == "unsupported_checkpoint_stream"


def test_invalid_chain_cannot_be_checkpointed(tmp_path) -> None:
    store = OperatorActionLog(tmp_path / "actions.sqlite3")
    keys = generate_signing_keypair()
    _append(store, suffix="one")
    with store._connect() as connection:
        connection.execute("UPDATE operator_actions SET action_hash = ? WHERE event_id = 1", ("f" * 64,))
    with pytest.raises(ValueError, match="operator action chain is not valid"):
        create_checkpoint(store, keys["private_key_b64"])


class _FakeLog:
    def __init__(self, *, count: int, head: str, rows: list[dict] | None = None, valid: bool = True):
        self.count = count
        self.head = head
        self.rows = rows or []
        self.valid = valid

    def verify_chain(self) -> dict:
        if not self.valid:
            return {"valid": False, "reason": "fake_invalid"}
        return {"valid": True, "reason": "operator_action_chain_valid", "count": self.count, "head": self.head}

    def list(self, *, limit: int = 1000) -> list[dict]:
        return self.rows[:limit]


def test_valid_checkpoint_detects_later_truncation(tmp_path) -> None:
    store = OperatorActionLog(tmp_path / "actions.sqlite3")
    keys = generate_signing_keypair()
    _append(store, suffix="one")
    second = _append(store, suffix="two")
    package = create_checkpoint(store, keys["private_key_b64"])

    truncated = _FakeLog(count=1, head="a" * 64, rows=[{"action_hash": "a" * 64}])
    result = verify_checkpoint_against_log(package, truncated)
    assert result["valid"] is False
    assert result["reason"] == "operator_chain_truncated_since_checkpoint"
    assert package["checkpoint"]["action_head_sha256"] == second["action_hash"]


def test_valid_checkpoint_detects_same_length_rewrite(tmp_path) -> None:
    store = OperatorActionLog(tmp_path / "actions.sqlite3")
    keys = generate_signing_keypair()
    _append(store, suffix="one")
    package = create_checkpoint(store, keys["private_key_b64"])

    rewritten = _FakeLog(count=1, head="b" * 64, rows=[{"action_hash": "b" * 64}])
    result = verify_checkpoint_against_log(package, rewritten)
    assert result["valid"] is False
    assert result["reason"] == "operator_chain_rewritten_since_checkpoint"


def test_valid_checkpoint_detects_historical_prefix_rewrite(tmp_path) -> None:
    store = OperatorActionLog(tmp_path / "actions.sqlite3")
    keys = generate_signing_keypair()
    _append(store, suffix="one")
    package = create_checkpoint(store, keys["private_key_b64"])

    rewritten_history = _FakeLog(
        count=2,
        head="d" * 64,
        rows=[{"action_hash": "c" * 64}, {"action_hash": "d" * 64}],
    )
    result = verify_checkpoint_against_log(package, rewritten_history)
    assert result["valid"] is False
    assert result["reason"] == "operator_chain_history_rewritten_since_checkpoint"
