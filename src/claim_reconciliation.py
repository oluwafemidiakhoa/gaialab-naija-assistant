"""Structured claim-to-evidence reconciliation for GaiaLab Naija Trust Engine."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from enum import Enum
import hashlib
import json
import re
from typing import Any, Mapping

RECONCILIATION_VERSION = "gaialab-naija-claims/0.1.0"


class ClaimStatus(str, Enum):
    SUPPORTED = "SUPPORTED"
    UNSUPPORTED = "UNSUPPORTED"
    CONTRADICTED = "CONTRADICTED"


@dataclass(frozen=True)
class ClaimCheck:
    field: str
    status: ClaimStatus
    claim_value: Any
    evidence_value: Any
    source: str | None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["status"] = self.status.value
        return payload


_HIGH_IMPACT_FIELDS = {
    "transaction_status",
    "refund_status",
    "reversal_status",
    "account_status",
    "restriction_status",
    "verification_status",
    "amount",
    "transaction_amount",
    "fee",
    "charge",
    "penalty",
    "expected_by",
    "eta",
    "timeline",
    "sla",
    "refund_eta_hours",
}

_STATUS_ALIASES = {
    "success": "completed",
    "successful": "completed",
    "succeeded": "completed",
    "complete": "completed",
    "processing": "pending",
    "in progress": "pending",
    "in_progress": "pending",
    "declined": "failed",
    "unsuccessful": "failed",
    "refunded": "reversed",
}

_MONEY_FIELDS = {"amount", "transaction_amount", "fee", "charge", "penalty"}
_SPACE_RE = re.compile(r"\s+")


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _sha256(payload: Any) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _normalize_money(value: Any) -> str:
    text = str(value).strip().upper().replace("NGN", "").replace("₦", "").replace(",", "").strip()
    try:
        number = Decimal(text)
    except (InvalidOperation, ValueError):
        return text.lower()
    normalized = format(number.normalize(), "f")
    return normalized.rstrip("0").rstrip(".") if "." in normalized else normalized


def _normalize(field: str, value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if field.endswith("_status") or field == "transaction_status":
        text = _SPACE_RE.sub(" ", str(value).strip().lower())
        return _STATUS_ALIASES.get(text, text)
    if field in _MONEY_FIELDS:
        return _normalize_money(value)
    if isinstance(value, (int, float, Decimal)):
        return str(value)
    if isinstance(value, str):
        return _SPACE_RE.sub(" ", value.strip().lower())
    return value


def _source_value(
    field: str,
    authoritative_state: Mapping[str, Any],
    evidence: Mapping[str, Any],
) -> tuple[bool, Any, str | None]:
    if field in authoritative_state and authoritative_state[field] not in (None, ""):
        return True, authoritative_state[field], "authoritative_state"
    if field in evidence and evidence[field] not in (None, ""):
        return True, evidence[field], "evidence"
    return False, None, None


def reconcile_claims(
    assistant_claims: Mapping[str, Any] | None,
    authoritative_state: Mapping[str, Any] | None,
    evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Compare explicit machine-readable assistant claims to supplied evidence.

    The function never infers approval. A claim is supported only when an exact
    normalized value is available in authoritative state or caller-supplied evidence.
    """

    claims = dict(assistant_claims or {})
    state = dict(authoritative_state or {})
    evidence_map = dict(evidence or {})
    checks: list[ClaimCheck] = []

    for field in sorted(claims):
        claim_value = claims[field]
        present, evidence_value, source = _source_value(field, state, evidence_map)
        if not present:
            status = ClaimStatus.UNSUPPORTED
        elif _normalize(field, claim_value) == _normalize(field, evidence_value):
            status = ClaimStatus.SUPPORTED
        else:
            status = ClaimStatus.CONTRADICTED
        checks.append(
            ClaimCheck(
                field=field,
                status=status,
                claim_value=claim_value,
                evidence_value=evidence_value,
                source=source,
            )
        )

    statuses = {check.status for check in checks}
    unsupported_high_impact = any(
        check.status is ClaimStatus.UNSUPPORTED and check.field in _HIGH_IMPACT_FIELDS
        for check in checks
    )

    if ClaimStatus.CONTRADICTED in statuses:
        required_disposition = "BLOCK"
        risk_score = 80
    elif unsupported_high_impact:
        required_disposition = "REWRITE"
        risk_score = 45
    elif ClaimStatus.UNSUPPORTED in statuses:
        required_disposition = "VERIFY"
        risk_score = 20
    else:
        required_disposition = "ALLOW"
        risk_score = 0

    reconciliation_core = {
        "version": RECONCILIATION_VERSION,
        "claims": claims,
        "authoritative_state": state,
        "evidence": evidence_map,
        "checks": [check.to_dict() for check in checks],
        "required_disposition": required_disposition,
        "risk_score": risk_score,
    }

    return {
        "reconciliation_id": _sha256(reconciliation_core),
        "version": RECONCILIATION_VERSION,
        "required_disposition": required_disposition,
        "risk_score": risk_score,
        "checks": [check.to_dict() for check in checks],
        "counts": {
            "supported": sum(check.status is ClaimStatus.SUPPORTED for check in checks),
            "unsupported": sum(check.status is ClaimStatus.UNSUPPORTED for check in checks),
            "contradicted": sum(check.status is ClaimStatus.CONTRADICTED for check in checks),
        },
    }
