"""FastAPI surface for GaiaLab Naija Trust Rail."""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any, Mapping

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from src.audit_export import create_audit_package, verify_audit_package
from src.claim_extraction import extract_claims
from src.claim_reconciliation import reconcile_claims
from src.key_registry import SigningKeyRegistry, SigningKeyRegistryError
from src.rate_limit import FixedWindowRateLimiter
from src.receipt_signing import sign_receipt, verify_receipt_signature
from src.receipt_store import ReceiptConflictError, ReceiptStore
from src.tenant_auth import TenantRegistry, require_scope
from src.tenant_policy import (
    TenantPolicyConfigurationError,
    TenantPolicyStore,
    default_policy_record,
    enforce_runtime_requirements,
    evaluate_tenant_policy,
)
from src.trust_engine import verify_interaction

API_VERSION = "v1"
app = FastAPI(
    title="GaiaLab Naija Trust API",
    version="0.5.0",
    description="Tenant-scoped, policy-controlled verification and audit evidence for consequential AI interactions.",
)


class VerifyRequest(BaseModel):
    user_message: str = ""
    assistant_response: str
    model_name: str = "unknown"
    model_version: str | None = None
    language: str | None = None
    business_state: dict[str, Any] = Field(default_factory=dict)
    authoritative_state: dict[str, Any] = Field(default_factory=dict)
    evidence: dict[str, Any] = Field(default_factory=dict)
    assistant_claims: dict[str, Any] | None = None


class ReceiptEnvelopeRequest(BaseModel):
    verification_receipt: dict[str, Any]
    signature: dict[str, Any]


class AuditExportRequest(BaseModel):
    created_from: str | None = None
    created_to: str | None = None
    dispositions: list[str] | None = None
    limit: int = Field(default=10000, ge=1, le=10000)


