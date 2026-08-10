from pathlib import Path

from src.claim_extraction import extract_claims
from src.receipt_signing import generate_signing_keypair, sign_receipt, verify_receipt_signature
from src.receipt_store import ReceiptConflictError, ReceiptStore
from src.trust_api import verify_payload


def test_claim_extraction_gets_pending_status():
    result = extract_claims("Your transfer is still pending.")
    assert result["claims"]["transaction_status"] == "pending"


def test_claim_extraction_detects_conflicting_transaction_statuses():
    result = extract_claims("Your transfer is pending, but the transaction was successful.")
    assert result["required_disposition"] == "REWRITE"
    assert result["conflicts"][0]["field"] == "transaction_status"


def test_negated_success_is_not_extracted_as_completed():
    result = extract_claims("Your transfer was not successful; the transfer is still pending.")
    assert result["claims"].get("transaction_status") == "pending"


def test_signature_verifies_and_tampering_fails():
    keys = generate_signing_keypair()
    receipt = {"verification_id": "abc", "disposition": "ALLOW"}
    signature = sign_receipt(receipt, keys["private_key_b64"])
    assert verify_receipt_signature(receipt, signature)["valid"] is True

    tampered = dict(receipt)
    tampered["disposition"] = "BLOCK"
    assert verify_receipt_signature(tampered, signature)["valid"] is False


def test_receipt_store_is_append_only(tmp_path: Path):
    store = ReceiptStore(tmp_path / "receipts.sqlite3")
    envelope = {"verification_receipt": {"verification_id": "abc"}, "signature": None}
    assert store.save("abc", envelope) is True
    assert store.save("abc", envelope) is False

    changed = {"verification_receipt": {"verification_id": "abc", "risk_score": 99}, "signature": None}
    try:
        store.save("abc", changed)
    except ReceiptConflictError:
        pass
    else:
        raise AssertionError("expected append-only conflict")


def test_verify_payload_automatically_extracts_and_blocks_contradiction():
    result = verify_payload(
        {
            "assistant_response": "Your transfer was successful.",
            "authoritative_state": {"transaction_status": "pending"},
        }
    )
    assert result["claim_extraction"]["mode"] == "deterministic"
    assert result["claim_extraction"]["claims"]["transaction_status"] == "completed"
    assert result["disposition"] == "BLOCK"


def test_verify_payload_can_sign_and_persist(tmp_path: Path):
    keys = generate_signing_keypair()
    db_path = tmp_path / "receipts.sqlite3"
    result = verify_payload(
        {
            "assistant_response": "Your transfer is still pending.",
            "authoritative_state": {"transaction_status": "pending"},
        },
        signing_key_b64=keys["private_key_b64"],
        receipt_store_path=str(db_path),
    )
    assert result["integrity"]["signed"] is True
    assert result["integrity"]["persisted"] is True
    assert verify_receipt_signature(
        result["verification_receipt"],
        result["receipt_envelope"]["signature"],
    )["valid"] is True
    stored = ReceiptStore(db_path).get(result["verification_receipt"]["verification_id"])
    assert stored == result["receipt_envelope"]
