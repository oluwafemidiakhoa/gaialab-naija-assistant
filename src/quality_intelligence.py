"""Deterministic, explainable, advisory dataset quality intelligence."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Protocol, Sequence


ASSESSMENT_SCHEMA = "gaialab.quality-assessment.v1"
ENGINE_VERSION = "deterministic-1.0.0"
FACTUAL_REVIEW_CATEGORIES = {
    "banking", "healthcare", "government_services", "education", "agriculture", "travel"
}
HIGH_RISK_CATEGORIES = {"banking", "healthcare", "government_services"}
PIDGIN_MARKERS = {
    "abeg", "dey", "dem", "don", "fit", "make", "na", "pikin", "sabi",
    "wahala", "wetin", "una", "no be", "go reach",
}
NIGERIAN_MARKERS = {
    "₦", "naira", "nigeria", "nigerian", "lagos", "abuja", "enugu", "kaduna",
    "ibadan", "kano", "market", "motor park", "pos", "waec",
}


@dataclass(frozen=True)
class Finding:
    check: str
    severity: str
    score_deduction: int
    message: str


@dataclass(frozen=True)
class QualityAssessment:
    record_id: str
    record_sha256: str
    assessment_schema: str
    engine_version: str
    assessed_at: str
    overall_score: int
    clarity_score: int
    grammar_score: int
    completeness_score: int
    safety_score: int
    relevance_score: int
    response_specificity_score: int
    cultural_context_score: int
    pidgin_authenticity_score: int
    business_writing_score: int
    duplicate_risk_score: int
    hallucination_risk_score: int
    high_risk_domain_score: int
    recommended_action: str
    factual_review_required: bool
    findings: list[dict[str, Any]]
    warnings: list[str]
    checks_run: list[str]
    assessment_sha256: str


class QualityProvider(Protocol):
    def assess(
        self,
        record: dict[str, Any],
        *,
        records: Sequence[dict[str, Any]] = (),
        assessed_at: str | None = None,
    ) -> QualityAssessment: ...


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", text.casefold())


def _normalized(text: str) -> str:
    return " ".join(_tokens(text))


def _similarity(left: str, right: str) -> float:
    a, b = set(_tokens(left)), set(_tokens(right))
    return len(a & b) / len(a | b) if a or b else 1.0


def _messages(record: dict[str, Any]) -> tuple[str, str]:
    values = {
        message.get("role"): str(message.get("content", ""))
        for message in record.get("messages", [])
        if isinstance(message, dict)
    }
    return values.get("user", "").strip(), values.get("assistant", "").strip()


def _assessment_hash(payload: dict[str, Any]) -> str:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class DeterministicQualityProvider:
    """Explainable local heuristics; does not establish factual correctness."""

    checks = (
        "empty_user", "empty_assistant", "response_length", "response_repetition",
        "prompt_copy", "template_language", "near_duplicate_prompt",
        "near_duplicate_response", "credential_solicitation", "medical_certainty",
        "financial_guarantee", "government_contact", "emergency_instruction",
        "high_risk_escalation", "guaranteed_outcome", "grammar_completeness",
        "nigerian_context", "pidgin_authenticity", "business_writing_structure",
    )

    def assess(
        self,
        record: dict[str, Any],
        *,
        records: Sequence[dict[str, Any]] = (),
        assessed_at: str | None = None,
    ) -> QualityAssessment:
        user, assistant = _messages(record)
        category = str(record.get("category", "")).strip()
        risk = str(record.get("risk_level", "")).strip()
        findings: list[Finding] = []
        warnings: list[str] = []

        def add(check: str, severity: str, deduction: int, message: str) -> None:
            findings.append(Finding(check, severity, deduction, message))

        if not user:
            add("empty_user", "critical", 100, "User text is missing or empty.")
        if not assistant:
            add("empty_assistant", "critical", 100, "Assistant text is missing or empty.")
        word_count = len(_tokens(assistant))
        if assistant and word_count < 5:
            add("response_length", "high", 25, "The response is extremely short.")
        if word_count > 220:
            add("response_length", "medium", 15, "The response is excessively long.")

        words = _tokens(assistant)
        trigrams = [tuple(words[i:i + 3]) for i in range(max(0, len(words) - 2))]
        if trigrams and len(set(trigrams)) / len(trigrams) < 0.72:
            add("response_repetition", "medium", 15, "The response repeats phrases excessively.")
        if user and assistant and (
            _normalized(user) == _normalized(assistant) or _similarity(user, assistant) > 0.9
        ):
            add("prompt_copy", "high", 30, "The response closely copies the prompt.")
        if re.search(r"\[(?:name|amount|date|insert|company)\]|lorem ipsum|as an ai language model", assistant, re.I):
            add("template_language", "medium", 12, "Suspicious placeholder or template language remains.")

        prompt_duplicate = response_duplicate = 0.0
        for other in records:
            if other is record or other.get("id") == record.get("id"):
                continue
            other_user, other_assistant = _messages(other)
            prompt_duplicate = max(prompt_duplicate, _similarity(user, other_user))
            response_duplicate = max(response_duplicate, _similarity(assistant, other_assistant))
        if prompt_duplicate >= 0.82:
            add("near_duplicate_prompt", "medium", 20, "The prompt is a near-duplicate of another prompt.")
        if response_duplicate >= 0.9:
            add("near_duplicate_response", "medium", 15, "The response is a near-duplicate of another response.")

        credential_request = re.search(
            r"\b(?:send|share|provide|tell|enter|give)\b.{0,45}\b(?:password|pin|otp|cvv|private key|auth(?:entication)? token|full card number)\b",
            assistant, re.I,
        )
        if credential_request and not re.search(r"\b(?:do not|don't|never|no)\b.{0,20}" + re.escape(credential_request.group(0).split()[0]), assistant, re.I):
            add("credential_solicitation", "critical", 60, "The response solicits a private credential.")
        if re.search(r"\b(?:\d[ -]?){13,19}\b", assistant):
            add("credential_exposure", "critical", 60, "The response may expose a full payment-card number.")
        if category == "healthcare" and re.search(
            r"\b(?:definitely|certainly|you have|this is)\b.{0,30}\b(?:cancer|malaria|infection|disease|stroke)\b",
            assistant, re.I,
        ):
            add("medical_certainty", "critical", 50, "The response expresses dangerous medical certainty.")
        financial_claim = re.search(
            r"\b(?:guaranteed?|risk[- ]free|double your money|certain profit)\b",
            assistant, re.I,
        )
        if financial_claim and not re.search(
            r"\b(?:cannot|can't|do not|don't|never|no|not)\b",
            assistant[max(0, financial_claim.start() - 30):financial_claim.start()],
            re.I,
        ) and category == "banking":
            add("financial_guarantee", "critical", 50, "The response makes an unsafe financial guarantee.")
        if category == "government_services" and re.search(r"\b(?:\+?234|0)\d{9,10}\b", assistant):
            add("government_contact", "high", 35, "The response contains an unverified-looking government phone number.")
        if re.search(r"\b(?:call|dial)\s+\d{3,}\b", assistant, re.I):
            add("emergency_instruction", "high", 30, "The response gives an unsupported numeric emergency contact.")
        escalation = re.search(
            r"\b(?:qualified|professional|official|emergency|hospital|clinic|lawyer|authorit(?:y|ies)|banks?|providers?|operators?|teachers?|guardians?|trusted adult|law-enforcement|extension worker|veterinarian)\b",
            assistant, re.I,
        )
        if risk == "high" and not escalation:
            add("high_risk_escalation", "critical", 45, "A high-risk response lacks qualified human or official escalation.")
        outcome_claim = re.search(
            r"\b(?:guarantee|guaranteed|will definitely|always works|cannot fail)\b",
            assistant, re.I,
        )
        if outcome_claim and not re.search(
            r"\b(?:cannot|can't|do not|don't|never|no|not|without)\b",
            assistant[max(0, outcome_claim.start() - 30):outcome_claim.start()],
            re.I,
        ) and not re.search(
            r"\b(?:cautious|cautiously|not reliable|not assured)\b",
            assistant[outcome_claim.end():outcome_claim.end() + 40],
            re.I,
        ):
            add("guaranteed_outcome", "high", 35, "The response claims a guaranteed outcome.")
        if assistant and not re.search(r"[.!?][\"']?$", assistant.strip()):
            add("grammar_completeness", "low", 5, "The response may not end with a complete sentence.")
        if assistant and assistant[:1].islower():
            add("grammar_completeness", "low", 5, "The response begins with a lowercase letter.")

        context_hits = sum(marker in f"{user} {assistant}".casefold() for marker in NIGERIAN_MARKERS)
        pidgin_hits = sum(
            re.search(rf"\b{re.escape(marker)}\b", assistant.casefold()) is not None
            for marker in PIDGIN_MARKERS
        )
        if category == "nigerian_pidgin" and pidgin_hits < 2:
            add("pidgin_authenticity", "medium", 20, "Nigerian Pidgin signals are limited; human language review is required.")
        if category == "business_writing" and not re.search(
            r"\b(?:good (?:day|morning|afternoon|evening)|dear|thank|subject|invoice|quotation|regards)\b",
            assistant, re.I,
        ):
            add("business_writing_structure", "medium", 15, "Expected business-writing structure is limited.")
        if category in FACTUAL_REVIEW_CATEGORIES:
            warnings.append("Factual correctness is not established; qualified human review is required.")

        deductions = sum(f.score_deduction for f in findings)
        safety_deductions = sum(
            f.score_deduction for f in findings
            if f.severity in {"critical", "high"} and f.check in {
                "credential_solicitation", "credential_exposure", "medical_certainty",
                "financial_guarantee", "emergency_instruction", "high_risk_escalation",
                "guaranteed_outcome", "government_contact",
            }
        )
        duplicate_deductions = sum(
            f.score_deduction for f in findings if "duplicate" in f.check
        )
        completeness_deductions = sum(
            f.score_deduction for f in findings
            if f.check in {"empty_user", "empty_assistant", "response_length"}
        )
        grammar_deductions = sum(
            f.score_deduction for f in findings
            if f.check in {"grammar_completeness", "response_repetition"}
        )
        scores = {
            "clarity_score": max(0, 100 - grammar_deductions),
            "grammar_score": max(0, 100 - grammar_deductions),
            "completeness_score": max(0, 100 - completeness_deductions),
            "safety_score": max(0, 100 - safety_deductions),
            "relevance_score": max(0, 100 - (30 if any(f.check == "prompt_copy" for f in findings) else 0)),
            "response_specificity_score": max(0, 100 - (25 if word_count < 5 else 0)),
            "cultural_context_score": min(100, 55 + context_hits * 10),
            "pidgin_authenticity_score": (
                min(100, 40 + pidgin_hits * 12) if category == "nigerian_pidgin" else 100
            ),
            "business_writing_score": (
                85 if category == "business_writing" and not any(f.check == "business_writing_structure" for f in findings)
                else 60 if category == "business_writing" else 100
            ),
            "duplicate_risk_score": max(0, 100 - duplicate_deductions),
            "hallucination_risk_score": max(
                0, 100 - sum(f.score_deduction for f in findings if f.check in {
                    "medical_certainty", "financial_guarantee", "government_contact",
                    "guaranteed_outcome",
                })
            ),
            "high_risk_domain_score": max(
                0, 100 - (45 if any(f.check == "high_risk_escalation" for f in findings) else 0)
            ),
        }
        overall = max(0, min(100, round(sum(scores.values()) / len(scores) - min(20, deductions / 10))))
        critical = any(f.severity == "critical" for f in findings)
        if critical or overall < 35:
            action = "reject_candidate"
        elif overall < 60:
            action = "revise"
        elif findings or category in FACTUAL_REVIEW_CATEGORIES:
            action = "human_review"
        else:
            action = "approve_candidate"

        timestamp = assessed_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
        payload: dict[str, Any] = {
            "record_id": str(record.get("id", "")),
            "record_sha256": str(record.get("example_sha256", "")),
            "assessment_schema": ASSESSMENT_SCHEMA,
            "engine_version": ENGINE_VERSION,
            "assessed_at": timestamp,
            "overall_score": overall,
            **{name: int(value) for name, value in scores.items()},
            "recommended_action": action,
            "factual_review_required": category in FACTUAL_REVIEW_CATEGORIES,
            "findings": [asdict(finding) for finding in findings],
            "warnings": warnings,
            "checks_run": list(self.checks),
        }
        payload["assessment_sha256"] = _assessment_hash(payload)
        return QualityAssessment(**payload)


class OptionalLLMQualityProvider:
    """Explicitly configured adapter; disabled and network-free by default."""

    def __init__(
        self,
        evaluator: Callable[[dict[str, Any]], QualityAssessment] | None = None,
        *,
        enabled: bool = False,
    ) -> None:
        self._evaluator = evaluator
        self._enabled = enabled

    def assess(
        self,
        record: dict[str, Any],
        *,
        records: Sequence[dict[str, Any]] = (),
        assessed_at: str | None = None,
    ) -> QualityAssessment:
        if not self._enabled or self._evaluator is None:
            raise RuntimeError("Optional LLM quality provider is disabled")
        return self._evaluator(record)


def assess_records(
    records: Sequence[dict[str, Any]],
    provider: QualityProvider | None = None,
    *,
    assessed_at: str | None = None,
) -> list[QualityAssessment]:
    active = provider or DeterministicQualityProvider()
    return [
        active.assess(record, records=records, assessed_at=assessed_at)
        for record in records
    ]
