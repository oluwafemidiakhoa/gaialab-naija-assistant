"""Train a governed LoRA adapter after validating immutable release evidence."""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.governed_training import (  # noqa: E402
    GovernedTrainingError,
    assert_release_identity,
    assert_output_isolated,
    build_training_manifest,
    cuda_information,
    deterministic_order,
    load_yaml_config,
    prepare_output_directory,
    require_execution_hardware,
    serializable_arguments,
    tokenize_supervised_record,
    validate_training_bundle,
    write_new_json,
)

DEFAULT_CONFIG = ROOT / "configs" / "training" / "v0.7.0-rc.3.yaml"
DEFAULT_BASE_MODEL = "Qwen/Qwen2.5-0.5B-Instruct"


def _config_defaults(path: Path) -> dict[str, Any]:
    config = load_yaml_config(path)
    defaults: dict[str, Any] = {}
    for section in ("dataset", "model", "training", "lora", "output", "hub"):
        value = config.get(section, {})
        if not isinstance(value, dict):
            raise GovernedTrainingError(
                f"configuration section {section!r} must be a mapping"
            )
        defaults.update(value)
    defaults["release_version"] = config.get("release_version", "unknown")
    return defaults


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    preliminary = argparse.ArgumentParser(add_help=False)
    preliminary.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    known, _ = preliminary.parse_known_args(argv)
    defaults = _config_defaults(known.config)

    parser = argparse.ArgumentParser(description=__doc__, parents=[preliminary])
    parser.add_argument("--train-file", type=Path, default=defaults.get("train_file"))
    parser.add_argument(
        "--release-version",
        default=defaults["release_version"],
    )
    parser.add_argument(
        "--validation-file",
        type=Path,
        default=defaults.get("validation_file"),
    )
    parser.add_argument("--output-dir", type=Path, default=defaults.get("output_dir"))
    parser.add_argument(
        "--base-model",
        default=defaults.get("base_model", DEFAULT_BASE_MODEL),
    )
    parser.add_argument(
        "--base-model-revision",
        default=defaults.get("base_model_revision"),
    )
    parser.add_argument(
        "--max-seq-length",
        type=int,
        default=defaults.get("max_seq_length", 512),
    )
    parser.add_argument("--epochs", type=float, default=defaults.get("epochs", 3.0))
    parser.add_argument(
        "--max-steps",
        type=int,
        default=defaults.get("max_steps", -1),
        help="Positive value overrides epochs; -1 uses epochs.",
    )
    parser.add_argument(
        "--learning-rate",
        type=float,
        default=defaults.get("learning_rate", 2e-4),
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=defaults.get("batch_size", 1),
    )
    parser.add_argument(
        "--gradient-accumulation-steps",
        type=int,
        default=defaults.get("gradient_accumulation_steps", 8),
    )
    parser.add_argument("--seed", type=int, default=defaults.get("seed", 42))
    parser.add_argument("--lora-r", type=int, default=defaults.get("lora_r", 16))
    parser.add_argument(
        "--lora-alpha",
        type=int,
        default=defaults.get("lora_alpha", 32),
    )
    parser.add_argument(
        "--lora-dropout",
        type=float,
        default=defaults.get("lora_dropout", 0.05),
    )
    parser.add_argument(
        "--warmup-ratio",
        type=float,
        default=defaults.get("warmup_ratio", 0.05),
    )
    parser.add_argument(
        "--logging-steps",
        type=int,
        default=defaults.get("logging_steps", 1),
    )
    parser.add_argument(
        "--save-steps",
        type=int,
        default=defaults.get("save_steps", 25),
    )
    parser.add_argument(
        "--eval-steps",
        type=int,
        default=defaults.get("eval_steps", 25),
    )
    parser.add_argument("--resume-from-checkpoint", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument("--overwrite-output-dir", action="store_true")
    parser.add_argument("--push-to-hub", action="store_true")
    parser.add_argument(
        "--hub-model-id",
        default=defaults.get("hub_model_id"),
    )
    parser.set_defaults(
        target_modules=defaults.get(
            "target_modules",
            ["q_proj", "k_proj", "v_proj", "o_proj"],
        ),
    )
    args = parser.parse_args(argv)
    if (
        args.train_file is None
        or args.validation_file is None
        or args.output_dir is None
    ):
        parser.error("train file, validation file, and output directory are required")
    if args.push_to_hub and not args.hub_model_id:
        parser.error("--hub-model-id is required with --push-to-hub")
    return args


def validate_hyperparameters(args: argparse.Namespace) -> None:
    incompatible = (
        (args.dry_run and args.smoke_test, "--dry-run and --smoke-test"),
        (args.dry_run and args.push_to_hub, "--dry-run and --push-to-hub"),
        (
            args.dry_run and args.resume_from_checkpoint is not None,
            "--dry-run and --resume-from-checkpoint",
        ),
        (args.smoke_test and args.push_to_hub, "--smoke-test and --push-to-hub"),
    )
    for invalid, labels in incompatible:
        if invalid:
            raise GovernedTrainingError(f"{labels} are mutually exclusive")
    positive = {
        "max_seq_length": args.max_seq_length,
        "epochs": args.epochs,
        "learning_rate": args.learning_rate,
        "batch_size": args.batch_size,
        "gradient_accumulation_steps": args.gradient_accumulation_steps,
        "lora_r": args.lora_r,
        "lora_alpha": args.lora_alpha,
        "logging_steps": args.logging_steps,
        "save_steps": args.save_steps,
        "eval_steps": args.eval_steps,
    }
    invalid = [name for name, value in positive.items() if value <= 0]
    if invalid:
        raise GovernedTrainingError(
            f"hyperparameters must be positive: {', '.join(sorted(invalid))}"
        )
    if args.max_steps == 0 or args.max_steps < -1:
        raise GovernedTrainingError("max_steps must be -1 or a positive integer")
    if not 0 <= args.lora_dropout < 1:
        raise GovernedTrainingError("lora_dropout must be in [0, 1)")
    if not 0 <= args.warmup_ratio < 1:
        raise GovernedTrainingError("warmup_ratio must be in [0, 1)")
    if not isinstance(args.target_modules, list) or not args.target_modules:
        raise GovernedTrainingError("target_modules must be a non-empty list")


def _set_seed(seed: int) -> None:
    os.environ["PYTHONHASHSEED"] = str(seed)
    random.seed(seed)
    try:
        import numpy

        numpy.random.seed(seed)
    except ImportError:
        pass
    import torch
    from transformers import set_seed

    set_seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


class SupervisedCollator:
    """Pad causal-LM batches while preserving prompt-masked labels."""

    def __init__(self, tokenizer: Any) -> None:
        self.tokenizer = tokenizer

    def __call__(self, features: list[dict[str, list[int]]]) -> dict[str, Any]:
        import torch

        maximum = max(len(feature["input_ids"]) for feature in features)
        pad_id = self.tokenizer.pad_token_id
        input_ids: list[list[int]] = []
        attention_mask: list[list[int]] = []
        labels: list[list[int]] = []
        for feature in features:
            padding = maximum - len(feature["input_ids"])
            input_ids.append(feature["input_ids"] + [pad_id] * padding)
            attention_mask.append(feature["attention_mask"] + [0] * padding)
            labels.append(feature["labels"] + [-100] * padding)
        return {
            "input_ids": torch.tensor(input_ids, dtype=torch.long),
            "attention_mask": torch.tensor(attention_mask, dtype=torch.long),
            "labels": torch.tensor(labels, dtype=torch.long),
        }


def _attempt_artifact_path(
    output_dir: Path,
    filename: str,
    resume_from_checkpoint: Path | None,
) -> Path:
    """Keep every resume attempt's manifest and metrics immutable."""
    initial = output_dir / filename
    if not initial.exists():
        return initial
    if resume_from_checkpoint is None:
        raise GovernedTrainingError(f"refusing to overwrite run artefact: {initial}")
    suffix = resume_from_checkpoint.name.replace("/", "_").replace("\\", "_")
    stem = Path(filename).stem
    return output_dir / f"{stem}.resume-{suffix}.json"


def _training_stack(
    args: argparse.Namespace,
    train_records: tuple[dict[str, Any], ...],
    validation_records: tuple[dict[str, Any], ...],
) -> tuple[Any, Any, Any, dict[str, Any], str | None]:
    import torch
    from datasets import Dataset
    from peft import LoraConfig, get_peft_model
    from transformers import (
        AutoModelForCausalLM,
        AutoTokenizer,
        Trainer,
        TrainingArguments,
    )

    _set_seed(args.seed)
    tokenizer = AutoTokenizer.from_pretrained(
        args.base_model,
        revision=args.base_model_revision,
        use_fast=True,
        trust_remote_code=False,
    )
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token

    supports_bf16 = bool(torch.cuda.is_bf16_supported())
    dtype = torch.bfloat16 if supports_bf16 else torch.float16
    model = AutoModelForCausalLM.from_pretrained(
        args.base_model,
        revision=args.base_model_revision,
        torch_dtype=dtype,
        trust_remote_code=False,
        low_cpu_mem_usage=True,
    )
    resolved_revision = (
        getattr(model.config, "_commit_hash", None) or args.base_model_revision
    )
    model.config.use_cache = False
    model.gradient_checkpointing_enable()
    if hasattr(model, "enable_input_require_grads"):
        model.enable_input_require_grads()

    lora_config = LoraConfig(
        r=args.lora_r,
        lora_alpha=args.lora_alpha,
        lora_dropout=args.lora_dropout,
        bias="none",
        task_type="CAUSAL_LM",
        target_modules=args.target_modules,
    )
    model = get_peft_model(model, lora_config)

    train_order = deterministic_order(train_records, args.seed)
    validation_order = sorted(validation_records, key=lambda record: record["id"])
    train_dataset = Dataset.from_list(
        [
            tokenize_supervised_record(tokenizer, record, args.max_seq_length)
            for record in train_order
        ]
    )
    validation_dataset = Dataset.from_list(
        [
            tokenize_supervised_record(tokenizer, record, args.max_seq_length)
            for record in validation_order
        ]
    )

    effective_max_steps = 5 if args.smoke_test else args.max_steps
    training_arguments = TrainingArguments(
        output_dir=str(args.output_dir),
        overwrite_output_dir=False,
        num_train_epochs=args.epochs,
        max_steps=effective_max_steps,
        per_device_train_batch_size=args.batch_size,
        per_device_eval_batch_size=args.batch_size,
        gradient_accumulation_steps=args.gradient_accumulation_steps,
        learning_rate=args.learning_rate,
        warmup_ratio=args.warmup_ratio,
        logging_steps=args.logging_steps,
        save_steps=args.save_steps,
        eval_steps=args.eval_steps,
        save_strategy="steps",
        eval_strategy="steps",
        save_total_limit=3,
        load_best_model_at_end=True,
        metric_for_best_model="eval_loss",
        greater_is_better=False,
        report_to="none",
        bf16=supports_bf16,
        fp16=not supports_bf16,
        optim="adamw_torch",
        seed=args.seed,
        data_seed=args.seed,
        remove_unused_columns=False,
        gradient_checkpointing=True,
    )
    trainer = Trainer(
        model=model,
        args=training_arguments,
        train_dataset=train_dataset,
        eval_dataset=validation_dataset,
        data_collator=SupervisedCollator(tokenizer),
    )
    return (
        trainer,
        model,
        tokenizer,
        {
            "r": args.lora_r,
            "alpha": args.lora_alpha,
            "dropout": args.lora_dropout,
            "target_modules": args.target_modules,
            "bias": "none",
            "task_type": "CAUSAL_LM",
        },
        resolved_revision,
    )


def run(args: argparse.Namespace) -> dict[str, Any]:
    validate_hyperparameters(args)
    bundle = validate_training_bundle(args.train_file, args.validation_file)
    assert_release_identity(args.release_version, bundle.candidate_evidence)
    assert_output_isolated(
        args.output_dir,
        (args.train_file, args.validation_file),
    )
    cuda = cuda_information()
    execution_mode = require_execution_hardware(
        dry_run=args.dry_run,
        smoke_test=args.smoke_test,
        cuda=cuda,
    )
    backup = prepare_output_directory(
        args.output_dir,
        overwrite=args.overwrite_output_dir,
        resume_from_checkpoint=args.resume_from_checkpoint,
    )
    lora = {
        "r": args.lora_r,
        "alpha": args.lora_alpha,
        "dropout": args.lora_dropout,
        "target_modules": args.target_modules,
        "bias": "none",
        "task_type": "CAUSAL_LM",
    }
    resolved = serializable_arguments(vars(args))
    resolved["execution_mode"] = execution_mode

    if args.dry_run or execution_mode == "cpu_smoke_validation_only":
        status = "dry_run_validated" if args.dry_run else "cpu_smoke_validation_only"
        manifest = build_training_manifest(
            root=ROOT,
            release_version=args.release_version,
            base_model=args.base_model,
            base_model_revision=args.base_model_revision,
            train_file=args.train_file,
            validation_file=args.validation_file,
            bundle=bundle,
            resolved_arguments=resolved,
            lora_configuration=lora,
            seed=args.seed,
            status=status,
            cuda=cuda,
            backup_path=backup,
        )
        write_new_json(
            _attempt_artifact_path(
                args.output_dir,
                "training_manifest.json",
                args.resume_from_checkpoint,
            ),
            manifest,
        )
        return manifest

    trainer: Any | None = None
    resolved_revision = args.base_model_revision
    status = "training_started"
    metrics: dict[str, Any] = {}
    try:
        trainer, model, tokenizer, lora, resolved_revision = _training_stack(
            args,
            bundle.train_records,
            bundle.validation_records,
        )
        result = trainer.train(
            resume_from_checkpoint=(
                str(args.resume_from_checkpoint)
                if args.resume_from_checkpoint is not None
                else None
            )
        )
        evaluation = trainer.evaluate()
        adapter_dir = args.output_dir / "adapter"
        model.save_pretrained(adapter_dir, safe_serialization=True)
        tokenizer.save_pretrained(adapter_dir)
        metrics = {
            key: value
            for key, value in {**result.metrics, **evaluation}.items()
            if isinstance(value, (int, float)) and math.isfinite(value)
        }
        write_new_json(
            _attempt_artifact_path(
                args.output_dir,
                "training_metrics.json",
                args.resume_from_checkpoint,
            ),
            metrics,
        )
        if args.push_to_hub:
            model.push_to_hub(args.hub_model_id, safe_serialization=True)
            tokenizer.push_to_hub(args.hub_model_id)
        status = "smoke_test_completed" if args.smoke_test else "training_completed"
    except Exception:
        status = "training_failed"
        raise
    finally:
        checkpoints = sorted(
            str(path) for path in args.output_dir.glob("checkpoint-*") if path.is_dir()
        )
        metrics_value: Mapping[str, Any] = (
            metrics if status != "training_failed" else {}
        )
        manifest = build_training_manifest(
            root=ROOT,
            release_version=args.release_version,
            base_model=args.base_model,
            base_model_revision=resolved_revision,
            train_file=args.train_file,
            validation_file=args.validation_file,
            bundle=bundle,
            resolved_arguments=resolved,
            lora_configuration=lora,
            seed=args.seed,
            status=status,
            cuda=cuda,
            metrics=metrics_value,
            checkpoints=checkpoints,
            backup_path=backup,
        )
        write_new_json(
            _attempt_artifact_path(
                args.output_dir,
                "training_manifest.json",
                args.resume_from_checkpoint,
            ),
            manifest,
        )
    return manifest


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        manifest = run(args)
    except Exception as exc:
        print(
            f"Governed training refused ({type(exc).__name__}): {exc}",
            file=sys.stderr,
        )
        return 1
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
