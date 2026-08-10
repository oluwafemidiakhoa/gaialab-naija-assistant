"""FastAPI surface for GaiaLab Naija Trust Rail."""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any, Mapping

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from src.claim_extraction import extract_claims
from src.claim_reconciliation import reconcile_claims
from src.key_registry import SigningKeyRegistry, SigningKeyRegistryError
from src.receipt_signing import sign_receipt, verify_receipt_signature
from src.receipt_store import ReceiptConflictError, ReceiptStore
from src.tenant_auth import TenantRegistry
from src.trust_engine import verify_interaction

API_VERSION = "v1"
app = FastAPI(
    title="GaiaLab Naija Trust API",
    version="0.3.0",
    description="Tenant-scoped, model-agnostic advisory verification for consequential AI interactions.",
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


def verify_payload(
    payload: Mapping[str, Any],
    *,
    tenant_id: str | None = None,
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

    reconciliation = reconcile_claims(
        assistant_claims,
        payload.get("authoritative_state") or payload.get("business_state") or {},
        payload.get("evidence") or {},
    )
    disposition = _max_disposition(
        engine_result["disposition"],
        reconciliation["required_disposition"],
        claim_extraction["required_disposition"],
    )
    extraction_risk = 45 if claim_extraction["required_disposition"] == "REWRITE" else 0
    risk_score = max(engine_result["risk_score"], reconciliation["risk_score"], extraction_risk)

    verification_core = {
        "api_version": API_VERSION,
        "tenant_id": tenant_id,
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
        "receipt_signing_configured": bool(os.getenv("GAIALAB_TRUST_SIGNING_KEY_B64")),
        "signing_key_registry_configured": bool(os.getenv("GAIALAB_TRUST_KEY_REGISTRY_DB")),
        "receipt_store_configured": bool(os.getenv("GAIALAB_TRUST_RECEIPT_DB")),
    }


@app.post("/v1/verify")
def verify(request: VerifyRequest, identity: dict[str, Any] = Depends(_authenticate)) -> dict[str, Any]:
    if not request.assistant_response.strip():
        raise HTTPException(status_code=422, detail="assistant_response must not be empty")
    try:
        return verify_payload(
            request.model_dump(),
            tenant_id=identity["tenant_id"],
            signing_key_b64=os.getenv("GAIALAB_TRUST_SIGNING_KEY_B64"),
            receipt_store_path=os.getenv("GAIALAB_TRUST_RECEIPT_DB"),
            key_registry_path=os.getenv("GAIALAB_TRUST_KEY_REGISTRY_DB"),
        )
    except (ValueError, TypeError, ReceiptConflictError, SigningKeyRegistryError) as exc:
        raise HTTPException(status_code=500, detail=f"trust receipt processing failed: {exc}") from exc


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
    stored = _configured_store().get(verification_id, tenant_id=identity["tenant_id"])
    if stored is None:
        raise HTTPException(status_code=404, detail="verification receipt not found")
    return stored


@app.get("/v1/receipts/{verification_id}/verify")
def verify_stored_receipt(
    verification_id: str,
    identity: dict[str, Any] = Depends(_authenticate),
) -> dict[str, Any]:
    stored = _configured_store().get(verification_id, tenant_id=identity["tenant_id"])
    if stored is None:
        raise HTTPException(status_code=404, detail="verification receipt not found")
    signature = stored.get("signature")
    if not signature:
        return {"valid": False, "reason": "receipt_is_unsigned", "verification_id": verification_id}
    result = verify_receipt_signature(stored["verification_receipt"], signature)
    registry = _configured_key_registry(required=False)
    key_status = registry.get(signature["key_id"])["status"] if registry and registry.get(signature["key_id"]) else None
    return {"verification_id": verification_id, "key_status": key_status, **result}
