"""Deterministic advisory analysis with validated optional provider output."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from src.dataset_management import example_sha256
from src.quality_intelligence import DeterministicQualityProvider
from src.review_automation.config import ReviewAutomationConfig
from src.review_automation.duplicates import (
    find_duplicate_matches,
    message_text,
)
from src.review_automation.models import (
    ANALYZER_VERSION,
    AdvisoryRecommendation,
    RecommendationCategory,
    ReviewAutomationModelError,
    SuggestedRevision,
)
from src.review_automation.providers import (
    ProviderRequest,
    ReviewProvider,
)


SAFETY_CHECKS = {
    "credential_solicitation",
    "credential_exposure",
    "medical_certainty",
    "financial_guarantee",
    "government_contact",
    "emergency_instruction",
    "high_risk_escalation",
    "guaranteed_outcome",
}
GRAMMAR_CHECKS = {
    "grammar_completeness", "response_repetition", "response_length"
}
AMBIGUITY_CHECKS = {
    "empty_user", "empty_assistant", "response_length", "template_language"
}
UNSUPPORTED_CLAIM_CHECKS = {
    "medical_certainty", "financial_guarantee", "government_contact",
    "guaranteed_outcome",
}
PROVIDER_FIELDS = {
    "summary",
    "language_grammar_findings",
    "safety_findings",
    "factuality_concerns",
    "cultural_context_concerns",
    "pidgin_authenticity_concerns",
    "ambiguity_findings",
    "unsupported_claim_indicators",
    "missing_citation_indicators",
    "high_risk_domain_indicators",
    "suggested_revision",
    "rationale",
    "confidence_score",
    "recommendation",
}


@dataclass(frozen=True)
class ProviderAnalysis:
    summary: str
    language_grammar_findings: tuple[str, ...]
    safety_findings: tuple[str, ...]
    factuality_concerns: tuple[str, ...]
    cultural_context_concerns: tuple[str, ...]
    pidgin_authenticity_concerns: tuple[str, ...]
    ambiguity_findings: tuple[str, ...]
    unsupported_claim_indicators: tuple[str, ...]
    missing_citation_indicators: tuple[str, ...]
    high_risk_domain_indicators: tuple[str, ...]
    suggested_revision: SuggestedRevision | None
    rationale: str
    confidence_score: int
    recommendation: RecommendationCategory


def _string_tuple(value: Any, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        raise ReviewAutomationModelError(
            f"provider field {field} must be a list of non-empty strings"
        )
    return tuple(item.strip() for item in value)


def validate_provider_output(value: Mapping[str, Any]) -> ProviderAnalysis:
    """Validate provider JSON strictly before it can become a recommendation."""
    if set(value) != PROVIDER_FIELDS:
        missing = sorted(PROVIDER_FIELDS - set(value))
        extra = sorted(set(value) - PROVIDER_FIELDS)
        raise ReviewAutomationModelError(
            f"provider schema mismatch; missing={missing}, extra={extra}"
        )
    summary = value["summary"]
    rationale = value["rationale"]
    confidence = value["confidence_score"]
    if not isinstance(summary, str) or not summary.strip():
        raise ReviewAutomationModelError("provider summary must not be empty")
    if not isinstance(rationale, str) or not rationale.strip():
        raise ReviewAutomationModelError("provider rationale must not be empty")
    if (
        isinstance(confidence, bool)
        or not isinstance(confidence, int)
        or not 0 <= confidence <= 100
    ):
        raise ReviewAutomationModelError(
            "provider confidence_score must be from 0 to 100"
        )
    try:
        category = RecommendationCategory(value["recommendation"])
    except (TypeError, ValueError) as exc:
        raise ReviewAutomationModelError(
            "provider recommendation category is invalid"
        ) from exc
    revision_value = value["suggested_revision"]
    revision = None
    if revision_value is not None:
        if not isinstance(revision_value, Mapping):
            raise ReviewAutomationModelError(
                "provider suggested_revision must be an object or null"
            )
        required = {
            "prompt", "response", "changes_summary", "reasons", "safety_impact",
            "factuality_impact", "cultural_context_impact",
        }
        if set(revision_value) != required:
            raise ReviewAutomationModelError(
                "provider suggested_revision schema mismatch"
            )
        revision = SuggestedRevision(
            prompt=str(revision_value["prompt"]),
            response=str(revision_value["response"]),
            changes_summary=_string_tuple(
                revision_value["changes_summary"], "changes_summary"
            ),
            reasons=_string_tuple(revision_value["reasons"], "reasons"),
            safety_impact=str(revision_value["safety_impact"]),
            factuality_impact=str(revision_value["factuality_impact"]),
            cultural_context_impact=str(
                revision_value["cultural_context_impact"]
            ),
        )
    tuple_fields = {
        field: _string_tuple(value[field], field)
        for field in PROVIDER_FIELDS
        if field.endswith("findings")
        or field.endswith("concerns")
        or field.endswith("indicators")
    }
    return ProviderAnalysis(
        summary=summary.strip(),
        **tuple_fields,
        suggested_revision=revision,
        rationale=rationale.strip(),
        confidence_score=confidence,
        recommendation=category,
    )


def _messages_for_findings(
    findings: list[dict[str, Any]], checks: set[str]
) -> tuple[str, ...]:
    return tuple(
        str(finding.get("message", "")).strip()
        for finding in findings
        if finding.get("check") in checks and str(finding.get("message", "")).strip()
    )


def _local_suggestion(
    record: dict[str, Any],
    findings: list[dict[str, Any]],
) -> SuggestedRevision | None:
    prompt = message_text(record, "user")
    response = message_text(record, "assistant")
    if not findings:
        return None
    revised_response = " ".join(response.split())
    changes: list[str] = []
    reasons: list[str] = []
    if revised_response and not re.search(r"[.!?][\"']?$", revised_response):
        revised_response += "."
        changes.append("Added sentence-ending punctuation.")
        reasons.append("Improve sentence completeness.")
    if any(finding.get("check") == "high_risk_escalation" for finding in findings):
        revised_response += (
            " Please contact a qualified professional or appropriate official "
            "channel for guidance."
        )
        changes.append("Added qualified human or official escalation.")
        reasons.append("The high-risk response lacked escalation guidance.")
    if not changes:
        changes.append("Preserved source wording for explicit human editing.")
        reasons.append("Automated rewriting could introduce unsupported meaning.")
    return SuggestedRevision(
        prompt=prompt,
        response=revised_response,
        changes_summary=tuple(changes),
        reasons=tuple(reasons),
        safety_impact=(
            "Adds general escalation guidance." if any(
                finding.get("check") == "high_risk_escalation"
                for finding in findings
            ) else "No automatic safety claim added."
        ),
        factuality_impact="No specific factual claim or citation was added.",
        cultural_context_impact=(
            "No Nigerian cultural claim was added; human context review remains required."
        ),
    )


class ReviewAnalyzer:
    """Create traceable recommendations without changing record state."""

    def __init__(
        self,
        config: ReviewAutomationConfig,
        *,
        provider: ReviewProvider | None = None,
        prompt_dir: Path | None = None,
    ) -> None:
        self.config = config
        self.provider = provider
        self.prompt_dir = prompt_dir or (
            Path(__file__).resolve().parents[2] / "evaluation" / "review_prompts"
        )

    def _prompt(self) -> str:
        path = self.prompt_dir / f"{self.config.prompt_version}.txt"
        try:
            prompt = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ReviewAutomationModelError(
                f"review prompt unavailable: {path.name}"
            ) from exc
        if f"prompt_version: {self.config.prompt_version}" not in prompt:
            raise ReviewAutomationModelError(
                "review prompt version does not match configuration"
            )
        return prompt

    def _local(
        self,
        record: dict[str, Any],
        records: Sequence[dict[str, Any]],
        generated_at: str,
    ) -> AdvisoryRecommendation:
        assessment = DeterministicQualityProvider().assess(
            record, records=records, assessed_at=generated_at
        )
        findings = list(assessment.findings)
        duplicates = find_duplicate_matches(
            record,
            records,
            near_threshold=self.config.near_duplicate_threshold,
        )
        category = str(record.get("category", ""))
        risk = str(record.get("risk_level", ""))
        domain_required = category in self.config.domain_review_categories
        safety_findings = _messages_for_findings(findings, SAFETY_CHECKS)
        confidence = max(55, 94 - min(30, len(findings) * 3 + len(duplicates) * 2))
        critical_safety = any(
            finding.get("severity") == "critical"
            and finding.get("check") in SAFETY_CHECKS
            for finding in findings
        )
        if critical_safety or (
            risk == "high"
            and category in self.config.enhanced_safety_categories
            and safety_findings
        ):
            recommendation = RecommendationCategory.ESCALATE_SAFETY
        elif domain_required:
            recommendation = RecommendationCategory.ESCALATE_DOMAIN
        elif assessment.overall_score < self.config.reject_candidate_below:
            recommendation = RecommendationCategory.REJECT_CANDIDATE
        elif (
            assessment.overall_score < self.config.approve_candidate_score
            or assessment.overall_score < self.config.minimum_quality_score
            or confidence < self.config.recommendation_confidence_threshold
            or findings
        ):
            recommendation = RecommendationCategory.REVISE_CANDIDATE
        else:
            recommendation = RecommendationCategory.APPROVE_CANDIDATE

        factuality = tuple(assessment.warnings)
        cultural = (
            ("Nigerian-context relevance is limited; human cultural review is required.",)
            if assessment.cultural_context_score < 65 else ()
        )
        pidgin = _messages_for_findings(findings, {"pidgin_authenticity"})
        unsupported = _messages_for_findings(findings, UNSUPPORTED_CLAIM_CHECKS)
        response = message_text(record, "assistant")
        citation_expected = (
            category in self.config.domain_review_categories
            and re.search(
                r"\b(?:according to|section|act|regulation|official requirement|20\d{2})\b|(?:₦|%)\s*\d",
                response,
                re.I,
            )
        )
        missing_citations = (
            ("A specific factual or regulatory-looking claim needs source verification.",)
            if citation_expected and not re.search(r"https?://|official source", response, re.I)
            else ()
        )
        high_risk = (
            (f"{category} is configured for enhanced safety review.",)
            if category in self.config.enhanced_safety_categories or risk == "high"
            else ()
        )
        return AdvisoryRecommendation.create(
            record_id=str(record.get("id", "")),
            dataset_version=str(record.get("dataset_version", "")),
            record_revision=int(record.get("revision", 1)),
            input_record_sha256=str(record.get("example_sha256", "")),
            prompt_version=self.config.prompt_version,
            provider="local",
            model_name="deterministic-rules",
            generation_timestamp=generated_at,
            analyzer_version=ANALYZER_VERSION,
            summary=f"{category} record with {risk} declared risk.",
            quality_score=assessment.overall_score,
            language_grammar_findings=_messages_for_findings(
                findings, GRAMMAR_CHECKS
            ),
            safety_findings=safety_findings,
            factuality_concerns=factuality,
            cultural_context_concerns=cultural,
            pidgin_authenticity_concerns=pidgin,
            ambiguity_findings=_messages_for_findings(findings, AMBIGUITY_CHECKS),
            unsupported_claim_indicators=unsupported,
            missing_citation_indicators=missing_citations,
            high_risk_domain_indicators=high_risk,
            duplicate_matches=duplicates,
            technical_review_required=True,
            domain_review_required=domain_required,
            suggested_revision=_local_suggestion(record, findings),
            rationale=(
                "Advisory local rules only; an explicit human decision is required."
            ),
            confidence_score=confidence,
            recommendation=recommendation,
        )

    def analyze(
        self,
        record: dict[str, Any],
        *,
        records: Sequence[dict[str, Any]],
        generated_at: str,
    ) -> AdvisoryRecommendation:
        """Analyze without mutating the record or its official review status."""
        if record.get("example_sha256") != example_sha256(record):
            raise ReviewAutomationModelError("record content hash mismatch")
        local = self._local(record, records, generated_at)
        if self.provider is None:
            return local
        if self.provider.externally_generated and not self.config.external_provider_enabled:
            return local
        request = ProviderRequest(
            prompt_version=self.config.prompt_version,
            prompt_template=self._prompt(),
            record_id=str(record.get("id", "")),
            category=str(record.get("category", "")),
            risk_level=str(record.get("risk_level", "")),
            user_text=message_text(record, "user"),
            assistant_text=message_text(record, "assistant"),
        )
        try:
            external = validate_provider_output(self.provider.generate(request))
        except Exception:
            return AdvisoryRecommendation.create(
                **{
                    **local.payload(),
                    "provider": "local_fallback",
                    "model_name": "deterministic-rules",
                    "rationale": (
                        "Provider output was unavailable or invalid; deterministic "
                        "local analysis was used. Explicit human review is required."
                    ),
                }
            )
        return AdvisoryRecommendation.create(
            **{
                **local.payload(),
                "provider": self.provider.name,
                "model_name": self.provider.model_name,
                "summary": external.summary,
                "language_grammar_findings": external.language_grammar_findings,
                "safety_findings": external.safety_findings,
                "factuality_concerns": external.factuality_concerns,
                "cultural_context_concerns": external.cultural_context_concerns,
                "pidgin_authenticity_concerns": external.pidgin_authenticity_concerns,
                "ambiguity_findings": external.ambiguity_findings,
                "unsupported_claim_indicators": external.unsupported_claim_indicators,
                "missing_citation_indicators": external.missing_citation_indicators,
                "high_risk_domain_indicators": external.high_risk_domain_indicators,
                "suggested_revision": external.suggested_revision,
                "rationale": (
                    (
                        "Externally generated advisory recommendation. "
                        if self.provider.externally_generated
                        else "Provider-generated advisory recommendation. "
                    )
                    + external.rationale
                ),
                "confidence_score": external.confidence_score,
                "recommendation": external.recommendation,
            }
        )
