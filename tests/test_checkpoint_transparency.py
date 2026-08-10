from __future__ import annotations

import copy
import json

import pytest

from src.checkpoint_transparency import (
    GENESIS_TRANSPARENCY_HASH,
    append_transparency_record,
    create_transparency_record,
    verify_transparency_log,
    verify_transparency_record,
)
from src.operator_action_log import OperatorActionLog
from src.operator_checkpoint import create_checkpoint
from src.receipt_signing import generate_signing_keypair


def _checkpoint(tmp_path, suffix: str = "one"):
    store = OperatorActionLog(tmp_path / f"actions-{suffix}.sqlite3")
    store.append(
        operator_id="operator_test",
        key_id="admin_test",
        action_type=f"test.action.{suffix}",
        target_type="test",
        target_id=f"target-{suffix}",
        metadata={"case": suffix},
    )
    keys = generate_signing_keypair()
    package = create_checkpoint(
        store,
        keys["private_key_b64"],
        created_at=f"2026-08-10T20:00:0{1 if suffix == 'one' else 2}+00:00",
    )
    return package, keys


def test_transparency_record_is_deterministic_and_offline_verifiable(tmp_path):
    package, keys = _checkpoint(tmp_path)
    first = create_transparency_record(package, trusted_key_ids={keys["key_id"]})
    second = create_transparency_record(package, trusted_key_ids={keys["key_id"]})

    assert first == second
    result = verify_transparency_record(first, trusted_key_ids={keys["key_id"]})
    assert result["valid"] is True
    assert result["checkpoint_id"] == package["checkpoint"]["checkpoint_id"]
    assert result["key_id"] == keys["key_id"]
    assert len(result["checkpoint_package_sha256"]) == 64


def test_untrusted_checkpoint_key_is_rejected(tmp_path):
    package, _keys = _checkpoint(tmp_path)
    other = generate_signing_keypair()
    with pytest.raises(ValueError, match="not trusted"):
        create_transparency_record(package, trusted_key_ids={other["key_id"]})


def test_checkpoint_or_signature_tamper_is_rejected(tmp_path):
    package, keys = _checkpoint(tmp_path)
    record = create_transparency_record(package)

    tampered = copy.deepcopy(record)
    tampered["checkpoint"]["action_count"] += 1
    assert verify_transparency_record(tampered)["reason"] == "checkpoint_package_hash_mismatch"

    tampered_signature = copy.deepcopy(record)
    tampered_signature["signature"]["signature_b64"] = "AAAA"
    assert verify_transparency_record(tampered_signature)["reason"] == "checkpoint_package_hash_mismatch"

    assert verify_transparency_record(record, trusted_key_ids={keys["key_id"]})["valid"] is True


def test_unexpected_fields_fail_closed(tmp_path):
    package, _keys = _checkpoint(tmp_path)
    package["checkpoint"]["operator_email"] = "must-not-publish@example.com"
    with pytest.raises(ValueError, match="unsupported checkpoint fields"):
        create_transparency_record(package)


def test_append_only_log_detects_rewrite_and_duplicate(tmp_path):
    ledger = tmp_path / "transparency.jsonl"
    package, keys = _checkpoint(tmp_path, "one")
    record = create_transparency_record(package, trusted_key_ids={keys["key_id"]})
    published = append_transparency_record(
        ledger,
        record,
        trusted_key_ids={keys["key_id"]},
        appended_at="2026-08-10T20:10:00+00:00",
    )
    assert published["sequence"] == 1
    assert verify_transparency_log(
        ledger,
        trusted_key_ids={keys["key_id"]},
        expected_head_sha256=published["head_sha256"],
    )["valid"] is True

    with pytest.raises(ValueError, match="already published"):
        append_transparency_record(ledger, record, trusted_key_ids={keys["key_id"]})

    rows = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
    rows[0]["appended_at"] = "2099-01-01T00:00:00+00:00"
    ledger.write_text(json.dumps(rows[0]) + "\n", encoding="utf-8")
    result = verify_transparency_log(ledger, trusted_key_ids={keys["key_id"]})
    assert result["valid"] is False
    assert result["reason"] == "transparency_entry_hash_mismatch"


def test_pinned_head_detects_tail_truncation(tmp_path):
    ledger = tmp_path / "transparency.jsonl"
    first_package, first_keys = _checkpoint(tmp_path, "one")
    second_package, second_keys = _checkpoint(tmp_path, "two")
    trusted = {first_keys["key_id"], second_keys["key_id"]}

    first = create_transparency_record(first_package, trusted_key_ids=trusted)
    first_result = append_transparency_record(
        ledger, first, trusted_key_ids=trusted, appended_at="2026-08-10T20:10:00+00:00"
    )
    second = create_transparency_record(second_package, trusted_key_ids=trusted)
    second_result = append_transparency_record(
        ledger, second, trusted_key_ids=trusted, appended_at="2026-08-10T20:20:00+00:00"
    )
    assert first_result["head_sha256"] != second_result["head_sha256"]

    lines = ledger.read_text(encoding="utf-8").splitlines()
    ledger.write_text(lines[0] + "\n", encoding="utf-8")
    result = verify_transparency_log(
        ledger,
        trusted_key_ids=trusted,
        expected_head_sha256=second_result["head_sha256"],
    )
    assert result["valid"] is False
    assert result["reason"] == "unexpected_transparency_head"


def test_empty_log_has_deterministic_genesis_head(tmp_path):
    result = verify_transparency_log(tmp_path / "missing.jsonl")
    assert result == {
        "valid": True,
        "reason": "transparency_log_valid",
        "entry_count": 0,
        "head_sha256": GENESIS_TRANSPARENCY_HASH,
        "publication_ids": [],
        "checkpoint_ids": [],
    }
