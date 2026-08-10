"""FastAPI surface for GaiaLab Naija Trust Engine."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from src.claim_reconciliation import reconcile_claims
from src.trust_engine import verify_interaction

API_VERSION = "v1"
app = FastAPI(
    title="GaiaLab Naija Trust API",
    version="0.1.0",
    description="Model-agnostic advisory verification for consequential AI interactions.",
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
    assistant_claims: dict[str, Any] = Field(default_factory=dict)


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _verification_id(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _max_disposition(base: str, reconciliation: str) -> str:
    ranks = {"ALLOW": 0, "VERIFY": 1, "REWRITE": 2, "ESCALATE": 3, "BLOCK": 4}
    return base if ranks[base] >= ranks[reconciliation] else reconciliation


def verify_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
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
    reconciliation = reconcile_claims(
        payload.get("assistant_claims") or {},
        payload.get("authoritative_state") or payload.get("business_state") or {},
        payload.get("evidence") or {},
    )
    disposition = _max_disposition(engine_result["disposition"], reconciliation["required_disposition"])
    risk_score = max(engine_result["risk_score"], reconciliation["risk_score"])

    verification_core = {
        "api_version": API_VERSION,
        "engine_receipt_id": engine_result["receipt"]["receipt_id"],
        "reconciliation_id": reconciliation["reconciliation_id"],
        "disposition": disposition,
        "risk_score": risk_score,
    }
    return {
        "api_version": API_VERSION,
        "disposition": disposition,
        "risk_score": risk_score,
        "findings": engine_result["findings"],
        "suggested_response": engine_result["suggested_response"],
        "claim_reconciliation": reconciliation,
        "trust_receipt": engine_result["receipt"],
        "verification_receipt": {
            "verification_id": _verification_id(verification_core),
            **verification_core,
        },
    }


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "gaialab-naija-trust-api", "api_version": API_VERSION}


@app.post("/v1/verify")
def verify(request: VerifyRequest) -> dict[str, Any]:
    if not request.assistant_response.strip():
        raise HTTPException(status_code=422, detail="assistant_response must not be empty")
    return verify_payload(request.model_dump())
