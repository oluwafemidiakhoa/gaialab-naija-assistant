from src.benchmarking import aggregate_results, leakage_report, prepare_benchmark_case, report_files


def case(prompt="Please write a reminder"):
    return prepare_benchmark_case({
        "benchmark_id": "bench-001", "category": "business_writing",
        "risk_level": "low", "prompt": prompt,
        "expected_behaviors": ["polite"], "prohibited_behaviors": ["threat"],
        "scoring_rubric": {"pass": "polite"}, "benchmark_version": "v1",
    })


def record(prompt="Different prompt"):
    return {"id": "train-1", "messages": [
        {"role": "system", "content": "Help"},
        {"role": "user", "content": prompt},
        {"role": "assistant", "content": "Okay"},
    ]}


def test_benchmark_hash_is_deterministic():
    assert case()["benchmark_sha256"] == case()["benchmark_sha256"]


def test_exact_and_normalized_leakage():
    report = leakage_report([case("Please, write a REMINDER!")], [record("please write a reminder")])
    assert not report["leakage_free"]
    assert report["exact_prompt_overlap"] == ["bench-001"]


def test_near_duplicate_reported_without_blocking():
    report = leakage_report([case("write a polite invoice reminder today")], [
        record("write a polite invoice reminder")
    ], near_threshold=0.7)
    assert report["near_duplicate_overlap"]


def test_cross_version_comparability_and_files():
    rows = [
        {"model_version": "v1", "benchmark_id": "b1", "category": "banking",
         "passed": True, "safety_passed": True, "dataset_version": "v0.6",
         "model_verified": True, "benchmark_version": "b1", "scoring_method": "human"},
        {"model_version": "v2", "benchmark_id": "b1", "category": "banking",
         "passed": False, "safety_passed": False, "failure_reason": "unsafe",
         "dataset_version": "v0.6", "model_verified": False,
         "benchmark_version": "b1", "scoring_method": "human"},
    ]
    assert aggregate_results(rows)["comparable"]
    files = report_files(rows)
    assert set(files) == {
        "all_model_versions.json", "all_model_versions.md",
        "per_category.csv", "failures.csv",
    }
