from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from src.review_automation.config import (
    DEFAULT_CONFIG_PATH,
    ReviewAutomationConfigError,
    load_review_config,
)


def test_default_config_is_local_and_external_opt_in_is_disabled() -> None:
    config = load_review_config()
    assert config.default_provider == "local"
    assert not config.external_provider_enabled
    assert config.domain_review_categories == (
        "banking", "healthcare", "government_services"
    )
    assert config.queue_ordering[-1] == "record_id"


def test_environment_can_opt_in_without_reading_or_storing_a_secret() -> None:
    config = load_review_config(environ={
        "GAIALAB_REVIEW_CONFIG": str(DEFAULT_CONFIG_PATH),
        "GAIALAB_REVIEW_PROVIDER": "external",
        "GAIALAB_REVIEW_EXTERNAL_ENABLED": "true",
        "GAIALAB_REVIEW_TIMEOUT_SECONDS": "12",
        "GAIALAB_REVIEW_MAX_RETRIES": "1",
        "SOME_API_KEY": "must-not-be-read",
    })
    assert config.default_provider == "external"
    assert config.external_provider_enabled
    assert config.provider_timeout_seconds == 12
    assert "must-not-be-read" not in repr(config)


def test_external_provider_requires_explicit_opt_in() -> None:
    with pytest.raises(ReviewAutomationConfigError, match="explicit opt-in"):
        load_review_config(environ={
            "GAIALAB_REVIEW_CONFIG": str(DEFAULT_CONFIG_PATH),
            "GAIALAB_REVIEW_PROVIDER": "external",
        })


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("thresholds", "near_duplicate_threshold"), 1.5),
        (("thresholds", "near_duplicate_threshold"), "invalid"),
        (("provider", "maximum_retry_count"), 11),
        (("provider", "maximum_retry_count"), "two"),
        (("provider", "timeout_seconds"), 0),
        (("provider", "external_enabled"), "false"),
    ],
)
def test_invalid_configuration_is_rejected(
    tmp_path: Path, path: tuple[str, str], value: object
) -> None:
    raw = yaml.safe_load(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
    raw[path[0]][path[1]] = value
    config_path = tmp_path / "invalid.yaml"
    config_path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(ReviewAutomationConfigError):
        load_review_config(config_path, environ={})


def test_prompt_template_is_versioned_and_preserves_human_control() -> None:
    prompt = (
        DEFAULT_CONFIG_PATH.parents[1]
        / "evaluation"
        / "review_prompts"
        / "gaialab-review-v1.txt"
    ).read_text(encoding="utf-8")
    assert "prompt_version: gaialab-review-v1" in prompt
    assert "Never change review status" in prompt


def test_governed_queue_order_cannot_be_weakened(tmp_path: Path) -> None:
    raw = yaml.safe_load(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
    raw["queue_ordering"] = ["quality_score", "record_id"]
    config_path = tmp_path / "unsafe-order.yaml"
    config_path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(ReviewAutomationConfigError, match="governed"):
        load_review_config(config_path, environ={})
