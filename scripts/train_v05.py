from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from typing import Any

import torch
from datasets import Dataset
from peft import LoraConfig, get_peft_model
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    DataCollatorForLanguageModeling,
    Trainer,
    TrainingArguments,
    set_seed,
)


BASE_MODEL = "Qwen/Qwen2.5-0.5B-Instruct"
DEFAULT_TRAIN_FILE = Path("data/v0.5/v0.5_training.jsonl")
DEFAULT_OUTPUT_DIR = Path("outputs/gaialab-naija-adapter-v0.5")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Train GaiaLab Naija Assistant v0.5 with LoRA."
    )
    parser.add_argument(
        "--train-file",
        type=Path,
        default=DEFAULT_TRAIN_FILE,
        help="Path to the v0.5 JSONL dataset.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory where the trained LoRA adapter will be saved.",
    )
    parser.add_argument("--epochs", type=float, default=3.0)
    parser.add_argument("--learning-rate", type=float, default=2e-4)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--gradient-accumulation-steps", type=int, default=8)
    parser.add_argument("--max-length", type=int, default=512)
    parser.add_argument("--validation-ratio", type=float, default=0.10)
    parser.add_argument("--seed", type=int, default=42)
    return parser.parse_args()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"Training file not found: {path}")

    records: list[dict[str, Any]] = []

    with path.open("r", encoding="utf-8-sig") as file:
        for line_number, raw_line in enumerate(file, start=1):
            line = raw_line.strip()
            if not line:
                continue

            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Invalid JSON on line {line_number}: {exc.msg}"
                ) from exc

            messages = record.get("messages")
            if not isinstance(messages, list) or not messages:
                raise ValueError(
                    f"Line {line_number}: missing or invalid 'messages'."
                )

            records.append(record)

    if len(records) < 2:
        raise ValueError("At least two training examples are required.")

    return records


def split_records(
    records: list[dict[str, Any]],
    validation_ratio: float,
    seed: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not 0.0 < validation_ratio < 1.0:
        raise ValueError("--validation-ratio must be between 0 and 1.")

    shuffled = records.copy()
    random.Random(seed).shuffle(shuffled)

    validation_size = max(1, round(len(shuffled) * validation_ratio))
    validation_size = min(validation_size, len(shuffled) - 1)

    validation_records = shuffled[:validation_size]
    training_records = shuffled[validation_size:]
    return training_records, validation_records


def main() -> int:
    args = parse_args()
    set_seed(args.seed)

    print()
    print("GaiaLab Naija Assistant v0.5 LoRA Training")
    print("=" * 58)
    print(f"Base model        : {BASE_MODEL}")
    print(f"Dataset           : {args.train_file}")
    print(f"Output directory  : {args.output_dir}")
    print(f"Device            : {'CUDA' if torch.cuda.is_available() else 'CPU'}")

    records = load_jsonl(args.train_file)
    train_records, validation_records = split_records(
        records,
        args.validation_ratio,
        args.seed,
    )

    print(f"Total examples    : {len(records)}")
    print(f"Training examples : {len(train_records)}")
    print(f"Validation examples: {len(validation_records)}")
    print()

    tokenizer = AutoTokenizer.from_pretrained(
        BASE_MODEL,
        use_fast=True,
        trust_remote_code=True,
    )

    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    model = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL,
        torch_dtype=torch.float32,
        trust_remote_code=True,
        low_cpu_mem_usage=True,
    )

    model.config.use_cache = False

    lora_config = LoraConfig(
        r=16,
        lora_alpha=32,
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM",
        target_modules=[
            "q_proj",
            "k_proj",
            "v_proj",
            "o_proj",
            "gate_proj",
            "up_proj",
            "down_proj",
        ],
    )

    model = get_peft_model(model, lora_config)
    model.print_trainable_parameters()

    def format_record(record: dict[str, Any]) -> dict[str, str]:
        text = tokenizer.apply_chat_template(
            record["messages"],
            tokenize=False,
            add_generation_prompt=False,
        )
        return {"text": text}

    train_dataset = Dataset.from_list(train_records).map(format_record)
    validation_dataset = Dataset.from_list(validation_records).map(format_record)

    def tokenize_batch(batch: dict[str, list[str]]) -> dict[str, Any]:
        return tokenizer(
            batch["text"],
            truncation=True,
            max_length=args.max_length,
            padding=False,
        )

    train_dataset = train_dataset.map(
        tokenize_batch,
        batched=True,
        remove_columns=train_dataset.column_names,
    )
    validation_dataset = validation_dataset.map(
        tokenize_batch,
        batched=True,
        remove_columns=validation_dataset.column_names,
    )

    data_collator = DataCollatorForLanguageModeling(
        tokenizer=tokenizer,
        mlm=False,
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)

    training_args = TrainingArguments(
        output_dir=str(args.output_dir),
        num_train_epochs=args.epochs,
        per_device_train_batch_size=args.batch_size,
        per_device_eval_batch_size=1,
        gradient_accumulation_steps=args.gradient_accumulation_steps,
        learning_rate=args.learning_rate,
        warmup_ratio=0.05,
        weight_decay=0.01,
        logging_steps=1,
        eval_strategy="epoch",
        save_strategy="epoch",
        save_total_limit=2,
        load_best_model_at_end=True,
        metric_for_best_model="eval_loss",
        greater_is_better=False,
        report_to="none",
        fp16=False,
        bf16=False,
        dataloader_pin_memory=False,
        optim="adamw_torch",
        seed=args.seed,
        data_seed=args.seed,
        remove_unused_columns=False,
    )

    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=train_dataset,
        eval_dataset=validation_dataset,
        data_collator=data_collator,
    )

    print("Starting training. CPU training may take a while.")
    print()

    train_result = trainer.train()

    trainer.save_model(str(args.output_dir))
    tokenizer.save_pretrained(str(args.output_dir))

    metrics = dict(train_result.metrics)
    metrics["total_examples"] = len(records)
    metrics["training_examples"] = len(train_records)
    metrics["validation_examples"] = len(validation_records)

    metrics_file = args.output_dir / "training_metrics.json"
    metrics_file.write_text(
        json.dumps(metrics, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print()
    print("=" * 58)
    print("TRAINING COMPLETE")
    print("=" * 58)
    print(f"Adapter saved to : {args.output_dir}")
    print(f"Metrics saved to : {metrics_file}")
    print()
    print("Do not publish yet. Run evaluation and benchmark first.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
