from __future__ import annotations

import argparse
import inspect
import json
from pathlib import Path
from typing import Any

import torch
from datasets import Dataset
from peft import LoraConfig, TaskType, get_peft_model
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    DataCollatorForLanguageModeling,
    Trainer,
    TrainingArguments,
    set_seed,
)


BASE_MODEL = "Qwen/Qwen2.5-0.5B-Instruct"
DEFAULT_TRAIN_FILE = Path("data/v0.4/v0.4_training.jsonl")
DEFAULT_VALIDATION_FILE = Path("data/v0.4/v0.4_validation.jsonl")
DEFAULT_OUTPUT_DIR = Path("outputs/gaialab-naija-adapter-v0.4")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fine-tune GaiaLab Naija Assistant v0.4 with LoRA."
    )

    parser.add_argument("--train-file", type=Path, default=DEFAULT_TRAIN_FILE)
    parser.add_argument(
        "--validation-file",
        type=Path,
        default=DEFAULT_VALIDATION_FILE,
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--epochs", type=float, default=5.0)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--eval-batch-size", type=int, default=1)
    parser.add_argument("--gradient-accumulation-steps", type=int, default=8)
    parser.add_argument("--learning-rate", type=float, default=2e-4)
    parser.add_argument("--max-length", type=int, default=512)
    parser.add_argument(
        "--max-steps",
        type=int,
        default=-1,
        help="Set to a small positive number, such as 2, for a smoke test.",
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--gradient-checkpointing",
        action="store_true",
        help="Reduce GPU memory usage at the cost of slower training.",
    )
    parser.add_argument(
        "--resume-from-checkpoint",
        type=str,
        default=None,
        help="Checkpoint path, or 'true' to resume from the latest checkpoint.",
    )

    args = parser.parse_args()

    if args.epochs <= 0:
        parser.error("--epochs must be greater than 0.")
    if args.batch_size <= 0:
        parser.error("--batch-size must be greater than 0.")
    if args.eval_batch_size <= 0:
        parser.error("--eval-batch-size must be greater than 0.")
    if args.gradient_accumulation_steps <= 0:
        parser.error("--gradient-accumulation-steps must be greater than 0.")
    if args.learning_rate <= 0:
        parser.error("--learning-rate must be greater than 0.")
    if args.max_length <= 0:
        parser.error("--max-length must be greater than 0.")
    if args.max_steps == 0 or args.max_steps < -1:
        parser.error("--max-steps must be -1 or a positive integer.")

    return args


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise FileNotFoundError(f"Dataset file was not found: {path.resolve()}")

    records: list[dict[str, Any]] = []

    with path.open("r", encoding="utf-8") as file:
        for line_number, raw_line in enumerate(file, start=1):
            line = raw_line.strip()
            if not line:
                continue

            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Invalid JSON in {path} at line {line_number}: {exc}"
                ) from exc

            if not isinstance(record, dict):
                raise ValueError(
                    f"Expected a JSON object in {path} at line {line_number}."
                )

            messages = record.get("messages")
            if not isinstance(messages, list) or not messages:
                raise ValueError(
                    f"Missing or invalid 'messages' list in {path} "
                    f"at line {line_number}."
                )

            for message_index, message in enumerate(messages, start=1):
                if not isinstance(message, dict):
                    raise ValueError(
                        f"Message {message_index} in {path} at line "
                        f"{line_number} must be an object."
                    )

                role = message.get("role")
                content = message.get("content")

                if role not in {"system", "user", "assistant", "tool"}:
                    raise ValueError(
                        f"Invalid role {role!r} in {path} at line "
                        f"{line_number}, message {message_index}."
                    )

                if not isinstance(content, str) or not content.strip():
                    raise ValueError(
                        f"Missing or empty content in {path} at line "
                        f"{line_number}, message {message_index}."
                    )

            records.append(record)

    if not records:
        raise ValueError(f"No training examples were loaded from {path}.")

    return records


def build_dataset(
    records: list[dict[str, Any]],
    tokenizer: Any,
    max_length: int,
) -> Dataset:
    formatted_records: list[dict[str, str]] = []

    for index, record in enumerate(records, start=1):
        try:
            text = tokenizer.apply_chat_template(
                record["messages"],
                tokenize=False,
                add_generation_prompt=False,
            )
        except Exception as exc:
            record_id = record.get("id", index)
            raise ValueError(
                f"Could not apply the chat template to record {record_id!r}."
            ) from exc

        formatted_records.append({"text": text})

    dataset = Dataset.from_list(formatted_records)

    def tokenize(batch: dict[str, list[str]]) -> dict[str, Any]:
        return tokenizer(
            batch["text"],
            truncation=True,
            max_length=max_length,
            padding=False,
            return_attention_mask=True,
        )

    return dataset.map(
        tokenize,
        batched=True,
        remove_columns=dataset.column_names,
        desc="Tokenizing dataset",
    )


