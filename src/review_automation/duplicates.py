"""Deterministic, CPU-only duplicate and near-duplicate analysis."""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from typing import Any, Iterable

from src.review_automation.models import DuplicateMatch


MATCH_ORDER = {
    "exact": 0,
    "normalized": 1,
    "prompt": 2,
    "answer": 3,
    "prompt_answer": 4,
    "near": 5,
}


def message_text(record: dict[str, Any], role: str) -> str:
    """Return one message role without assuming list offsets."""
    for message in record.get("messages", []):
        if isinstance(message, dict) and message.get("role") == role:
            return str(message.get("content", "")).strip()
    return ""


def normalize_text(text: str) -> str:
    """Normalize Unicode, case, punctuation, and whitespace deterministically."""
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return " ".join(re.findall(r"[^\W_]+(?:'[^\W_]+)?", normalized, re.UNICODE))


def _features(text: str) -> Counter[str]:
    words = normalize_text(text).split()
    return Counter(words + [f"{left}_{right}" for left, right in zip(words, words[1:])])


def _feature_similarity(a: Counter[str], b: Counter[str]) -> float:
    common = a.keys() & b.keys()
    numerator = sum(a[token] * b[token] for token in common)
    denominator = math.sqrt(sum(value * value for value in a.values())) * math.sqrt(
        sum(value * value for value in b.values())
    )
    return numerator / denominator if denominator else 0.0


def similarity(left: str, right: str) -> float:
    """Return deterministic unigram/bigram cosine similarity."""
    return _feature_similarity(_features(left), _features(right))


@dataclass(frozen=True)
class _PreparedRecord:
    record: dict[str, Any]
    prompt: str
    answer: str
    normalized_prompt: str
    normalized_answer: str
    combined: str
    normalized_combined: str
    features: Counter[str]


def _prepare(record: dict[str, Any]) -> _PreparedRecord:
    prompt = message_text(record, "user")
    answer = message_text(record, "assistant")
    normalized_prompt = normalize_text(prompt)
    normalized_answer = normalize_text(answer)
    normalized_combined = f"{normalized_prompt}\n{normalized_answer}"
    return _PreparedRecord(
        record=record,
        prompt=prompt,
        answer=answer,
        normalized_prompt=normalized_prompt,
        normalized_answer=normalized_answer,
        combined=f"{prompt}\n{answer}",
        normalized_combined=normalized_combined,
        features=_features(normalized_combined),
    )


def _pair_specs(
    left: _PreparedRecord,
    right: _PreparedRecord,
    near_threshold: float,
) -> list[tuple[str, float, str]]:
    specs: list[tuple[str, float, str]] = []
    if left.combined == right.combined:
        specs.append((
            "exact",
            1.0,
            "Prompt and answer are byte-for-byte equal after trimming.",
        ))
    if (
        left.normalized_combined == right.normalized_combined
        and left.combined != right.combined
    ):
        specs.append((
            "normalized",
            1.0,
            "Prompt and answer match after case, punctuation, and whitespace normalization.",
        ))
    if (
        left.normalized_prompt
        and left.normalized_prompt == right.normalized_prompt
    ):
        specs.append(("prompt", 1.0, "Normalized user prompts are equal."))
    if (
        left.normalized_answer
        and left.normalized_answer == right.normalized_answer
    ):
        specs.append(("answer", 1.0, "Normalized assistant responses are equal."))
    if (
        left.normalized_combined == right.normalized_combined
        and left.normalized_prompt
        and left.normalized_answer
    ):
        specs.append((
            "prompt_answer",
            1.0,
            "The normalized prompt-answer pair is duplicated.",
        ))
    score = _feature_similarity(left.features, right.features)
    if near_threshold <= score < 1:
        specs.append((
            "near",
            score,
            "Local unigram/bigram cosine similarity exceeds the configured threshold.",
        ))
    return specs


def _match(
    other: dict[str, Any],
    match_type: str,
    score: float,
    explanation: str,
) -> DuplicateMatch:
    return DuplicateMatch(
        matched_record_id=str(other.get("id", "")),
        matched_record_sha256=str(other.get("example_sha256", "")),
        match_type=match_type,
        similarity=round(score, 6),
        explanation=explanation,
    )


def _ordered_unique(
    matches: Iterable[DuplicateMatch],
) -> tuple[DuplicateMatch, ...]:
    unique = {
        (match.matched_record_id, match.matched_record_sha256, match.match_type): match
        for match in matches
    }
    return tuple(sorted(
        unique.values(),
        key=lambda match: (
            MATCH_ORDER[match.match_type],
            -match.similarity,
            match.matched_record_id,
            match.matched_record_sha256,
        ),
    ))


def find_duplicate_matches(
    record: dict[str, Any],
    records: Iterable[dict[str, Any]],
    *,
    near_threshold: float = 0.82,
) -> tuple[DuplicateMatch, ...]:
    """Explain all exact, normalized, field, pair, and near matches."""
    if not 0 < near_threshold <= 1:
        raise ValueError("near_threshold must be greater than 0 and at most 1")
    prepared = _prepare(record)
    matches: list[DuplicateMatch] = []

    for other in records:
        if other is record or (
            other.get("id") == record.get("id")
            and other.get("example_sha256") == record.get("example_sha256")
        ):
            continue
        for match_type, score, explanation in _pair_specs(
            prepared,
            _prepare(other),
            near_threshold,
        ):
            matches.append(_match(other, match_type, score, explanation))
    return _ordered_unique(matches)


def duplicate_match_map(
    records: Iterable[dict[str, Any]],
    *,
    near_threshold: float = 0.82,
) -> dict[tuple[str, str], tuple[DuplicateMatch, ...]]:
    """Compute all record matches once for efficient queue construction."""
    if not 0 < near_threshold <= 1:
        raise ValueError("near_threshold must be greater than 0 and at most 1")
    prepared = [_prepare(record) for record in records]
    matches: list[list[DuplicateMatch]] = [[] for _ in prepared]
    for left_index, left in enumerate(prepared):
        for right_index in range(left_index + 1, len(prepared)):
            right = prepared[right_index]
            if (
                left.record.get("id") == right.record.get("id")
                and left.record.get("example_sha256")
                == right.record.get("example_sha256")
            ):
                continue
            for match_type, score, explanation in _pair_specs(
                left,
                right,
                near_threshold,
            ):
                matches[left_index].append(
                    _match(right.record, match_type, score, explanation)
                )
                matches[right_index].append(
                    _match(left.record, match_type, score, explanation)
                )
    return {
        (
            str(item.record.get("id", "")),
            str(item.record.get("example_sha256", "")),
        ): _ordered_unique(matches[index])
        for index, item in enumerate(prepared)
    }


def duplicate_likelihood(matches: Iterable[DuplicateMatch]) -> int:
    """Convert explained matches to a stable 0–100 queue signal."""
    values = list(matches)
    return round(100 * max((match.similarity for match in values), default=0.0))
