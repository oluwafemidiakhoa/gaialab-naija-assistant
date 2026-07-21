import json
from collections import Counter
from pathlib import Path

import pytest

from evaluation import run_benchmark as benchmark_runner
from evaluation.run_benchmark import (
    BenchmarkError,
    EXPECTED_CATEGORIES,
    PROHIBITED_ANSWER_FIELDS,
    blank_human_review,
    load_benchmark,
)


ROOT = Path(__file__).parents[1]
BENCHMARK_PATH = ROOT / "evaluation" / "gaia_benchmark_v0.1.jsonl"


def test_benchmark_has_exact_size_and_distribution():
    records = load_benchmark(BENCHMARK_PATH)

    assert len(records) == 30
    assert Counter(record["category"] for record in records) == EXPECTED_CATEGORIES
    assert len({record["id"] for record in records}) == 30
    assert len({record["instruction"] for record in records}) == 30


def test_benchmark_contains_characteristics_but_no_answers():
    for record in load_benchmark(BENCHMARK_PATH):
        assert record["expected_characteristics"]
        assert not PROHIBITED_ANSWER_FIELDS.intersection(record)
        assert record["review_status"] == "draft_pending_independent_human_review"
        assert record["source"] == (
            "GaiaBench Africa original draft — pending independent Nigerian human review"
        )
        assert record["license"] == "CC0-1.0"


def test_benchmark_prompts_are_not_training_prompts():
    benchmark_prompts = {
        (record["instruction"], record["input"])
        for record in load_benchmark(BENCHMARK_PATH)
    }
    training_prompts = set()
    for dataset_path in (ROOT / "data").glob("*.jsonl"):
        for line in dataset_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                record = json.loads(line)
                training_prompts.add((record["instruction"], record["input"]))

    assert benchmark_prompts.isdisjoint(training_prompts)


def test_loader_rejects_expected_answers(tmp_path):
    records = load_benchmark(BENCHMARK_PATH)
    records[0]["expected_answer"] = "This must not be present."
    invalid_path = tmp_path / "invalid.jsonl"
    invalid_path.write_text(
        "".join(json.dumps(record) + "\n" for record in records), encoding="utf-8"
    )

    with pytest.raises(BenchmarkError, match="expected answers are prohibited"):
        load_benchmark(invalid_path)


def test_human_scores_start_unassigned():
    review = blank_human_review()

    assert review["reviewer"] == ""
    assert review["notes"] == ""
    assert all(value is None for key, value in review.items() if key not in {"reviewer", "notes"})


def test_runner_writes_responses_without_scores(tmp_path, monkeypatch):
    records = load_benchmark(BENCHMARK_PATH)
    monkeypatch.setattr(
        benchmark_runner,
        "load_model",
        lambda model_id: (object(), object(), object()),
    )
    monkeypatch.setattr(
        benchmark_runner,
        "generate_response",
        lambda *args, **kwargs: "Draft model response",
    )
    output_path = tmp_path / "results.jsonl"

    benchmark_runner.run_benchmark(
        records,
        output_path,
        model_id="local/test-model",
        max_input_tokens=512,
        max_new_tokens=64,
    )

    results = [
        json.loads(line)
        for line in output_path.read_text(encoding="utf-8").splitlines()
    ]
    assert len(results) == 30
    assert all(result["response"] == "Draft model response" for result in results)
    assert all(
        score is None
        for result in results
        for key, score in result["human_review"].items()
        if key not in {"reviewer", "notes"}
    )
