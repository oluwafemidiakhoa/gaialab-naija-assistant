"""FastAPI surface for GaiaLab Naija Trust Rail."""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any, Mapping

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from src.audit_export import create_audit_package_from_store, verify_audit_package
from src.claim_extraction import extract_claims
from src.claim_reconciliation import reconcile_claims
from src.key_registry import SigningKeyRegistry, SigningKeyRegistryError
from src.neon_observability import failure_snapshot, readiness_report
from src.operator_auth import require_admin_scope
from src.receipt_signing import sign_receipt, verify_receipt_signature
from src.receipt_store import ReceiptConflictError, ReceiptStore
from src.retention_deletion import RetentionDeletionError, create_signed_deletion_plan
from src.storage_backend import (
    audit_lifecycle_store,
    neon_backend,
    operator_neon_backend,
    operator_registry,
    rate_limiter,
    receipt_store,
    retention_deletion_store,
    signing_key_registry,
    storage_mode,
    tenant_policy_store,
    tenant_registry,
)
from src.tenant_auth import require_scope
from src.tenant_policy import (
    TenantPolicyConfigurationError,
    default_policy_record,
    enforce_runtime_requirements,
    evaluate_tenant_policy,
)
from src.trust_engine import verify_interaction

API_VERSION = "v1"
app = FastAPI(
    title="GaiaLab Naija Trust API",
    version="0.9.0",
    description="Tenant-scoped AI verification with Neon Postgres production storage and SQLite local fallback.",
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
    retention_until: str | None = None


class AuditPackageRequest(BaseModel):
    package: dict[str, Any]


class AuditLifecycleEventRequest(BaseModel):
    event_type: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class RetentionCancellationRequest(BaseModel):
    reason: str | None = None


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


def _tenant_registry() -> Any:
    try:
        return tenant_registry()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def _operator_registry() -> Any:
    try:
        return operator_registry()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def _authenticate(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> dict[str, Any]:
    if not x_api_key:
        raise HTTPException(status_code=401, detail="missing X-API-Key")
    identity = _tenant_registry().authenticate(x_api_key)
    if identity is None:
        raise HTTPException(status_code=401, detail="invalid or disabled API key")
    return identity


def _authenticate_admin(
    x_admin_api_key: str | None = Header(default=None, alias="X-Admin-API-Key"),
) -> dict[str, Any]:
    if not x_admin_api_key:
        raise HTTPException(status_code=401, detail="missing X-Admin-API-Key")
    identity = _operator_registry().authenticate(x_admin_api_key)
    if identity is None:
        raise HTTPException(status_code=401, detail="invalid or disabled admin API key")
    return identity


def _authorize(identity: dict[str, Any], scope: str) -> None:
    try:
        require_scope(identity, scope)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


def _authorize_admin(identity: dict[str, Any], scope: str) -> None:
    try:
        require_admin_scope(identity, scope)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


def _apply_rate_limit(identity: dict[str, Any]) -> None:
    try:
        decision = rate_limiter().consume(
            identity["key_id"],
            limit=int(identity["rate_limit_per_minute"]),
            window_seconds=60,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not decision.allowed:
        raise HTTPException(
            status_code=429,
            detail="API key rate limit exceeded",
            headers={"Retry-After": str(max(1, decision.reset_at - int(__import__("time").time())))},
        )


def _configured_store() -> Any:
    try:
        return receipt_store(required=True)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def _configured_lifecycle() -> Any:
    try:
        return audit_lifecycle_store(required=True)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def _configured_deletion_store() -> Any:
    try:
        return retention_deletion_store(required=True)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def _configured_key_registry(required: bool = False) -> Any | None:
    try:
        return signing_key_registry(required=required)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def _active_policy(tenant_id: str) -> dict[str, Any]:
    store = tenant_policy_store(required=False)
    return store.active_for(tenant_id) if store else default_policy_record(tenant_id)


def verify_payload(
    payload: Mapping[str, Any],
    *,
    tenant_id: str | None = None,
    tenant_policy: Mapping[str, Any] | None = None,
    signing_key_b64: str | None = None,
    receipt_store_path: str | None = None,
    key_registry_path: str | None = None,
    receipt_store_backend: Any | None = None,
    key_registry_backend: Any | None = None,
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

    persistence_configured = bool(receipt_store_backend or receipt_store_path)
    policy_record = dict(tenant_policy or default_policy_record(tenant_id))
    enforce_runtime_requirements(
        policy_record,
        signing_configured=bool(signing_key_b64),
        persistence_configured=persistence_configured,
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
    registry = key_registry_backend
    if registry is None and key_registry_path:
        registry = SigningKeyRegistry(key_registry_path)
    if signature and registry:
        registry.assert_can_sign(signature["key_id"])

    receipt_envelope = {"verification_receipt": verification_receipt, "signature": signature}
    persisted = False
    store = receipt_store_backend
    if store is None and receipt_store_path:
        store = ReceiptStore(receipt_store_path)
    if store:
        persisted = store.save(
            verification_receipt["verification_id"],
            receipt_envelope,
            tenant_id=tenant_id,
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


@app.get("/live")
def live() -> dict[str, Any]:
    """Process liveness only; intentionally does not touch the database."""
    return {
        "status": "alive",
        "service": "gaialab-naija-trust-api",
        "api_version": API_VERSION,
    }


@app.get("/ready")
def ready() -> dict[str, Any]:
    """Traffic readiness: database, migrations, and runtime role safety."""
    if storage_mode() != "neon":
        return {
            "ready": True,
            "storage_mode": "sqlite",
            "database_probe": "not_applicable",
        }
    tenant = neon_backend()
    if tenant is None:
        raise HTTPException(status_code=503, detail="Neon tenant runtime is not configured")
    try:
        report = readiness_report(
            tenant_backend=tenant,
            operator_backend=operator_neon_backend(),
        )
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "ready": False,
                "reason": type(exc).__name__,
                "failures": failure_snapshot(),
            },
        ) from exc
    if not report["ready"]:
        raise HTTPException(status_code=503, detail=report)
    return report


@app.get("/health")
def health() -> dict[str, Any]:
    neon = bool(os.getenv("GAIALAB_DATABASE_URL"))
    operator_neon = bool(os.getenv("GAIALAB_OPERATOR_DATABASE_URL"))
    return {
        "status": "ok",
        "service": "gaialab-naija-trust-api",
        "api_version": API_VERSION,
        "storage_mode": storage_mode(),
        "neon_configured": neon,
        "operator_neon_configured": operator_neon,
        "tenant_auth_configured": neon or bool(os.getenv("GAIALAB_TENANT_DB")),
        "operator_auth_configured": operator_neon or bool(os.getenv("GAIALAB_OPERATOR_DB")),
        "tenant_policy_configured": neon or bool(os.getenv("GAIALAB_TENANT_POLICY_DB")),
        "rate_limit_configured": neon or bool(os.getenv("GAIALAB_RATE_LIMIT_DB") or os.getenv("GAIALAB_TENANT_DB")),
        "receipt_signing_configured": bool(os.getenv("GAIALAB_TRUST_SIGNING_KEY_B64")),
        "signing_key_registry_configured": neon or bool(os.getenv("GAIALAB_TRUST_KEY_REGISTRY_DB")),
        "receipt_store_configured": neon or bool(os.getenv("GAIALAB_TRUST_RECEIPT_DB")),
        "audit_lifecycle_configured": (neon and operator_neon) or bool(os.getenv("GAIALAB_AUDIT_LIFECYCLE_DB")),
        "retention_deletion_configured": (neon and operator_neon) or bool(os.getenv("GAIALAB_AUDIT_LIFECYCLE_DB")),
        "database_failures": failure_snapshot(),
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
            receipt_store_backend=receipt_store(required=False),
            key_registry_backend=signing_key_registry(required=False),
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
    store = _configured_store()
    try:
        package = create_audit_package_from_store(
            receipt_store=store,
            tenant_id=identity["tenant_id"],
            created_from=request.created_from,
            created_to=request.created_to,
            dispositions=request.dispositions,
            limit=request.limit,
            signing_key_b64=os.getenv("GAIALAB_TRUST_SIGNING_KEY_B64"),
        )
        lifecycle = audit_lifecycle_store(required=False)
        lifecycle_record = None
        if lifecycle:
            lifecycle_record = lifecycle.register_export(
                package,
                tenant_id=identity["tenant_id"],
                created_by_key_id=identity["key_id"],
                retention_until=request.retention_until,
            )
        return {**package, "lifecycle": lifecycle_record}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/v1/audit/verify")
def verify_audit(request: AuditPackageRequest) -> dict[str, Any]:
    return verify_audit_package(request.package)


@app.get("/v1/admin/audit/exports/{package_id}")
def admin_get_audit_export(
    package_id: str,
    identity: dict[str, Any] = Depends(_authenticate_admin),
) -> dict[str, Any]:
    _authorize_admin(identity, "audit:lifecycle")
    record = _configured_lifecycle().get(package_id)
    if record is None:
        raise HTTPException(status_code=404, detail="audit export not found")
    return record


@app.get("/v1/admin/audit/exports/{package_id}/retention")
def admin_get_retention(
    package_id: str,
    identity: dict[str, Any] = Depends(_authenticate_admin),
) -> dict[str, Any]:
    _authorize_admin(identity, "audit:lifecycle")
    try:
        return _configured_lifecycle().retention_status(package_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="audit export not found") from exc


@app.post("/v1/admin/audit/exports/{package_id}/events")
def admin_add_audit_event(
    package_id: str,
    request: AuditLifecycleEventRequest,
    identity: dict[str, Any] = Depends(_authenticate_admin),
) -> dict[str, Any]:
    _authorize_admin(identity, "audit:lifecycle")
    try:
        return _configured_lifecycle().add_event(
            package_id,
            actor_type="operator",
            actor_id=identity["operator_id"],
            event_type=request.event_type,
            metadata=request.metadata,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="audit export not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/v1/admin/audit/exports/{package_id}/deletion-plans")
def admin_create_deletion_plan(
    package_id: str,
    identity: dict[str, Any] = Depends(_authenticate_admin),
) -> dict[str, Any]:
    _authorize_admin(identity, "audit:delete")
    signing_key = os.getenv("GAIALAB_TRUST_SIGNING_KEY_B64")
    if not signing_key:
        raise HTTPException(status_code=503, detail="retention deletion requires receipt signing")
    try:
        registry = _configured_key_registry(required=True)
        key_probe = sign_receipt({"purpose": "retention-deletion-key-check"}, signing_key)
        registry.assert_can_sign(key_probe["key_id"])
        return create_signed_deletion_plan(
            authorization_store=_configured_deletion_store(),
            lifecycle_store=_configured_lifecycle(),
            package_id=package_id,
            operator_id=identity["operator_id"],
            signing_key_b64=signing_key,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="audit export not found") from exc
    except (RetentionDeletionError, SigningKeyRegistryError, ValueError, TypeError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/v1/admin/audit/deletion-plans/{plan_id}")
def admin_get_deletion_plan(
    plan_id: str,
    identity: dict[str, Any] = Depends(_authenticate_admin),
) -> dict[str, Any]:
    _authorize_admin(identity, "audit:delete")
    record = _configured_deletion_store().get(plan_id)
    if record is None:
        raise HTTPException(status_code=404, detail="deletion plan not found")
    return record


@app.post("/v1/admin/audit/deletion-plans/{plan_id}/approvals")
def admin_approve_deletion_plan(
    plan_id: str,
    identity: dict[str, Any] = Depends(_authenticate_admin),
) -> dict[str, Any]:
    _authorize_admin(identity, "audit:delete")
    try:
        return _configured_deletion_store().approve(plan_id, identity["operator_id"])
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="deletion plan not found") from exc
    except RetentionDeletionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/v1/admin/audit/deletion-plans/{plan_id}/cancel")
def admin_cancel_deletion_plan(
    plan_id: str,
    request: RetentionCancellationRequest,
    identity: dict[str, Any] = Depends(_authenticate_admin),
) -> dict[str, Any]:
    _authorize_admin(identity, "audit:delete")
    try:
        return _configured_deletion_store().cancel(
            plan_id,
            identity["operator_id"],
            reason=request.reason,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="deletion plan not found") from exc
    except RetentionDeletionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/v1/admin/audit/deletion-plans/{plan_id}/execute")
def admin_execute_deletion_plan(
    plan_id: str,
    identity: dict[str, Any] = Depends(_authenticate_admin),
) -> dict[str, Any]:
    _authorize_admin(identity, "audit:delete")
    try:
        return _configured_deletion_store().execute(plan_id, identity["operator_id"])
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="deletion plan not found") from exc
    except RetentionDeletionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


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
