from fastapi.testclient import TestClient

from src.claim_reconciliation import reconcile_claims
from src.trust_api import app, verify_payload


client = TestClient(app)


def test_claim_reconciliation_normalizes_status_aliases():
    result = reconcile_claims(
        {"transaction_status": "successful"},
        {"transaction_status": "completed"},
    )
    assert result["checks"][0]["status"] == "SUPPORTED"
    assert result["required_disposition"] == "ALLOW"


def test_claim_reconciliation_normalizes_ngn_amounts():
    result = reconcile_claims(
        {"amount": "NGN 250,000.00"},
        {"amount": 250000},
    )
    assert result["checks"][0]["status"] == "SUPPORTED"


def test_contradicted_transaction_status_blocks():
    result = verify_payload(
        {
            "user_message": "What happened to my transfer?",
            "assistant_response": "Your transfer was successful.",
            "authoritative_state": {"transaction_status": "pending"},
            "assistant_claims": {"transaction_status": "completed"},
        }
    )
    assert result["disposition"] == "BLOCK"
    assert result["claim_reconciliation"]["counts"]["contradicted"] == 1


def test_unsupported_high_impact_claim_requires_rewrite_or_stricter():
    result = verify_payload(
        {
            "user_message": "How much is the fee?",
            "assistant_response": "A ₦100 charge applies.",
            "assistant_claims": {"fee": 100},
        }
    )
    assert result["disposition"] in {"REWRITE", "ESCALATE", "BLOCK"}
    assert result["claim_reconciliation"]["counts"]["unsupported"] == 1


def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_verify_endpoint_returns_receipts():
    response = client.post(
        "/v1/verify",
        json={
            "user_message": "What is the transfer status?",
            "assistant_response": "The transfer is still pending.",
            "authoritative_state": {"transaction_status": "pending"},
            "assistant_claims": {"transaction_status": "pending"},
            "model_name": "example-model",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["disposition"] == "ALLOW"
    assert len(payload["trust_receipt"]["receipt_id"]) == 64
    assert len(payload["verification_receipt"]["verification_id"]) == 64


def test_verify_endpoint_rejects_empty_response():
    response = client.post(
        "/v1/verify",
        json={"assistant_response": "   "},
    )
    assert response.status_code == 422
