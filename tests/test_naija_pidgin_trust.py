import json
from pathlib import Path

from src.trust_api import verify_payload


FIXTURE = (
    Path(__file__).resolve().parent.parent
    / "evaluation"
    / "fixtures"
    / "naija_pidgin_trust_v0.1.jsonl"
)


def _cases():
    return [json.loads(line) for line in FIXTURE.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_pidgin_trust_fixture_is_synthetic_and_not_culturally_validated():
    cases = _cases()
    assert len(cases) >= 8
    assert all(case["synthetic"] is True for case in cases)
    assert all(case["culturally_validated"] is False for case in cases)


def test_pidgin_trust_end_to_end_without_caller_supplied_claims():
    failures = []
    for case in _cases():
        payload = {
            "user_message": case["user_message"],
            "assistant_response": case["assistant_response"],
            "authoritative_state": case.get("authoritative_state") or {},
            "evidence": case.get("evidence") or {},
            "language": case["language"],
            "model_name": "benchmark-model",
        }
        result = verify_payload(payload)
        checks = result["claim_reconciliation"]["checks"]
        observed_status = checks[0]["status"] if checks else None
        observed = {
            "claims": result["claim_extraction"]["claims"],
            "disposition": result["disposition"],
            "claim_status": observed_status,
        }
        expected = {
            "claims": case["expected_extracted_claims"],
            "disposition": case["expected_disposition"],
            "claim_status": case["expected_claim_status"],
        }
        if observed != expected:
            failures.append({"id": case["id"], "observed": observed, "expected": expected})
    assert failures == []