def select_precision() -> tuple[torch.dtype, bool, bool]:
    if not torch.cuda.is_available():
        return torch.float32, False, False

    if torch.cuda.is_bf16_supported():
        return torch.bfloat16, False, True

    return torch.float16, True, False


def resolve_resume_argument(value: str | None) -> str | bool | None:
    if value is None:
        return None

    if value.lower() in {"true", "latest"}:
        return True

    return value


def make_training_arguments(
    args: argparse.Namespace,
    use_fp16: bool,
    use_bf16: bool,
) -> TrainingArguments:
    kwargs: dict[str, Any] = {
        "output_dir": str(args.output_dir),
        "num_train_epochs": args.epochs,
        "max_steps": args.max_steps,
        "per_device_train_batch_size": args.batch_size,
        "per_device_eval_batch_size": args.eval_batch_size,
        "gradient_accumulation_steps": args.gradient_accumulation_steps,
        "learning_rate": args.learning_rate,
        "warmup_ratio": 0.1,
        "weight_decay": 0.01,
        "logging_strategy": "steps",
        "logging_steps": 1,
        "save_strategy": "epoch",
        "save_total_limit": 2,
        "load_best_model_at_end": True,
        "metric_for_best_model": "eval_loss",
        "greater_is_better": False,
        "report_to": "none",
        "fp16": use_fp16,
        "bf16": use_bf16,
        "dataloader_pin_memory": torch.cuda.is_available(),
        "gradient_checkpointing": args.gradient_checkpointing,
        "seed": args.seed,
        "data_seed": args.seed,
        "save_safetensors": True,
        "remove_unused_columns": True,
    }

    parameters = inspect.signature(TrainingArguments.__init__).parameters

    if "eval_strategy" in parameters:
        kwargs["eval_strategy"] = "epoch"
    elif "evaluation_strategy" in parameters:
        kwargs["evaluation_strategy"] = "epoch"
    else:
        raise RuntimeError(
            "This Transformers version exposes neither 'eval_strategy' "
            "nor 'evaluation_strategy'. Upgrade Transformers."
        )

    return TrainingArguments(**kwargs)


def main() -> None:
    args = parse_args()
    set_seed(args.seed)

    device_name = "cuda" if torch.cuda.is_available() else "cpu"
    model_dtype, use_fp16, use_bf16 = select_precision()

    print("=" * 70)
    print("GaiaLab Naija Assistant v0.4 Training")
    print(f"Base model: {BASE_MODEL}")
    print(f"Device: {device_name}")
    print(f"Model dtype: {model_dtype}")
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
        use_fast=True,
    )

    if tokenizer.pad_token_id is None:
        if tokenizer.eos_token_id is None:
            raise ValueError("Tokenizer has neither a pad token nor an EOS token.")
        tokenizer.pad_token = tokenizer.eos_token

    tokenizer.padding_side = "right"

    model = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL,
        trust_remote_code=True,
        torch_dtype=model_dtype,
        low_cpu_mem_usage=True,
    )

    model.config.use_cache = False

    lora_config = LoraConfig(
        r=16,
        lora_alpha=32,
        lora_dropout=0.05,
        bias="none",
        task_type=TaskType.CAUSAL_LM,
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

    if args.gradient_checkpointing:
        model.enable_input_require_grads()

    model.print_trainable_parameters()

    train_dataset = build_dataset(
        records=train_records,
        tokenizer=tokenizer,
        max_length=args.max_length,
    )
    validation_dataset = build_dataset(
        records=validation_records,
        tokenizer=tokenizer,
        max_length=args.max_length,
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)

    training_args = make_training_arguments(
        args=args,
        use_fp16=use_fp16,
        use_bf16=use_bf16,
    )

    data_collator = DataCollatorForLanguageModeling(
        tokenizer=tokenizer,
        mlm=False,
    )

    trainer_kwargs: dict[str, Any] = {
        "model": model,
        "args": training_args,
        "train_dataset": train_dataset,
        "eval_dataset": validation_dataset,
        "data_collator": data_collator,
    }

    trainer_parameters = inspect.signature(Trainer.__init__).parameters
    if "processing_class" in trainer_parameters:
        trainer_kwargs["processing_class"] = tokenizer
    else:
        trainer_kwargs["tokenizer"] = tokenizer

    trainer = Trainer(**trainer_kwargs)

    train_result = trainer.train(
        resume_from_checkpoint=resolve_resume_argument(
            args.resume_from_checkpoint
        )
    )

    trainer.save_model(str(args.output_dir))
    tokenizer.save_pretrained(str(args.output_dir))
    trainer.save_state()
    trainer.log_metrics("train", train_result.metrics)
    trainer.save_metrics("train", train_result.metrics)

    evaluation_metrics = trainer.evaluate()
    trainer.log_metrics("eval", evaluation_metrics)
    trainer.save_metrics("eval", evaluation_metrics)

    print("=" * 70)
    print("Training completed successfully.")
    print(f"LoRA adapter and tokenizer saved to: {args.output_dir.resolve()}")
    print("=" * 70)


if __name__ == "__main__":
    main()
