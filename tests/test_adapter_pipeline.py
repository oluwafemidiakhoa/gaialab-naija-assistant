import csv
import json
from pathlib import Path

import pytest
import yaml

from compare_models import (
    DEFAULT_BASE_MODEL,
    build_comparison,
    write_reports,
)
from evaluation.run_benchmark import HUMAN_SCORE_FIELDS, load_benchmark
from publish_to_huggingface import PublishingError, publish_release
from train_adapter import (
    AdapterTrainingConfig,
    CsvMetricsCallback,
    TrainingConfigurationError,
    find_latest_checkpoint,
    load_split_records,
    load_training_config,
)


ROOT = Path(__file__).parents[1]
CONFIG_PATH = ROOT / "training" / "default_config.yaml"
BENCHMARK_PATH = ROOT / "evaluation" / "gaia_benchmark_v0.1.jsonl"


def test_default_training_config_has_required_values():
    config = load_training_config(CONFIG_PATH)

    assert config.model == "Qwen/Qwen2.5-0.5B-Instruct"
    assert config.dataset == "data/gaialab_naija_v0.1.jsonl"
    assert config.evaluation_frequency == 1
    assert config.target_modules == ["q_proj", "k_proj", "v_proj", "o_proj"]
    train, validation, report = load_split_records(config)
    assert report.valid_records == 100
    assert len(train) == 80
    assert len(validation) == 20


def test_training_config_rejects_missing_fields(tmp_path):
    raw = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    del raw["seed"]
    path = tmp_path / "invalid.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")

    with pytest.raises(TrainingConfigurationError, match="Missing"):
        load_training_config(path)


def test_find_latest_complete_checkpoint(tmp_path):
    for step in (4, 12, 9):
        checkpoint = tmp_path / f"checkpoint-{step}"
        checkpoint.mkdir()
        (checkpoint / "trainer_state.json").write_text("{}", encoding="utf-8")
    (tmp_path / "checkpoint-99").mkdir()

    assert find_latest_checkpoint(tmp_path) == tmp_path / "checkpoint-12"


def test_csv_metrics_callback_writes_train_and_evaluation_rows(tmp_path):
    callback = CsvMetricsCallback(tmp_path / "metrics.csv")
    state = type("State", (), {"global_step": 3, "epoch": 1.0})()

    callback.on_log(None, state, None, {"loss": 1.2, "learning_rate": 0.0002})
    callback.on_log(None, state, None, {"eval_loss": 1.0, "epoch": 1.0})

    with (tmp_path / "metrics.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert [row["split"] for row in rows] == ["training", "evaluation"]
    assert rows[0]["loss"] == "1.2"
    assert rows[1]["eval_loss"] == "1.0"


def test_comparison_reports_contain_only_human_score_placeholders(tmp_path):
    records = load_benchmark(BENCHMARK_PATH)
    comparison = build_comparison(
        records,
        ["Base response"] * len(records),
        ["Adapter response"] * len(records),
        DEFAULT_BASE_MODEL,
        Path("outputs/test-adapter"),
        BENCHMARK_PATH,
    )

    assert comparison["benchmark_metadata"]["prompt_count"] == 30
    assert comparison["benchmark_metadata"]["scores_assigned_by_runner"] is False
    for model_scores in comparison["average_score_placeholders"].values():
        assert all(score is None for score in model_scores.values())
    for result in comparison["results"]:
        for model in ("base_model", "lora_adapter"):
            review = result["human_review"][model]
            assert all(review[field] is None for field in HUMAN_SCORE_FIELDS)

    write_reports(comparison, tmp_path, overwrite=False)
    assert (tmp_path / "comparison.json").is_file()
    assert (tmp_path / "comparison.csv").is_file()
    with (tmp_path / "comparison.csv").open(encoding="utf-8", newline="") as handle:
        csv_rows = list(csv.DictReader(handle))
    assert csv_rows[-1]["id"] == "AVERAGE_SCORE_PLACEHOLDER"
    assert csv_rows[0]["benchmark_name"] == "GaiaBench Africa"
    assert csv_rows[0]["benchmark_version"] == "v0.1"
    markdown = (tmp_path / "comparison.md").read_text(encoding="utf-8")
    assert "Pending human review" in markdown
    assert "does not claim that either model performs better" in markdown


class FakeHubApi:
    def __init__(self):
        self.calls = []

    def create_repo(self, **kwargs):
        self.calls.append(("create_repo", kwargs))

    def upload_folder(self, **kwargs):
        self.calls.append(("upload_folder", kwargs))

    def upload_file(self, **kwargs):
        self.calls.append(("upload_file", kwargs))


def make_release_files(tmp_path):
    adapter = tmp_path / "adapter"
    adapter.mkdir()
    (adapter / "adapter_config.json").write_text("{}", encoding="utf-8")
    (adapter / "adapter_model.safetensors").write_bytes(b"test")
    (adapter / "tokenizer_config.json").write_text("{}", encoding="utf-8")
    model_card = tmp_path / "README.md"
    model_card.write_text("# Completed model card\n", encoding="utf-8")
    report = tmp_path / "comparison.md"
    report.write_text("# Human-reviewed report\n", encoding="utf-8")
    return adapter, model_card, report


def test_publish_release_uploads_required_artifacts_privately(tmp_path):
    adapter, model_card, report = make_release_files(tmp_path)
    api = FakeHubApi()

    publish_release(
        adapter,
        model_card,
        report,
        "gaialab/adapter-v0.1",
        public=False,
        api=api,
    )

    assert [name for name, _ in api.calls] == [
        "create_repo",
        "upload_folder",
        "upload_file",
        "upload_file",
    ]
    assert api.calls[0][1]["private"] is True
    assert api.calls[2][1]["path_in_repo"] == "README.md"
    assert api.calls[3][1]["path_in_repo"] == "evaluation/comparison.md"


def test_publish_release_rejects_unresolved_model_card(tmp_path):
    adapter, model_card, report = make_release_files(tmp_path)
    model_card.write_text("# Card\n{{known_failures}}\n", encoding="utf-8")

    with pytest.raises(PublishingError, match="unresolved"):
        publish_release(
            adapter,
            model_card,
            report,
            "gaialab/adapter-v0.1",
            public=False,
            api=FakeHubApi(),
        )


def test_publish_release_rejects_pending_human_review(tmp_path):
    adapter, model_card, report = make_release_files(tmp_path)
    report.write_text("# Report\nPending human review\n", encoding="utf-8")

    with pytest.raises(PublishingError, match="pending human-review"):
        publish_release(
            adapter,
            model_card,
            report,
            "gaialab/adapter-v0.1",
            public=False,
            api=FakeHubApi(),
        )
