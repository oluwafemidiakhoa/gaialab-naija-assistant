"""Fine-tune a small instruction model with QLoRA. No training runs automatically."""

from __future__ import annotations

import argparse
from pathlib import Path

import torch
from datasets import load_from_disk
from peft import LoraConfig, prepare_model_for_kbit_training
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
from trl import SFTConfig, SFTTrainer

DEFAULT_MODEL = "Qwen/Qwen2.5-0.5B-Instruct"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-id", default=DEFAULT_MODEL)
    parser.add_argument("--dataset-dir", type=Path, default=Path("prepared_data/hf"))
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/gaialab-naija"))
    parser.add_argument("--epochs", type=float, default=1.0)
    parser.add_argument("--max-steps", type=int, default=-1)
    args = parser.parse_args()

    if not torch.cuda.is_available():
        raise RuntimeError("QLoRA training requires a CUDA GPU. Use Colab or Kaggle.")

    if not args.dataset_dir.is_dir():
        raise FileNotFoundError(
            f"Prepared dataset not found: {args.dataset_dir}. Run prepare_dataset first."
        )
    dataset = load_from_disk(str(args.dataset_dir))
    missing_splits = {"train", "validation"} - set(dataset)
    if missing_splits:
        raise ValueError(
            f"Prepared dataset is missing split(s): {', '.join(sorted(missing_splits))}."
        )
    if not dataset["train"] or not dataset["validation"]:
        raise ValueError("Train and validation splits must both contain records.")
    required_columns = {"prompt", "completion"}
    if not required_columns.issubset(dataset["train"].column_names):
        raise ValueError(
            "Prepared training data must contain conversational prompt and completion columns."
        )
    tokenizer = AutoTokenizer.from_pretrained(args.model_id, use_fast=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    compute_dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
    quantization = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True,
        bnb_4bit_compute_dtype=compute_dtype,
    )
    model = AutoModelForCausalLM.from_pretrained(
        args.model_id,
        quantization_config=quantization,
        device_map="auto",
        dtype=compute_dtype,
    )
    model.config.use_cache = False
    model = prepare_model_for_kbit_training(
        model,
        use_gradient_checkpointing=True,
        gradient_checkpointing_kwargs={"use_reentrant": False},
    )

    peft_config = LoraConfig(
        r=16,
        lora_alpha=32,
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM",
        target_modules="all-linear",
    )
    training_args = SFTConfig(
        output_dir=str(args.output_dir),
        num_train_epochs=args.epochs,
        max_steps=args.max_steps,
        per_device_train_batch_size=2,
        per_device_eval_batch_size=2,
        gradient_accumulation_steps=8,
        gradient_checkpointing=True,
        gradient_checkpointing_kwargs={"use_reentrant": False},
        learning_rate=2e-4,
        logging_steps=5,
        eval_strategy="steps",
        eval_steps=25,
        save_steps=25,
        save_total_limit=2,
        bf16=compute_dtype == torch.bfloat16,
        fp16=compute_dtype == torch.float16,
        report_to="none",
        max_length=1024,
        completion_only_loss=True,
        optim="paged_adamw_8bit",
        seed=42,
    )
    trainer = SFTTrainer(
        model=model,
        args=training_args,
        train_dataset=dataset["train"],
        eval_dataset=dataset["validation"],
        processing_class=tokenizer,
        peft_config=peft_config,
    )
    trainer.train()
    trainer.save_model()
    tokenizer.save_pretrained(args.output_dir)


if __name__ == "__main__":
    main()
