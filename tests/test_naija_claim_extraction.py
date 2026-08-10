import json
from pathlib import Path

from src.claim_extraction import EXTRACTION_VERSION, extract_claims


FIXTURE = (
    Path(__file__).resolve().parent.parent
    / "evaluation"
    / "fixtures"
    / "naija_pidgin_claim_extraction_v0.1.jsonl"
)


def _cases():
    return [json.loads(line) for line in FIXTURE.read_text(encoding="utf-8").splitlines() if line.strip()]


def _normalized_conflicts(items):
    return {
        item["field"]: sorted(item["values"], key=str)
        for item in items
    }


def test_pidgin_benchmark_is_synthetic_and_not_culturally_validated():
    cases = _cases()
    assert len(cases) >= 14
    assert all(case["synthetic"] is True for case in cases)
    assert all(case["culturally_validated"] is False for case in cases)


def test_pidgin_claim_extraction_fixture_exact_matches():
    failures = []
    for case in _cases():
        result = extract_claims(case["assistant_response"])
        expected_conflicts = {
            field: sorted(values, key=str)
            for field, values in (case.get("expected_conflicts") or {}).items()
        }
        observed_conflicts = _normalized_conflicts(result["conflicts"])
        if (
            result["claims"] != case["expected_claims"]
            or observed_conflicts != expected_conflicts
            or result["required_disposition"] != case["expected_required_disposition"]
        ):
            failures.append(
                {
                    "id": case["id"],
                    "claims": result["claims"],
                    "conflicts": observed_conflicts,
                    "required_disposition": result["required_disposition"],
                }
            )
    assert failures == []


def test_extraction_version_records_pidgin_hardening():
    assert EXTRACTION_VERSION == "gaialab-naija-claim-extraction/0.2.0"


def test_negated_completion_does_not_hide_pending_claim():
    result = extract_claims("The transfer never complete; e still dey pending.")
    assert result["claims"] == {"transaction_status": "pending"}
    assert result["conflicts"] == []


def test_conflicting_pidgin_transaction_states_require_rewrite():
    result = extract_claims("The payment don fail but the transfer don enter.")
    assert "transaction_status" not in result["claims"]
    conflict = next(item for item in result["conflicts"] if item["field"] == "transaction_status")
    assert set(conflict["values"]) == {"failed", "completed"}
    assert result["required_disposition"] == "REWRITE"
