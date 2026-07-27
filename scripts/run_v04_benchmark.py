from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer


SYSTEM_PROMPT = (
    "You are GaiaLab Naija Assistant. "
    "Follow the user's facts exactly. "
    "Do not invent details that were not requested."
)


def load_benchmark(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"Benchmark file was not found: {path}")

    records: list[dict[str, Any]] = []

    with path.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            line = line.strip()

            if not line:
                continue

            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Invalid JSON on line {line_number} of {path}: {exc}"
                ) from exc

            required_fields = {
                "id",
                "category",
                "prompt",
                "expected_behavior",
                "risk_level",
            }

            missing_fields = required_fields.difference(record)

            if missing_fields:
                missing = ", ".join(sorted(missing_fields))
                raise ValueError(
                    f"Benchmark record on line {line_number} is missing: {missing}"
                )

            records.append(record)

    if not records:
        raise ValueError(f"No benchmark records were found in: {path}")

    return records


def load_model(
    base_model: str,
    adapter_path: Path,
):
    if not adapter_path.exists():
        raise FileNotFoundError(
            f"Adapter directory was not found: {adapter_path}"
        )

    adapter_config = adapter_path / "adapter_config.json"

    if not adapter_config.exists():
        raise FileNotFoundError(
            f"adapter_config.json was not found in: {adapter_path}"
        )

    print(f"Loading tokenizer from base model: {base_model}")

    tokenizer = AutoTokenizer.from_pretrained(
        base_model,
        trust_remote_code=True,
        use_fast=True,
    )

    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token

    print(f"Loading base model: {base_model}")

    base = AutoModelForCausalLM.from_pretrained(
        base_model,
        device_map="auto",
        torch_dtype="auto",
        trust_remote_code=True,
        low_cpu_mem_usage=True,
    )

    print(f"Loading LoRA adapter from: {adapter_path}")

    model = PeftModel.from_pretrained(
        base,
        str(adapter_path),
        is_trainable=False,
    )

    model.eval()

    print(f"Model device: {model.device}")
    print("Model and adapter loaded successfully.")

    return model, tokenizer


def generate(
    model,
    tokenizer,
    prompt: str,
    max_new_tokens: int,
) -> str:
    messages = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT,
        },
        {
            "role": "user",
            "content": prompt,
        },
    ]

    formatted_prompt = tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=True,
    )

    inputs = tokenizer(
        formatted_prompt,
        return_tensors="pt",
    )

    inputs = {
        key: value.to(model.device)
        for key, value in inputs.items()
    }

    input_length = inputs["input_ids"].shape[1]

    with torch.inference_mode():
        output = model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            do_sample=False,
            repetition_penalty=1.1,
            pad_token_id=tokenizer.pad_token_id,
            eos_token_id=tokenizer.eos_token_id,
        )

    generated_tokens = output[0][input_length:]

    return tokenizer.decode(
        generated_tokens,
        skip_special_tokens=True,
    ).strip()


def write_review_row(
    writer: csv.DictWriter,
    record: dict[str, Any],
    model_version: str,
    model_response: str,
) -> None:
    writer.writerow(
        {
            "id": record["id"],
            "category": record["category"],
            "prompt": record["prompt"],
            "expected_behavior": record["expected_behavior"],
            "risk_level": record["risk_level"],
            "model_version": model_version,
            "model_response": model_response,
            "instruction_following": "",
            "factual_consistency": "",
            "tone": "",
            "clarity": "",
            "safety": "",
            "hallucination": "",
            "pass": "",
            "reviewer_notes": "",
        }
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the GaiaLab Naija v0.4 benchmark."
    )

    parser.add_argument(
        "--benchmark",
        default="evaluation/v0.4/benchmark_v0.4.jsonl",
        help="Path to the benchmark JSONL file.",
    )

    parser.add_argument(
        "--adapter",
        required=True,
        help="Path to the trained LoRA adapter folder.",
    )

    parser.add_argument(
        "--base-model",
        default="Qwen/Qwen2.5-0.5B-Instruct",
        help="Base Hugging Face model used by the adapter.",
    )

    parser.add_argument(
        "--model-version",
        default="v0.3",
        help="Model version written to the review CSV.",
    )

    parser.add_argument(
        "--output",
        default="evaluation/v0.4/v0.3_baseline_review.csv",
        help="Output review CSV path.",
    )

    parser.add_argument(
        "--max-new-tokens",
        type=int,
        default=160,
        help="Maximum number of new tokens generated per prompt.",
    )

    args = parser.parse_args()

    benchmark_path = Path(args.benchmark)
    adapter_path = Path(args.adapter)
    output_path = Path(args.output)

    try:
        records = load_benchmark(benchmark_path)

        print(f"Loaded {len(records)} benchmark records.")

        model, tokenizer = load_model(
            base_model=args.base_model,
            adapter_path=adapter_path,
        )

        fields = [
            "id",
            "category",
            "prompt",
            "expected_behavior",
            "risk_level",
            "model_version",
            "model_response",
            "instruction_following",
            "factual_consistency",
            "tone",
            "clarity",
            "safety",
            "hallucination",
            "pass",
            "reviewer_notes",
        ]

        output_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        with output_path.open(
            "w",
            newline="",
            encoding="utf-8-sig",
        ) as file:
            writer = csv.DictWriter(
                file,
                fieldnames=fields,
            )

            writer.writeheader()

            for index, record in enumerate(records, start=1):
                record_id = record["id"]

                print(
                    f"[{index}/{len(records)}] "
                    f"Running benchmark: {record_id}"
                )

                try:
                    response = generate(
                        model=model,
                        tokenizer=tokenizer,
                        prompt=record["prompt"],
                        max_new_tokens=args.max_new_tokens,
                    )
                except Exception as exc:
                    response = (
                        f"[GENERATION ERROR] "
                        f"{type(exc).__name__}: {exc}"
                    )

                    print(
                        f"WARNING: Generation failed for "
                        f"{record_id}: {exc}"
                    )

                write_review_row(
                    writer=writer,
                    record=record,
                    model_version=args.model_version,
                    model_response=response,
                )

                file.flush()

        print()
        print("Benchmark completed successfully.")
        print(f"Saved review sheet to: {output_path}")

        return 0

    except KeyboardInterrupt:
        print("\nBenchmark cancelled by user.")
        return 130

    except Exception as exc:
        print()
        print(
            f"BENCHMARK FAILED: "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )

        return 1


if __name__ == "__main__":
    raise SystemExit(main())