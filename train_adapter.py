"""Train GaiaLab Adapter v0.1 with LoRA. Training starts only from the CLI."""

from __future__ import annotations

import argparse
import csv
import json
import logging
import shutil
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from src.validate_dataset import read_jsonl, split_records, validate_records

try:
    from transformers import TrainerCallback as _TrainerCallbackBase
except ImportError:  # Lightweight validation and unit tests do not require Transformers.
    class _TrainerCallbackBase:
        pass

DEFAULT_CONFIG_PATH = Path("training/default_config.yaml")
DEFAULT_OUTPUT_DIR = Path("outputs/gaialab-adapter-v0.1")
MAX_SEQUENCE_LENGTH = 1024
SYSTEM_PROMPT = (
    "You are GaiaLab Naija Assistant, an experimental assistant for Nigerian "
    "small-business owners. Be clear, respectful, practical, and do not invent facts."
)
REQUIRED_CONFIG_FIELDS = {
    "model",
    "dataset",
    "learning_rate",
    "epochs",
    "batch_size",
    "gradient_accumulation",
    "lora_rank",
    "lora_alpha",
    "target_modules",
    "evaluation_frequency",
    "seed",
}


class TrainingConfigurationError(ValueError):
    """Raised when adapter training configuration is invalid."""


@dataclass(frozen=True)
class AdapterTrainingConfig:
    model: str
    dataset: str
    learning_rate: float
    epochs: int
    batch_size: int
    gradient_accumulation: int
    lora_rank: int
    lora_alpha: int
    target_modules: list[str]
    evaluation_frequency: int
    seed: int


