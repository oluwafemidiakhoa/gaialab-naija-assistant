"""Deterministic typed claim extraction for GaiaLab Naija Trust Engine.

This module extracts a deliberately narrow set of consequential fintech/customer
support claims from candidate assistant responses. Extraction is advisory and
never constitutes evidence, approval, or a business-state mutation.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import re
from typing import Any

EXTRACTION_VERSION = "gaialab-naija-claim-extraction/0.1.0"


@dataclass(frozen=True)
class ExtractedClaim:
    field: str
    value: Any
    claim_text: str
    confidence: float
    extractor: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _sha256(payload: Any) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


_TRANSACTION_STATUS_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("pending", re.compile(r"\b(?:transfer|transaction|payment)\b.{0,30}\b(?:is|was|remains?|still)\b.{0,12}\b(?:pending|processing)\b", re.IGNORECASE)),
    ("completed", re.compile(r"\b(?:transfer|transaction|payment)\b.{0,30}\b(?:is|was|has been)\b.{0,12}\b(?:successful|completed|succeeded)\b", re.IGNORECASE)),
    ("failed", re.compile(r"\b(?:transfer|transaction|payment)\b.{0,30}\b(?:is|was|has been)\b.{0,12}\b(?:failed|declined|unsuccessful)\b", re.IGNORECASE)),
    ("reversed", re.compile(r"\b(?:transfer|transaction|payment)\b.{0,30}\b(?:is|was|has been)\b.{0,12}\b(?:reversed|refunded|returned)\b", re.IGNORECASE)),
)

_REFUND_STATUS_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("pending", re.compile(r"\b(?:refund|reversal)\b.{0,24}\b(?:is|remains?|still)\b.{0,12}\b(?:pending|processing)\b", re.IGNORECASE)),
    ("completed", re.compile(r"\b(?:refund|reversal)\b.{0,24}\b(?:is|was|has been)\b.{0,12}\b(?:completed|processed|successful)\b", re.IGNORECASE)),
    ("reversed", re.compile(r"\b(?:refund|reversal)\b.{0,24}\b(?:has been|was|is)\b.{0,12}\b(?:reversed|refunded|returned)\b", re.IGNORECASE)),
)

_ACCOUNT_STATUS_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("blocked", re.compile(r"\b(?:your\s+)?account\b.{0,16}\b(?:is|was|has been|will be)\b.{0,8}\bblocked\b", re.IGNORECASE)),
    ("restricted", re.compile(r"\b(?:your\s+)?account\b.{0,16}\b(?:is|was|has been|will be)\b.{0,8}\brestricted\b", re.IGNORECASE)),
    ("suspended", re.compile(r"\b(?:your\s+)?account\b.{0,16}\b(?:is|was|has been|will be)\b.{0,8}\bsuspended\b", re.IGNORECASE)),
    ("frozen", re.compile(r"\b(?:your\s+)?account\b.{0,16}\b(?:is|was|has been|will be)\b.{0,8}\bfrozen\b", re.IGNORECASE)),
    ("unblocked", re.compile(r"\b(?:your\s+)?account\b.{0,16}\b(?:is|was|has been|will be)\b.{0,8}\bunblocked\b", re.IGNORECASE)),
    ("reactivated", re.compile(r"\b(?:your\s+)?account\b.{0,16}\b(?:is|was|has been|will be)\b.{0,8}\breactivated\b", re.IGNORECASE)),
    ("verified", re.compile(r"\b(?:your\s+)?account\b.{0,16}\b(?:is|was|has been|will be)\b.{0,8}\bverified\b", re.IGNORECASE)),
)

_MONEY_RE = re.compile(r"(?P<currency>NGN\s*|₦\s*)(?P<amount>\d[\d,]*(?:\.\d{1,2})?)", re.IGNORECASE)
_FEE_CONTEXT_RE = re.compile(r"\b(?:fee|charge|penalty|levy)\b", re.IGNORECASE)
_TRANSACTION_AMOUNT_CONTEXT_RE = re.compile(r"\b(?:sent|send|transfer(?:red)?|transaction|payment|amount)\b", re.IGNORECASE)
_REFUND_ETA_HOURS_RE = re.compile(
    r"\b(?:refund|reversal|money|funds?)\b.{0,45}\bwithin\s+(?P<hours>\d+)\s+hours?\b",
    re.IGNORECASE,
)
_REFUND_ETA_DAYS_RE = re.compile(
    r"\b(?:refund|reversal|money|funds?)\b.{0,45}\bwithin\s+(?P<days>\d+)\s+days?\b",
    re.IGNORECASE,
)
_ETA_RE = re.compile(r"\b(?:arrive|delivered|completed|processed|resolved)\b.{0,35}\b(?:today|tomorrow|tonight)\b", re.IGNORECASE)
_NEGATION_RE = re.compile(r"\b(?:not|isn't|isnt|wasn't|wasnt|hasn't|hasnt|won't|wont|cannot|can't|cant)\b", re.IGNORECASE)


def _is_negated(text: str, start: int) -> bool:
    prefix = text[max(0, start - 24):start]
    prefix = re.split(r"[.;!?]", prefix)[-1]
    return bool(_NEGATION_RE.search(prefix))


def _add_status_claims(
    response: str,
    field: str,
    patterns: tuple[tuple[str, re.Pattern[str]], ...],
    items: list[ExtractedClaim],
) -> None:
    for value, pattern in patterns:
        for match in pattern.finditer(response):
            if _is_negated(response, match.start()) or _NEGATION_RE.search(match.group(0)):
                continue
            items.append(
                ExtractedClaim(
                    field=field,
                    value=value,
                    claim_text=match.group(0),
                    confidence=0.94,
                    extractor="deterministic_pattern",
                )
            )


def _money_claims(response: str) -> list[ExtractedClaim]:
    items: list[ExtractedClaim] = []
    for match in _MONEY_RE.finditer(response):
        amount = match.group("amount").replace(",", "")
        numeric: int | float
        if "." in amount:
            numeric = float(amount)
        else:
            numeric = int(amount)
        window = response[max(0, match.start() - 42): min(len(response), match.end() + 42)]
        if _FEE_CONTEXT_RE.search(window):
            field = "fee"
            confidence = 0.93
        elif _TRANSACTION_AMOUNT_CONTEXT_RE.search(window):
            field = "amount"
            confidence = 0.86
        else:
            continue
        items.append(
            ExtractedClaim(
                field=field,
                value=numeric,
                claim_text=match.group(0),
                confidence=confidence,
                extractor="deterministic_currency_pattern",
            )
        )
    return items


def extract_claims(assistant_response: str) -> dict[str, Any]:
    response = str(assistant_response or "").strip()
    items: list[ExtractedClaim] = []

    _add_status_claims(response, "transaction_status", _TRANSACTION_STATUS_PATTERNS, items)
    _add_status_claims(response, "refund_status", _REFUND_STATUS_PATTERNS, items)
    _add_status_claims(response, "account_status", _ACCOUNT_STATUS_PATTERNS, items)
    items.extend(_money_claims(response))

    match = _REFUND_ETA_HOURS_RE.search(response)
    if match:
        items.append(
            ExtractedClaim(
                field="refund_eta_hours",
                value=int(match.group("hours")),
                claim_text=match.group(0),
                confidence=0.95,
                extractor="deterministic_timeline_pattern",
            )
        )
    else:
        match = _REFUND_ETA_DAYS_RE.search(response)
        if match:
            items.append(
                ExtractedClaim(
                    field="refund_eta_hours",
                    value=int(match.group("days")) * 24,
                    claim_text=match.group(0),
                    confidence=0.90,
                    extractor="deterministic_timeline_pattern",
                )
            )

    eta_match = _ETA_RE.search(response)
    if eta_match:
        token_match = re.search(r"\b(today|tomorrow|tonight)\b", eta_match.group(0), re.IGNORECASE)
        if token_match:
            items.append(
                ExtractedClaim(
                    field="eta",
                    value=token_match.group(1).lower(),
                    claim_text=eta_match.group(0),
                    confidence=0.82,
                    extractor="deterministic_timeline_pattern",
                )
            )

    by_field: dict[str, list[ExtractedClaim]] = {}
    for item in items:
        by_field.setdefault(item.field, []).append(item)

    claims: dict[str, Any] = {}
    conflicts: list[dict[str, Any]] = []
    for field, field_items in sorted(by_field.items()):
        values: list[Any] = []
        for item in field_items:
            if item.value not in values:
                values.append(item.value)
        if len(values) == 1:
            claims[field] = values[0]
        else:
            conflicts.append({"field": field, "values": values})

    required_disposition = "REWRITE" if conflicts else "ALLOW"
    extraction_core = {
        "version": EXTRACTION_VERSION,
        "response_sha256": hashlib.sha256(response.encode("utf-8")).hexdigest(),
        "claims": claims,
        "conflicts": conflicts,
        "items": [item.to_dict() for item in items],
        "required_disposition": required_disposition,
    }
    return {
        "extraction_id": _sha256(extraction_core),
        **extraction_core,
        "mode": "deterministic",
        "advisory_only": True,
    }
