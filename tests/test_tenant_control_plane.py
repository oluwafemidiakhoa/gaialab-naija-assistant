import os
import tempfile

from src.rate_limit import FixedWindowRateLimiter
from src.tenant_auth import TenantRegistry, require_scope
from src.tenant_policy import (
    TenantPolicyConfigurationError,
    TenantPolicyStore,
    enforce_runtime_requirements,
    evaluate_tenant_policy,
)
from src.trust_api import verify_payload


def test_api_key_scopes_and_rate_limit_metadata():
    with tempfile.TemporaryDirectory() as directory:
        registry = TenantRegistry(os.path.join(directory, "tenants.sqlite3"))
        tenant = registry.create_tenant("Scoped Bank")
        issued = registry.issue_api_key(
            tenant["tenant_id"],
            scopes=["verification:write"],
            rate_limit_per_minute=2,
        )
        identity = registry.authenticate(issued["api_key"])
        assert identity["scopes"] == ["verification:write"]
        assert identity["rate_limit_per_minute"] == 2
        require_scope(identity, "verification:write")
        try:
            require_scope(identity, "receipts:read")
            assert False, "missing scope must be rejected"
        except PermissionError:
            pass


def test_fixed_window_rate_limiter_is_deterministic():
    with tempfile.TemporaryDirectory() as directory:
        limiter = FixedWindowRateLimiter(os.path.join(directory, "rate.sqlite3"))
        assert limiter.consume("key-a", limit=2, now=120).allowed is True
        second = limiter.consume("key-a", limit=2, now=121)
        assert second.allowed is True
        assert second.remaining == 0
        denied = limiter.consume("key-a", limit=2, now=122)
        assert denied.allowed is False
        assert denied.reset_at == 180
        assert limiter.consume("key-a", limit=2, now=180).allowed is True


def test_tenant_policy_versions_are_immutable_and_activatable():
    with tempfile.TemporaryDirectory() as directory:
        store = TenantPolicyStore(os.path.join(directory, "policies.sqlite3"))
        tenant_id = "tenant_example"
        first = store.create_version(
            tenant_id,
            {"name": "standard", "max_automated_risk": 40},
        )
        second = store.create_version(
            tenant_id,
            {
                "name": "high-value",
                "max_automated_risk": 20,
                "require_human_review_above_ngn": 500000,
            },
            activate=False,
        )
        assert store.active_for(tenant_id)["policy_id"] == first["policy_id"]
        store.activate(tenant_id, second["policy_id"], note="production rollout")
        assert store.active_for(tenant_id)["policy_id"] == second["policy_id"]
        assert len(store.list_versions(tenant_id)) == 2


def test_tenant_policy_can_only_make_global_result_stricter():
    policy = {
        "policy_id": "policy_test",
        "policy_hash": "hash",
        "policy": {
            "name": "bank-policy",
            "max_automated_risk": 20,
            "require_human_review_above_ngn": 500000,
            "block_finding_codes": [],
            "escalate_finding_codes": [],
            "require_signed_receipts": False,
            "require_persisted_receipts": False,
        },
    }
    high_value = evaluate_tenant_policy(
        policy,
        base_disposition="ALLOW",
        risk_score=0,
        findings=[],
        claims={"amount": 750000},
        authoritative_state={"amount": 750000},
        evidence={},
    )
    assert high_value["final_disposition"] == "ESCALATE"

    already_blocked = evaluate_tenant_policy(
        policy,
        base_disposition="BLOCK",
        risk_score=80,
        findings=[],
        claims={},
        authoritative_state={},
        evidence={},
    )
    assert already_blocked["final_disposition"] == "BLOCK"


def test_required_receipt_infrastructure_fails_closed():
    policy = {
        "policy": {
            "name": "strict",
            "require_signed_receipts": True,
            "require_persisted_receipts": True,
        }
    }
    try:
        enforce_runtime_requirements(
            policy,
            signing_configured=False,
            persistence_configured=False,
        )
        assert False, "missing required integrity infrastructure must fail closed"
    except TenantPolicyConfigurationError:
        pass


def test_verify_payload_records_tenant_policy_in_receipt():
    result = verify_payload(
        {
            "assistant_response": "The transfer is still pending.",
            "authoritative_state": {"transaction_status": "pending", "amount": 750000},
            "assistant_claims": {"transaction_status": "pending", "amount": 750000},
        },
        tenant_id="tenant_bank",
        tenant_policy={
            "policy_id": "policy_bank_v1",
            "policy_hash": "policyhash",
            "policy": {
                "name": "bank-v1",
                "require_human_review_above_ngn": 500000,
            },
        },
    )
    assert result["disposition"] == "ESCALATE"
    assert result["tenant_policy"]["policy_id"] == "policy_bank_v1"
    assert result["verification_receipt"]["tenant_policy_id"] == "policy_bank_v1"