def _positive_integer(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise TrainingConfigurationError(f"'{field}' must be a positive integer.")
    return value


def _nonnegative_integer(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise TrainingConfigurationError(f"'{field}' must be a non-negative integer.")
    return value


def load_training_config(path: Path) -> AdapterTrainingConfig:
    """Load and strictly validate the versioned YAML configuration."""
    with path.open(encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)
    if not isinstance(raw, dict):
        raise TrainingConfigurationError("Training configuration must be a YAML map.")

    missing = sorted(REQUIRED_CONFIG_FIELDS.difference(raw))
    unexpected = sorted(set(raw).difference(REQUIRED_CONFIG_FIELDS))
    if missing:
        raise TrainingConfigurationError(
            f"Missing training configuration field(s): {', '.join(missing)}."
        )
    if unexpected:
        raise TrainingConfigurationError(
            f"Unexpected training configuration field(s): {', '.join(unexpected)}."
        )
    for field in ("model", "dataset"):
        if not isinstance(raw[field], str) or not raw[field].strip():
            raise TrainingConfigurationError(f"'{field}' must be a non-empty string.")

    learning_rate = raw["learning_rate"]
    if (
        isinstance(learning_rate, bool)
        or not isinstance(learning_rate, (int, float))
        or not 0 < float(learning_rate) < 1
    ):
        raise TrainingConfigurationError(
            "'learning_rate' must be a number greater than 0 and less than 1."
        )
    modules = raw["target_modules"]
    if (
        not isinstance(modules, list)
        or not modules
        or any(not isinstance(module, str) or not module.strip() for module in modules)
    ):
        raise TrainingConfigurationError(
            "'target_modules' must be a non-empty list of non-empty strings."
        )

    config = AdapterTrainingConfig(
        model=raw["model"].strip(),
        dataset=raw["dataset"].strip(),
        learning_rate=float(learning_rate),
        epochs=_positive_integer(raw["epochs"], "epochs"),
        batch_size=_positive_integer(raw["batch_size"], "batch_size"),
        gradient_accumulation=_positive_integer(
            raw["gradient_accumulation"], "gradient_accumulation"
        ),
        lora_rank=_positive_integer(raw["lora_rank"], "lora_rank"),
        lora_alpha=_positive_integer(raw["lora_alpha"], "lora_alpha"),
        target_modules=[module.strip() for module in modules],
        evaluation_frequency=_positive_integer(
            raw["evaluation_frequency"], "evaluation_frequency"
        ),
        seed=_nonnegative_integer(raw["seed"], "seed"),
    )
    if config.evaluation_frequency != 1:
        raise TrainingConfigurationError(
            "GaiaLab Adapter v0.1 requires evaluation_frequency: 1 so validation "
            "runs after every epoch."
        )
    return config


def find_latest_checkpoint(output_dir: Path) -> Path | None:
    """Return the highest numbered complete Trainer checkpoint, if present."""
    checkpoints: list[tuple[int, Path]] = []
    if not output_dir.exists():
        return None
    for path in output_dir.glob("checkpoint-*"):
        if not path.is_dir():
            continue
        try:
            step = int(path.name.removeprefix("checkpoint-"))
        except ValueError:
            continue
        if (path / "trainer_state.json").is_file():
            checkpoints.append((step, path))
    return max(checkpoints, default=(0, None), key=lambda item: item[0])[1]


def resolve_resume_checkpoint(value: str | None, output_dir: Path) -> str | None:
    if value is None:
        return None
    if value == "auto":
        checkpoint = find_latest_checkpoint(output_dir)
        if checkpoint is None:
            raise TrainingConfigurationError(
                f"No complete checkpoint was found under {output_dir}."
            )
        return str(checkpoint)
    checkpoint = Path(value)
    if not checkpoint.is_dir() or not (checkpoint / "trainer_state.json").is_file():
        raise TrainingConfigurationError(
            f"Resume checkpoint is missing or incomplete: {checkpoint}."
        )
    return str(checkpoint)


class CsvMetricsCallback(_TrainerCallbackBase):
    """Append Trainer log events to a stable CSV file."""

    fieldnames = (
        "timestamp_utc",
        "step",
        "epoch",
        "split",
        "loss",
        "eval_loss",
        "learning_rate",
        "grad_norm",
        "eval_runtime",
        "eval_samples_per_second",
    )

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            with self.path.open("w", encoding="utf-8", newline="") as handle:
                csv.DictWriter(handle, fieldnames=self.fieldnames).writeheader()

    def on_log(self, args, state, control, logs=None, **kwargs):
        if not logs:
            return control
        row = {field: logs.get(field, "") for field in self.fieldnames}
        row["timestamp_utc"] = datetime.now(timezone.utc).isoformat()
        row["step"] = state.global_step
        row["epoch"] = logs.get("epoch", state.epoch)
        row["split"] = "evaluation" if "eval_loss" in logs else "training"
        with self.path.open("a", encoding="utf-8", newline="") as handle:
            csv.DictWriter(handle, fieldnames=self.fieldnames).writerow(row)
        return control


def configure_logging(output_dir: Path) -> logging.Logger:
    output_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("gaialab.training")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    for handler in (
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(output_dir / "training.log", encoding="utf-8"),
    ):
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    return logger


def load_split_records(config: AdapterTrainingConfig):
    records, report = validate_records(read_jsonl(Path(config.dataset)))
    train_records, validation_records = split_records(records, seed=config.seed)
    return train_records, validation_records, report


def _messages(record: dict[str, str]) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    user_content = record["instruction"]
    if record["input"].strip():
        user_content += f"\n\nContext:\n{record['input'].strip()}"
    prompt = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]
    complete = [*prompt, {"role": "assistant", "content": record["output"]}]
    return prompt, complete


def prepare_datasets(train_records, validation_records, tokenizer):
    """Tokenize examples and mask prompt tokens from the training loss."""
    from datasets import Dataset, DatasetDict

    def tokenize(record):
        prompt_messages, complete_messages = _messages(record)
        prompt_text = tokenizer.apply_chat_template(
            prompt_messages, tokenize=False, add_generation_prompt=True
        )
        complete_text = tokenizer.apply_chat_template(
            complete_messages, tokenize=False, add_generation_prompt=False
        )
        prompt_ids = tokenizer(
            prompt_text,
            truncation=True,
            max_length=MAX_SEQUENCE_LENGTH,
            add_special_tokens=False,
        )["input_ids"]
        encoded = tokenizer(
            complete_text,
            truncation=True,
            max_length=MAX_SEQUENCE_LENGTH,
            add_special_tokens=False,
        )
        labels = list(encoded["input_ids"])
        for index in range(min(len(prompt_ids), len(labels))):
            labels[index] = -100
        return {**encoded, "labels": labels}

    prepared = {}
    for name, records in (
        ("train", train_records),
        ("validation", validation_records),
    ):
        dataset = Dataset.from_list(records)
        tokenized = dataset.map(tokenize, remove_columns=dataset.column_names)
        tokenized = tokenized.filter(lambda row: any(label != -100 for label in row["labels"]))
        if not tokenized:
            raise TrainingConfigurationError(
                f"The {name} split has no assistant tokens after truncation."
            )
        prepared[name] = tokenized
    return DatasetDict(prepared)


def train(config: AdapterTrainingConfig, output_dir: Path, resume: str | None, patience: int):
    import torch

    if not torch.cuda.is_available():
        raise RuntimeError("LoRA training requires a CUDA GPU. Use Kaggle or Colab.")

    from peft import LoraConfig, get_peft_model
    from transformers import (
        AutoModelForCausalLM,
        AutoTokenizer,
        DataCollatorForSeq2Seq,
        EarlyStoppingCallback,
        Trainer,
        TrainingArguments,
        set_seed,
    )

    logger = configure_logging(output_dir)
    set_seed(config.seed)
    train_records, validation_records, report = load_split_records(config)
    logger.info("Validated %d unique dataset records.", report.valid_records)

    tokenizer = AutoTokenizer.from_pretrained(config.model, use_fast=True)
    tokenizer.truncation_side = "right"
    if tokenizer.pad_token is None:
        if tokenizer.eos_token is None:
            raise TrainingConfigurationError(
                "Tokenizer has no pad token or end-of-sequence token."
            )
        tokenizer.pad_token = tokenizer.eos_token
    datasets = prepare_datasets(train_records, validation_records, tokenizer)

    compute_dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
    base_model = AutoModelForCausalLM.from_pretrained(
        config.model,
        torch_dtype=compute_dtype,
    )
    base_model.config.use_cache = False
    base_model.enable_input_require_grads()
    model = get_peft_model(
        base_model,
        LoraConfig(
            r=config.lora_rank,
            lora_alpha=config.lora_alpha,
            lora_dropout=0.05,
            bias="none",
            task_type="CAUSAL_LM",
            target_modules=config.target_modules,
        ),
    )

    metrics_path = output_dir / "metrics.csv"
    arguments = TrainingArguments(
        output_dir=str(output_dir),
        num_train_epochs=config.epochs,
        per_device_train_batch_size=config.batch_size,
        per_device_eval_batch_size=config.batch_size,
        gradient_accumulation_steps=config.gradient_accumulation,
        gradient_checkpointing=True,
        learning_rate=config.learning_rate,
        eval_strategy="epoch",
        save_strategy="epoch",
        logging_strategy="steps",
        logging_steps=1,
        save_total_limit=2,
        load_best_model_at_end=True,
        metric_for_best_model="eval_loss",
        greater_is_better=False,
        bf16=compute_dtype == torch.bfloat16,
        fp16=compute_dtype == torch.float16,
        report_to=["tensorboard"],
        logging_dir=str(output_dir / "tensorboard"),
        seed=config.seed,
        data_seed=config.seed,
    )
    trainer = Trainer(
        model=model,
        args=arguments,
        train_dataset=datasets["train"],
        eval_dataset=datasets["validation"],
        data_collator=DataCollatorForSeq2Seq(
            tokenizer=tokenizer,
            model=model,
            label_pad_token_id=-100,
            pad_to_multiple_of=8,
        ),
        callbacks=[
            CsvMetricsCallback(metrics_path),
            EarlyStoppingCallback(early_stopping_patience=patience),
        ],
    )
    logger.info("Starting training with model %s.", config.model)
    result = trainer.train(resume_from_checkpoint=resume)

    best_adapter_dir = output_dir / "best_adapter"
    if best_adapter_dir.exists():
        shutil.rmtree(best_adapter_dir)
    trainer.model.save_pretrained(best_adapter_dir, safe_serialization=True)
    tokenizer.save_pretrained(best_adapter_dir)
    trainer.save_state()
    summary = {
        "base_model": config.model,
        "dataset": config.dataset,
        "dataset_records": report.valid_records,
        "train_records": len(datasets["train"]),
        "validation_records": len(datasets["validation"]),
        "best_checkpoint": trainer.state.best_model_checkpoint,
        "best_metric": trainer.state.best_metric,
        "global_step": trainer.state.global_step,
        "train_metrics": result.metrics,
        "human_evaluation_completed": False,
    }
    (output_dir / "training_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (output_dir / "resolved_config.yaml").write_text(
        yaml.safe_dump(asdict(config), sort_keys=False), encoding="utf-8"
    )
    logger.info("Best adapter saved to %s.", best_adapter_dir)
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--resume-from-checkpoint",
        nargs="?",
        const="auto",
        help="Resume from a checkpoint path, or use the latest checkpoint when omitted.",
    )
    parser.add_argument("--early-stopping-patience", type=int, default=2)
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate configuration and dataset without loading a model or training.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.early_stopping_patience < 1:
            raise TrainingConfigurationError(
                "--early-stopping-patience must be a positive integer."
            )
        config = load_training_config(args.config)
        train_records, validation_records, report = load_split_records(config)
        if args.validate_only:
            print(
                json.dumps(
                    {
                        "model": config.model,
                        "dataset": config.dataset,
                        "valid_records": report.valid_records,
                        "train_records": len(train_records),
                        "validation_records": len(validation_records),
                        "training_started": False,
                    },
                    indent=2,
                )
            )
            return 0
        resume = resolve_resume_checkpoint(args.resume_from_checkpoint, args.output_dir)
        train(config, args.output_dir, resume, args.early_stopping_patience)
    except (ImportError, OSError, RuntimeError, TrainingConfigurationError, ValueError) as exc:
        print(f"Adapter training failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
