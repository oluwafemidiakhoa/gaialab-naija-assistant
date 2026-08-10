from src.trust_engine import Disposition, Interaction, TrustEngine, verify_interaction


def test_allows_non_consequential_supported_response():
    result = TrustEngine().verify(
        Interaction(
            user_message="Help me write a polite greeting.",
            assistant_response="Good afternoon. How may I assist you today?",
            model_name="example-model",
        )
    )
    assert result.disposition is Disposition.ALLOW
    assert result.risk_score == 0
    assert result.findings == ()


def test_blocks_unsupported_refund_and_timeline_promise():
    result = TrustEngine().verify(
        Interaction(
            user_message="My transfer did not arrive. When will I get it back?",
            assistant_response="Your refund will be returned to your account within 24 hours.",
            model_name="example-model",
        )
    )
    codes = {finding.code for finding in result.findings}
    assert result.disposition is Disposition.BLOCK
    assert "UNSUPPORTED_REFUND_OR_REVERSAL" in codes
    assert "UNSUPPORTED_TIMELINE" in codes


def test_accepts_refund_language_when_authoritative_state_and_timeline_exist():
    result = TrustEngine().verify(
        Interaction(
            user_message="When will I get it back?",
            assistant_response="The transaction is reversed and the refund is expected within 24 hours.",
            business_state={
                "transaction_status": "reversed",
                "refund_status": "initiated",
                "expected_by": "2026-08-10T21:00:00-05:00",
            },
        )
    )
    codes = {finding.code for finding in result.findings}
    assert "UNSUPPORTED_REFUND_OR_REVERSAL" not in codes
    assert "UNSUPPORTED_TIMELINE" not in codes
    assert "TRANSACTION_STATE_CONTRADICTION" not in codes


def test_pending_status_does_not_authorize_refund_claim():
    result = TrustEngine().verify(
        Interaction(
            user_message="Will it come back?",
            assistant_response="Your refund will be processed.",
            business_state={"transaction_status": "pending"},
        )
    )
    assert any(f.code == "UNSUPPORTED_REFUND_OR_REVERSAL" for f in result.findings)


def test_blocks_transaction_state_contradiction():
    result = TrustEngine().verify(
        Interaction(
            user_message="Did the transfer go through?",
            assistant_response="Yes, the transfer was successful.",
            business_state={"transaction_status": "pending"},
        )
    )
    assert result.disposition is Disposition.BLOCK
    assert any(f.code == "TRANSACTION_STATE_CONTRADICTION" for f in result.findings)


def test_receipt_id_is_content_stable_and_does_not_expose_evidence_values():
    payload = {
        "user_message": "What is the transaction status?",
        "assistant_response": "The transfer is still processing.",
        "model_name": "model-a",
        "business_state": {"transaction_status": "pending", "customer_phone": "+2348000000000"},
        "evidence": {"ledger_reference": "SECRET-REFERENCE-123"},
    }
    first = verify_interaction(payload)
    second = verify_interaction(payload)
    assert first["receipt"]["receipt_id"] == second["receipt"]["receipt_id"]
    receipt_text = str(first["receipt"])
    assert "SECRET-REFERENCE-123" not in receipt_text
    assert "+2348000000000" not in receipt_text
    assert "ledger_reference" in first["receipt"]["evidence_keys"]
    assert "customer_phone" in first["receipt"]["business_state_keys"]