class AuditPackageRequest(BaseModel):
    package: dict[str, Any]


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _verification_id(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _max_disposition(*values: str) -> str:
    ranks = {"ALLOW": 0, "VERIFY": 1, "REWRITE": 2, "ESCALATE": 3, "BLOCK": 4}
    return max(values, key=lambda value: ranks[value])


def _caller_claim_record(claims: Mapping[str, Any]) -> dict[str, Any]:
    core = {
        "version": "caller-supplied/0.1.0",
        "claims": dict(claims),
        "conflicts": [],
        "items": [],
        "required_disposition": "ALLOW",
        "mode": "caller_supplied",
        "advisory_only": True,
    }
    return {"extraction_id": _verification_id(core), **core}


def _tenant_registry() -> TenantRegistry:
    path = os.getenv("GAIALAB_TENANT_DB")
    if not path:
        raise HTTPException(status_code=503, detail="tenant authentication is not configured")
    return TenantRegistry(path)


def _authenticate(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> dict[str, Any]:
    if not x_api_key:
        raise HTTPException(status_code=401, detail="missing X-API-Key")
    identity = _tenant_registry().authenticate(x_api_key)
    if identity is None:
        raise HTTPException(status_code=401, detail="invalid or disabled API key")
    return identity


def _authorize(identity: dict[str, Any], scope: str) -> None:
    try:
        require_scope(identity, scope)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


def _apply_rate_limit(identity: dict[str, Any]) -> None:
    path = os.getenv("GAIALAB_RATE_LIMIT_DB")
    if not path:
        tenant_db = os.getenv("GAIALAB_TENANT_DB")
        if not tenant_db:
            raise HTTPException(status_code=503, detail="rate limiting is not configured")
        path = tenant_db + ".rate.sqlite3"
    decision = FixedWindowRateLimiter(path).consume(
        identity["key_id"],
        limit=int(identity["rate_limit_per_minute"]),
        window_seconds=60,
    )
    if not decision.allowed:
        raise HTTPException(
            status_code=429,
            detail="API key rate limit exceeded",
            headers={"Retry-After": str(max(1, decision.reset_at - int(__import__("time").time())))},
        )


def _configured_store() -> ReceiptStore:
    path = os.getenv("GAIALAB_TRUST_RECEIPT_DB")
    if not path:
        raise HTTPException(status_code=503, detail="receipt persistence is not configured")
    return ReceiptStore(path)


def _configured_key_registry(required: bool = False) -> SigningKeyRegistry | None:
    path = os.getenv("GAIALAB_TRUST_KEY_REGISTRY_DB")
    if not path:
        if required:
            raise HTTPException(status_code=503, detail="signing key registry is not configured")
        return None
    return SigningKeyRegistry(path)


def _active_policy(tenant_id: str) -> dict[str, Any]:
    path = os.getenv("GAIALAB_TENANT_POLICY_DB")
    if not path:
        return default_policy_record(tenant_id)
    return TenantPolicyStore(path).active_for(tenant_id)


def verify_payload(
    payload: Mapping[str, Any],
    *,
    tenant_id: str | None = None,
    tenant_policy: Mapping[str, Any] | None = None,
    signing_key_b64: str | None = None,
    receipt_store_path: str | None = None,
    key_registry_path: str | None = None,
) -> dict[str, Any]:
    engine_payload = {
        "user_message": payload.get("user_message", ""),
        "assistant_response": payload.get("assistant_response", ""),
        "model_name": payload.get("model_name", "unknown"),
        "model_version": payload.get("model_version"),
        "language": payload.get("language"),
        "business_state": payload.get("business_state") or payload.get("authoritative_state") or {},
        "evidence": payload.get("evidence") or {},
    }
    engine_result = verify_interaction(engine_payload)

    supplied_claims = payload.get("assistant_claims")
    if supplied_claims is None:
        claim_extraction = extract_claims(str(payload.get("assistant_response", "")))
        assistant_claims = claim_extraction["claims"]
    else:
        assistant_claims = dict(supplied_claims or {})
        claim_extraction = _caller_claim_record(assistant_claims)

    authoritative_state = payload.get("authoritative_state") or payload.get("business_state") or {}
    evidence = payload.get("evidence") or {}
    reconciliation = reconcile_claims(assistant_claims, authoritative_state, evidence)
    base_disposition = _max_disposition(
        engine_result["disposition"],
        reconciliation["required_disposition"],
        claim_extraction["required_disposition"],
    )
    extraction_risk = 45 if claim_extraction["required_disposition"] == "REWRITE" else 0
    risk_score = max(engine_result["risk_score"], reconciliation["risk_score"], extraction_risk)

    policy_record = dict(tenant_policy or default_policy_record(tenant_id))
    enforce_runtime_requirements(
        policy_record,
        signing_configured=bool(signing_key_b64),
        persistence_configured=bool(receipt_store_path),
    )
    policy_evaluation = evaluate_tenant_policy(
        policy_record,
        base_disposition=base_disposition,
        risk_score=risk_score,
        findings=engine_result["findings"],
        claims=assistant_claims,
        authoritative_state=authoritative_state,
        evidence=evidence,
    )
    disposition = policy_evaluation["final_disposition"]

    verification_core = {
        "api_version": API_VERSION,
        "tenant_id": tenant_id,
        "model_name": str(payload.get("model_name", "unknown")),
        "model_version": payload.get("model_version"),
        "language": payload.get("language"),
        "finding_codes": [str(item.get("code")) for item in engine_result["findings"] if item.get("code")],
        "tenant_policy_id": policy_evaluation["policy_id"],
        "tenant_policy_hash": policy_evaluation["policy_hash"],
        "tenant_policy_evaluation_id": policy_evaluation["evaluation_id"],
        "engine_receipt_id": engine_result["receipt"]["receipt_id"],
        "claim_extraction_id": claim_extraction["extraction_id"],
        "reconciliation_id": reconciliation["reconciliation_id"],
        "disposition": disposition,
        "risk_score": risk_score,
    }
    verification_receipt = {"verification_id": _verification_id(verification_core), **verification_core}

    signature = sign_receipt(verification_receipt, signing_key_b64) if signing_key_b64 else None
    if signature and key_registry_path:
        SigningKeyRegistry(key_registry_path).assert_can_sign(signature["key_id"])

    receipt_envelope = {"verification_receipt": verification_receipt, "signature": signature}
    persisted = False
    if receipt_store_path:
        persisted = ReceiptStore(receipt_store_path).save(
            verification_receipt["verification_id"], receipt_envelope, tenant_id=tenant_id
        )

    return {
        "api_version": API_VERSION,
        "tenant_id": tenant_id,
        "disposition": disposition,
        "risk_score": risk_score,
        "findings": engine_result["findings"],
        "suggested_response": engine_result["suggested_response"],
        "claim_extraction": claim_extraction,
        "claim_reconciliation": reconciliation,
        "tenant_policy": policy_evaluation,
        "trust_receipt": engine_result["receipt"],
        "verification_receipt": verification_receipt,
        "receipt_envelope": receipt_envelope,
        "integrity": {
            "signed": signature is not None,
            "persisted": persisted,
            "signature_algorithm": signature["algorithm"] if signature else None,
            "key_id": signature["key_id"] if signature else None,
        },
    }


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "gaialab-naija-trust-api",
        "api_version": API_VERSION,
        "tenant_auth_configured": bool(os.getenv("GAIALAB_TENANT_DB")),
        "tenant_policy_configured": bool(os.getenv("GAIALAB_TENANT_POLICY_DB")),
        "rate_limit_configured": bool(os.getenv("GAIALAB_RATE_LIMIT_DB") or os.getenv("GAIALAB_TENANT_DB")),
        "receipt_signing_configured": bool(os.getenv("GAIALAB_TRUST_SIGNING_KEY_B64")),
        "signing_key_registry_configured": bool(os.getenv("GAIALAB_TRUST_KEY_REGISTRY_DB")),
        "receipt_store_configured": bool(os.getenv("GAIALAB_TRUST_RECEIPT_DB")),
    }


@app.post("/v1/verify")
def verify(request: VerifyRequest, identity: dict[str, Any] = Depends(_authenticate)) -> dict[str, Any]:
    _authorize(identity, "verification:write")
    _apply_rate_limit(identity)
    if not request.assistant_response.strip():
        raise HTTPException(status_code=422, detail="assistant_response must not be empty")
    try:
        return verify_payload(
            request.model_dump(),
            tenant_id=identity["tenant_id"],
            tenant_policy=_active_policy(identity["tenant_id"]),
            signing_key_b64=os.getenv("GAIALAB_TRUST_SIGNING_KEY_B64"),
            receipt_store_path=os.getenv("GAIALAB_TRUST_RECEIPT_DB"),
            key_registry_path=os.getenv("GAIALAB_TRUST_KEY_REGISTRY_DB"),
        )
    except (
        ValueError,
        TypeError,
        ReceiptConflictError,
        SigningKeyRegistryError,
        TenantPolicyConfigurationError,
    ) as exc:
        raise HTTPException(status_code=503, detail=f"trust verification configuration failed: {exc}") from exc


@app.post("/v1/audit/exports")
def export_audit(request: AuditExportRequest, identity: dict[str, Any] = Depends(_authenticate)) -> dict[str, Any]:
    _authorize(identity, "audit:export")
    _apply_rate_limit(identity)
    receipt_db = os.getenv("GAIALAB_TRUST_RECEIPT_DB")
    if not receipt_db:
        raise HTTPException(status_code=503, detail="receipt persistence is not configured")
    try:
        return create_audit_package(
            receipt_store_path=receipt_db,
            tenant_id=identity["tenant_id"],
            created_from=request.created_from,
            created_to=request.created_to,
            dispositions=request.dispositions,
            limit=request.limit,
            signing_key_b64=os.getenv("GAIALAB_TRUST_SIGNING_KEY_B64"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/v1/audit/verify")
def verify_audit(request: AuditPackageRequest) -> dict[str, Any]:
    return verify_audit_package(request.package)


@app.post("/v1/receipts/verify")
def verify_receipt(request: ReceiptEnvelopeRequest) -> dict[str, Any]:
    return verify_receipt_signature(request.verification_receipt, request.signature)


@app.get("/v1/signing-keys")
def list_signing_keys() -> dict[str, Any]:
    registry = _configured_key_registry(required=True)
    return {"keys": registry.list()}


@app.get("/v1/signing-keys/{key_id}")
def get_signing_key(key_id: str) -> dict[str, Any]:
    registry = _configured_key_registry(required=True)
    record = registry.get(key_id)
    if record is None:
        raise HTTPException(status_code=404, detail="signing key not found")
    return record


@app.get("/v1/receipts/{verification_id}")
def get_receipt(verification_id: str, identity: dict[str, Any] = Depends(_authenticate)) -> dict[str, Any]:
    _authorize(identity, "receipts:read")
    _apply_rate_limit(identity)
    stored = _configured_store().get(verification_id, tenant_id=identity["tenant_id"])
    if stored is None:
        raise HTTPException(status_code=404, detail="verification receipt not found")
    return stored


@app.get("/v1/receipts/{verification_id}/verify")
def verify_stored_receipt(
    verification_id: str,
    identity: dict[str, Any] = Depends(_authenticate),
) -> dict[str, Any]:
    _authorize(identity, "receipts:read")
    _apply_rate_limit(identity)
    stored = _configured_store().get(verification_id, tenant_id=identity["tenant_id"])
    if stored is None:
        raise HTTPException(status_code=404, detail="verification receipt not found")
    signature = stored.get("signature")
    if not signature:
        return {"valid": False, "reason": "receipt_is_unsigned", "verification_id": verification_id}
    result = verify_receipt_signature(stored["verification_receipt"], signature)
    registry = _configured_key_registry(required=False)
    key_record = registry.get(signature["key_id"]) if registry else None
    key_status = key_record["status"] if key_record else None
    return {"verification_id": verification_id, "key_status": key_status, **result}
