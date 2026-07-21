"""Publish a reviewed LoRA adapter package to the Hugging Face Hub."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any


class PublishingError(ValueError):
    """Raised when a release package is incomplete or unsafe to publish."""


def validate_release_files(
    adapter_dir: Path, model_card: Path, evaluation_report: Path
) -> None:
    if not adapter_dir.is_dir():
        raise PublishingError(f"Adapter directory does not exist: {adapter_dir}.")
    if not (adapter_dir / "adapter_config.json").is_file():
        raise PublishingError("Adapter directory is missing adapter_config.json.")
    if not any(
        (adapter_dir / filename).is_file()
        for filename in ("adapter_model.safetensors", "adapter_model.bin")
    ):
        raise PublishingError("Adapter directory is missing adapter weights.")
    if not any(
        (adapter_dir / filename).is_file()
        for filename in ("tokenizer.json", "tokenizer_config.json")
    ):
        raise PublishingError("Adapter directory is missing tokenizer files.")
    if not model_card.is_file():
        raise PublishingError(f"Model card does not exist: {model_card}.")
    card_text = model_card.read_text(encoding="utf-8")
    if "{{" in card_text or "}}" in card_text:
        raise PublishingError("Model card still contains unresolved template placeholders.")
    if not evaluation_report.is_file():
        raise PublishingError(
            f"Human-reviewed evaluation report does not exist: {evaluation_report}."
        )
    report_text = evaluation_report.read_text(encoding="utf-8")
    if "Pending human review" in report_text or "| Pending |" in report_text:
        raise PublishingError(
            "Evaluation report still contains pending human-review placeholders."
        )


def publish_release(
    adapter_dir: Path,
    model_card: Path,
    evaluation_report: Path,
    repo_id: str,
    public: bool,
    api: Any | None = None,
) -> None:
    """Upload adapter, tokenizer, card, and report without logging credentials."""
    validate_release_files(adapter_dir, model_card, evaluation_report)
    if not repo_id.strip() or "/" not in repo_id:
        raise PublishingError("--repo-id must use the form account/repository.")

    if api is None:
        from huggingface_hub import HfApi

        api = HfApi(token=os.getenv("HF_TOKEN") or None)
    api.create_repo(
        repo_id=repo_id,
        repo_type="model",
        private=not public,
        exist_ok=True,
    )
    api.upload_folder(
        repo_id=repo_id,
        repo_type="model",
        folder_path=str(adapter_dir),
        path_in_repo="",
        commit_message="Upload GaiaLab LoRA adapter and tokenizer",
        ignore_patterns=["checkpoint-*", "*.log", "*.csv", "tensorboard/*"],
    )
    api.upload_file(
        repo_id=repo_id,
        repo_type="model",
        path_or_fileobj=str(model_card),
        path_in_repo="README.md",
        commit_message="Add reviewed model card",
    )
    api.upload_file(
        repo_id=repo_id,
        repo_type="model",
        path_or_fileobj=str(evaluation_report),
        path_in_repo=f"evaluation/{evaluation_report.name}",
        commit_message="Add human-reviewed evaluation report",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-id", required=True, help="Hugging Face account/repository")
    parser.add_argument(
        "--adapter-dir",
        type=Path,
        default=Path("outputs/gaialab-adapter-v0.1/best_adapter"),
    )
    parser.add_argument("--model-card", type=Path, required=True)
    parser.add_argument("--evaluation-report", type=Path, required=True)
    parser.add_argument(
        "--public",
        action="store_true",
        help="Create or update a public repository. The default is private.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        publish_release(
            args.adapter_dir,
            args.model_card,
            args.evaluation_report,
            args.repo_id,
            args.public,
        )
    except (ImportError, OSError, PublishingError, RuntimeError, ValueError) as exc:
        print(f"Publishing failed: {exc}", file=sys.stderr)
        return 1
    visibility = "public" if args.public else "private"
    print(f"Published reviewed adapter package to {args.repo_id} ({visibility}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
