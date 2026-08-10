"""Deterministic, model-agnostic trust verification for GaiaLab Naija.

The engine is advisory runtime safety infrastructure. It never mutates governed
human-review state and never converts an automated finding into human approval.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import re
from typing import Any, Mapping, Sequence

POLICY_VERSION = "gaialab-naija-trust/0.1.0"


class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Disposition(str, Enum):
    ALLOW = "ALLOW"
    VERIFY = "VERIFY"
    REWRITE = "REWRITE"
    ESCALATE = "ESCALATE"
    BLOCK = "BLOCK"


@dataclass(frozen=True)
class Interaction:
    user_message: str
    assistant_response: str
    model_name: str = "unknown"
    model_version: str | None = None
    language: str | None = None
    business_state: Mapping[str, Any] = field(default_factory=dict)
    evidence: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Finding:
    code: str
    severity: Severity
    reason: str
    claim_text: str | None = None
    evidence_keys: tuple[str, ...] = ()


@dataclass(frozen=True)
class TrustReceipt:
    receipt_id: str
    policy_version: str
    created_at: str
    model_name: str
    model_version: str | None
    language: str | None
    input_hash: str
    response_hash: str
    evidence_keys: tuple[str, ...]
    business_state_keys: tuple[str, ...]
    finding_codes: tuple[str, ...]
    risk_score: int
    disposition: Disposition

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["disposition"] = self.disposition.value
        return payload


@dataclass(frozen=True)
class VerificationResult:
    disposition: Disposition
    risk_score: int
    findings: tuple[Finding, ...]
    suggested_response: str | None
    receipt: TrustReceipt

    def to_dict(self) -> dict[str, Any]:
        return {
            "disposition": self.disposition.value,
            "risk_score": self.risk_score,
            "findings": [
                {
                    **asdict(finding),
                    "severity": finding.severity.value,
                }
                for finding in self.findings
            ],
            "suggested_response": self.suggested_response,
            "receipt": self.receipt.to_dict(),
        }


_SEVERITY_WEIGHT = {
    Severity.LOW: 10,
    Severity.MEDIUM: 20,
    Severity.HIGH: 35,
    Severity.CRITICAL: 70,
}

_REFUND_RE = re.compile(
    r"\b(refund(?:ed)?|reversal|reversed|return(?:ed)?\s+(?:to|into)\s+(?:your\s+)?account)\b",
    re.IGNORECASE,
)
_TIMELINE_RE = re.compile(
    r"\b(?:within\s+\d+\s+(?:minutes?|hours?|days?)|in\s+\d+\s+(?:minutes?|hours?|days?)|"
    r"today|tomorrow|tonight|by\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)|"
    r"by\s+\d{1,2}(?::\d{2})?\s*(?:am|pm))\b",
    re.IGNORECASE,
)
_TIMELINE_CONTEXT_RE = re.compile(
    r"\b(?:arriv(?:e|es)|receiv(?:e|ed)|refund(?:ed)?|revers(?:e|ed)|complet(?:e|ed)|resolv(?:e|ed)|"
    r"credit(?:ed)?|deliver(?:ed)?|process(?:ed)?|return(?:ed)?|restor(?:e|ed)|unblock(?:ed)?|reactivat(?:e|ed))\b",
    re.IGNORECASE,
)
_ACCOUNT_ACTION_RE = re.compile(
    r"\b(?:your\s+)?account\s+(?:has\s+been|is|will\s+be)\s+"
    r"(?:blocked|unblocked|closed|restricted|suspended|verified|reactivated|frozen|unfrozen)\b",
    re.IGNORECASE,
)
_FEE_RE = re.compile(
    r"\b(?:fee|charge|penalty|levy)\b|(?:₦|NGN\s*)\d[\d,]*(?:\.\d+)?",
    re.IGNORECASE,
)
_CERTAINTY_RE = re.compile(r"\b(?:definitely|guaranteed|certainly|100%|for sure)\b", re.IGNORECASE)

_STATUS_TERMS = {
    "pending": re.compile(r"\b(?:pending|processing|still processing)\b", re.IGNORECASE),
    "completed": re.compile(r"\b(?:completed|successful|succeeded|went through)\b", re.IGNORECASE),
    "failed": re.compile(r"\b(?:failed|declined|unsuccessful)\b", re.IGNORECASE),
    "reversed": re.compile(r"\b(?:reversed|refunded|returned)\b", re.IGNORECASE),
}
_STATUS_CONTRADICTIONS = {
    "pending": {"completed", "failed", "reversed"},
    "completed": {"pending", "failed", "reversed"},
    "failed": {"completed", "pending"},
    "reversed": {"pending", "completed", "failed"},
}


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _present(mapping: Mapping[str, Any], keys: Sequence[str]) -> tuple[str, ...]:
    return tuple(sorted(key for key in keys if mapping.get(key) not in (None, "", [], {})))


def _normalize_status(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    aliases = {
        "success": "completed",
        "successful": "completed",
        "succeeded": "completed",
        "complete": "completed",
        "processing": "pending",
        "in_progress": "pending",
        "in progress": "pending",
        "declined": "failed",
        "refunded": "reversed",
    }
    return aliases.get(text, text if text in _STATUS_TERMS else None)


class TrustEngine:
    """Run deterministic trust checks against an AI interaction."""

    def verify(self, interaction: Interaction) -> VerificationResult:
        findings = list(self._evaluate(interaction))
        risk_score = min(100, sum(_SEVERITY_WEIGHT[f.severity] for f in findings))
        disposition = self._disposition(findings, risk_score)
        suggested_response = self._safe_rewrite(findings) if disposition in {
            Disposition.REWRITE,
            Disposition.ESCALATE,
            Disposition.BLOCK,
        } else None
        receipt = self._receipt(interaction, findings, risk_score, disposition)
        return VerificationResult(
            disposition=disposition,
            risk_score=risk_score,
            findings=tuple(findings),
            suggested_response=suggested_response,
            receipt=receipt,
        )

    def _evaluate(self, interaction: Interaction) -> Sequence[Finding]:
        response = interaction.assistant_response.strip()
        state = interaction.business_state
        evidence = interaction.evidence
        findings: list[Finding] = []

        if not response:
            findings.append(
                Finding(
                    code="EMPTY_RESPONSE",
                    severity=Severity.MEDIUM,
                    reason="The assistant response is empty.",
                )
            )
            return findings

        refund_keys = _present(state, ("refund_status", "reversal_status")) + _present(
            evidence, ("refund_status", "reversal_status")
        )
        known_transaction_status = _normalize_status(
            state.get("transaction_status") or evidence.get("transaction_status")
        )
        if known_transaction_status == "reversed":
            refund_keys = refund_keys + ("transaction_status",)
        refund_match = _REFUND_RE.search(response)
        if refund_match and not refund_keys:
            findings.append(
                Finding(
                    code="UNSUPPORTED_REFUND_OR_REVERSAL",
                    severity=Severity.CRITICAL,
                    reason="The response states or promises a refund/reversal without supporting refund/reversal state.",
                    claim_text=refund_match.group(0),
                )
            )

        timeline_keys = _present(state, ("expected_by", "eta", "timeline", "sla")) + _present(
            evidence, ("expected_by", "eta", "timeline", "sla")
        )
        timeline_match = _TIMELINE_RE.search(response)
        timeline_is_consequential = bool(timeline_match and _TIMELINE_CONTEXT_RE.search(response))
        if timeline_is_consequential and not timeline_keys:
            findings.append(
                Finding(
                    code="UNSUPPORTED_TIMELINE",
                    severity=Severity.HIGH,
                    reason="The response gives a concrete timeline without supporting ETA/SLA evidence.",
                    claim_text=timeline_match.group(0),
                )
            )

        account_keys = _present(state, ("account_status", "restriction_status", "verification_status")) + _present(
            evidence, ("account_status", "restriction_status", "verification_status")
        )
        account_match = _ACCOUNT_ACTION_RE.search(response)
        if account_match and not account_keys:
            findings.append(
                Finding(
                    code="UNSUPPORTED_ACCOUNT_ACTION",
                    severity=Severity.CRITICAL,
                    reason="The response asserts an account action or state without supporting account evidence.",
                    claim_text=account_match.group(0),
                )
            )

        fee_keys = _present(state, ("fee", "fees", "charge", "penalty")) + _present(
            evidence, ("fee", "fees", "charge", "penalty")
        )
        fee_match = _FEE_RE.search(response)
        if fee_match and not fee_keys:
            findings.append(
                Finding(
                    code="UNSUPPORTED_FEE_OR_AMOUNT",
                    severity=Severity.HIGH,
                    reason="The response introduces a fee, charge, penalty, or monetary amount without supporting evidence.",
                    claim_text=fee_match.group(0),
                )
            )

        known_status = known_transaction_status
        if known_status:
            contradicted = _STATUS_CONTRADICTIONS.get(known_status, set())
            for claimed_status in sorted(contradicted):
                match = _STATUS_TERMS[claimed_status].search(response)
                if match:
                    findings.append(
                        Finding(
                            code="TRANSACTION_STATE_CONTRADICTION",
                            severity=Severity.CRITICAL,
                            reason=(
                                f"Known transaction status is '{known_status}', but the response states "
                                f"a contradictory '{claimed_status}' status."
                            ),
                            claim_text=match.group(0),
                            evidence_keys=("transaction_status",),
                        )
                    )
                    break

        certainty_match = _CERTAINTY_RE.search(response)
        if certainty_match and not state and not evidence:
            findings.append(
                Finding(
                    code="UNSUPPORTED_CERTAINTY",
                    severity=Severity.MEDIUM,
                    reason="The response uses absolute certainty without any supplied evidence or business state.",
                    claim_text=certainty_match.group(0),
                )
            )

        return findings

    @staticmethod
    def _disposition(findings: Sequence[Finding], risk_score: int) -> Disposition:
        if any(f.severity is Severity.CRITICAL for f in findings):
            return Disposition.BLOCK
        if risk_score >= 70:
            return Disposition.ESCALATE
        if risk_score >= 40:
            return Disposition.REWRITE
        if risk_score >= 20:
            return Disposition.VERIFY
        return Disposition.ALLOW

    @staticmethod
    def _safe_rewrite(findings: Sequence[Finding]) -> str:
        categories: list[str] = []
        codes = {finding.code for finding in findings}
        if "UNSUPPORTED_REFUND_OR_REVERSAL" in codes:
            categories.append("a refund or reversal")
        if "UNSUPPORTED_TIMELINE" in codes:
            categories.append("a completion timeline")
        if "UNSUPPORTED_ACCOUNT_ACTION" in codes:
            categories.append("an account action or status")
        if "UNSUPPORTED_FEE_OR_AMOUNT" in codes:
            categories.append("a fee or monetary amount")
        if "TRANSACTION_STATE_CONTRADICTION" in codes:
            categories.append("the transaction status")
        if not categories:
            categories.append("the requested outcome")
        joined = ", ".join(categories[:-1]) + (" and " if len(categories) > 1 else "") + categories[-1]
        return (
            f"I can help with this, but I cannot safely confirm {joined} from the information available. "
            "Please verify the authoritative transaction/account record or escalate to an authorized support agent "
            "before making a promise to the customer."
        )

    @staticmethod
    def _receipt(
        interaction: Interaction,
        findings: Sequence[Finding],
        risk_score: int,
        disposition: Disposition,
    ) -> TrustReceipt:
        evidence_keys = tuple(sorted(str(key) for key in interaction.evidence.keys()))
        state_keys = tuple(sorted(str(key) for key in interaction.business_state.keys()))
        response_hash = _sha256_text(interaction.assistant_response)
        input_hash = _sha256_text(
            _canonical_json(
                {
                    "user_message": interaction.user_message,
                    "assistant_response": interaction.assistant_response,
                    "model_name": interaction.model_name,
                    "model_version": interaction.model_version,
                    "language": interaction.language,
                    "business_state": interaction.business_state,
                    "evidence": interaction.evidence,
                }
            )
        )
        receipt_core = {
            "policy_version": POLICY_VERSION,
            "model_name": interaction.model_name,
            "model_version": interaction.model_version,
            "language": interaction.language,
            "input_hash": input_hash,
            "response_hash": response_hash,
            "evidence_keys": evidence_keys,
            "business_state_keys": state_keys,
            "finding_codes": tuple(f.code for f in findings),
            "risk_score": risk_score,
            "disposition": disposition.value,
        }
        receipt_id = _sha256_text(_canonical_json(receipt_core))
        return TrustReceipt(
            receipt_id=receipt_id,
            policy_version=POLICY_VERSION,
            created_at=datetime.now(timezone.utc).isoformat(),
            model_name=interaction.model_name,
            model_version=interaction.model_version,
            language=interaction.language,
            input_hash=input_hash,
            response_hash=response_hash,
            evidence_keys=evidence_keys,
            business_state_keys=state_keys,
            finding_codes=tuple(f.code for f in findings),
            risk_score=risk_score,
            disposition=disposition,
        )


def verify_interaction(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Convenience JSON-compatible entry point for API/CLI adapters."""
    interaction = Interaction(
        user_message=str(payload.get("user_message", "")),
        assistant_response=str(payload.get("assistant_response", "")),
        model_name=str(payload.get("model_name", "unknown")),
        model_version=payload.get("model_version"),
        language=payload.get("language"),
        business_state=payload.get("business_state") or {},
        evidence=payload.get("evidence") or {},
    )
    return TrustEngine().verify(interaction).to_dict()
