from __future__ import annotations

import argparse
import json
from pathlib import Path

import torch
from datasets import Dataset
from peft import LoraConfig, get_peft_model
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    DataCollatorForLanguageModeling,
    Trainer,
    TrainingArguments,
)


BASE_MODEL = "Qwen/Qwen2.5-0.5B-Instruct"
DEFAULT_TRAIN_FILE = Path("data/v0.4/v0.4_training.jsonl")
DEFAULT_VALIDATION_FILE = Path("data/v0.4/v0.4_validation.jsonl")
DEFAULT_OUTPUT_DIR = Path("outputs/gaialab-naija-adapter-v0.4")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fine-tune GaiaLab Naija Assistant v0.4 with LoRA."
    )

    parser.add_argument(
        "--train-file",
        type=Path,
        default=DEFAULT_TRAIN_FILE,
    )
    parser.add_argument(
        "--validation-file",
        type=Path,
        default=DEFAULT_VALIDATION_FILE,
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
    )
    parser.add_argument(
        "--epochs",
        type=float,
        default=5.0,
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=1,
    )
    parser.add_argument(
        "--gradient-accumulation-steps",
        type=int,
        default=8,
    )
    parser.add_argument(
        "--learning-rate",
        type=float,
        default=2e-4,
    )
    parser.add_argument(
        "--max-length",
        type=int,
        default=512,
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        default=-1,
        help="Use a small positive number such as 2 for a smoke test.",
    )

    return parser.parse_args()


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        raise FileNotFoundError(f"Dataset file was not found: {path}")

    records: list[dict] = []

    with path.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            line = line.strip()

            if not line:
                continue

            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Invalid JSON in {path} at line {line_number}: {exc}"
                ) from exc

            messages = record.get("messages")

            if not isinstance(messages, list) or not messages:
                raise ValueError(
                    f"Missing or invalid messages in {path} at line {line_number}"
                )

            records.append(record)

    if not records:
        raise ValueError(f"No examples were loaded from {path}")

    return records


def build_dataset(
    records: list[dict],
    tokenizer: AutoTokenizer,
    max_length: int,
) -> Dataset:
    formatted_records = []

    for record in records:
        text = tokenizer.apply_chat_template(
            record["messages"],
            tokenize=False,
            add_generation_prompt=False,
        )

        formatted_records.append(
            {
                "id": record["id"],
                "category": record["category"],
                "risk_level": record["risk_level"],
                "text": text,
            }
        )

    dataset = Dataset.from_list(formatted_records)

    def tokenize(batch: dict) -> dict:
        return tokenizer(
            batch["text"],
            truncation=True,
            max_length=max_length,
            padding=False,
        )

    return dataset.map(
        tokenize,
        batched=True,
        remove_columns=dataset.column_names,
    )


def main() -> None:
    args = parse_args()

    device_name = "cuda" if torch.cuda.is_available() else "cpu"

    print("=" * 70)
    print("GaiaLab Naija Assistant v0.4 Training")
    print(f"Base model: {BASE_MODEL}")
    print(f"Device: {device_name}")
    print(f"Training file: {args.train_file}")
    print(f"Validation file: {args.validation_file}")
    print(f"Output directory: {args.output_dir}")
    print("=" * 70)

    train_records = load_jsonl(args.train_file)
    validation_records = load_jsonl(args.validation_file)

    print(f"Training examples: {len(train_records)}")
    print(f"Validation examples: {len(validation_records)}")

    tokenizer = AutoTokenizer.from_pretrained(
        BASE_MODEL,
        trust_remote_code=True,
    )

    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    model_kwargs = {
        "trust_remote_code": True,
    }

    if torch.cuda.is_available():
        model_kwargs["torch_dtype"] = torch.float16
    else:
        model_kwargs["torch_dtype"] = torch.float32

    model = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL,
        **model_kwargs,
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

    train_dataset = build_dataset(
        train_records,
        tokenizer,
        args.max_length,
    )

    validation_dataset = build_dataset(
        validation_records,
        tokenizer,
        args.max_length,
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)

    use_fp16 = torch.cuda.is_available()

    training_args = TrainingArguments(
        output_dir=str(args.output_dir),
        num_train_epochs=args.epochs,
        max_steps=args.max_steps,
        per_device_train_batch_size=args.batch_size,
        per_device_eval_batch_size=1,
        gradient_accumulation_steps=args.gradient_accumulation_steps,
        learning_rate=args.learning_rate,
        warmup_ratio=0.1,
        weight_decay=0.01,
        logging_steps=1,
        save_strategy="epoch",
        eval_strategy="epoch",
        save_total_limit=2,
        load_best_model_at_end=True,
        load_best_model_at_end=True,
        report_to="none",
        fp16=use_fp16,
        dataloader_pin_memory=use_fp16,
        seed=42,
    )

    data_collator = DataCollatorForLanguageModeling(
        tokenizer=tokenizer,
        mlm=False,
    )

    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=train_dataset,
        eval_dataset=validation_dataset,
        data_collator=data_collator,
    )

    trainer.train()

    trainer.save_model(str(args.output_dir))
    tokenizer.save_pretrained(str(args.output_dir))

    print("=" * 70)
    print("Training completed successfully.")
    print(f"Adapter saved to: {args.output_dir}")
    print("=" * 70)


if __name__ == "__main__":
    main()