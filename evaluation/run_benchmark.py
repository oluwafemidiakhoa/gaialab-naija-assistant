"""Run GaiaBench Africa prompts with a local Hugging Face causal language model."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any
from peft import PeftConfig, PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer

DEFAULT_BENCHMARK = Path("evaluation/gaia_benchmark_v0.1.jsonl")
DEFAULT_OUTPUT = Path("evaluation/results.jsonl")
EXPECTED_CATEGORIES = {
    "customer_service": 6,
    "business_terminology": 6,
    "translation_en_to_pidgin": 6,
    "translation_pidgin_to_en": 6,
    "business_writing": 6,
}
REQUIRED_FIELDS = (
    "id",
    "instruction",
    "input",
    "expected_characteristics",
    "language",
    "category",
    "difficulty",
    "review_status",
    "source",
    "license",
)
PROHIBITED_ANSWER_FIELDS = {"answer", "expected_answer", "expected_output", "output"}
HUMAN_SCORE_FIELDS = (
    "instruction_following",
    "meaning_preservation",
    "naturalness",
    "professional_tone",
    "safety",
    "hallucination",
    "business_usefulness",
)


class BenchmarkError(ValueError):
    """Raised when the benchmark or runner configuration is invalid."""


def load_benchmark(path: Path) -> list[dict[str, Any]]:
    """Load and validate the versioned GaiaBench JSONL file."""
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise BenchmarkError(
                    f"Line {line_number}: invalid JSON ({exc.msg})."
                ) from exc
            if not isinstance(record, dict):
                raise BenchmarkError(f"Line {line_number}: record must be an object.")

            missing = [field for field in REQUIRED_FIELDS if field not in record]
            if missing:
                raise BenchmarkError(
                    f"Line {line_number}: missing field(s): {', '.join(missing)}."
                )
            prohibited = sorted(PROHIBITED_ANSWER_FIELDS.intersection(record))
            if prohibited:
                raise BenchmarkError(
                    f"Line {line_number}: expected answers are prohibited "
                    f"({', '.join(prohibited)})."
                )

            for field in REQUIRED_FIELDS:
                if field == "expected_characteristics":
                    continue
                if not isinstance(record[field], str) or not record[field].strip():
                    raise BenchmarkError(
                        f"Line {line_number}: '{field}' must be a non-empty string."
                    )
            characteristics = record["expected_characteristics"]
            if (
                not isinstance(characteristics, list)
                or not characteristics
                or any(not isinstance(item, str) or not item.strip() for item in characteristics)
            ):
                raise BenchmarkError(
                    f"Line {line_number}: 'expected_characteristics' must be a "
                    "non-empty list of non-empty strings."
                )
            records.append(record)

    if len(records) != 30:
        raise BenchmarkError(f"Expected exactly 30 prompts, found {len(records)}.")
    if len({record["id"] for record in records}) != len(records):
        raise BenchmarkError("Benchmark IDs must be unique.")
    prompts = {(record["instruction"], record["input"]) for record in records}
    if len(prompts) != len(records):
        raise BenchmarkError("Benchmark instruction/input pairs must be unique.")

    counts = Counter(record["category"] for record in records)
    if counts != EXPECTED_CATEGORIES:
        raise BenchmarkError(
            f"Unexpected category distribution: {dict(sorted(counts.items()))}."
        )
    return records


def build_prompt(record: dict[str, Any], tokenizer: Any) -> str:
    """Create a model prompt without exposing evaluation characteristics."""
    user_content = record["instruction"]
    if record["input"].strip():
        user_content += f"\n\nContext:\n{record['input'].strip()}"
    system_content = (
        "You are an experimental assistant for African small-business contexts. "
        f"Answer in {record['language']}. Follow the request carefully, preserve "
        "the supplied facts, and do not invent missing information."
    )
    messages = [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_content},
    ]
    if getattr(tokenizer, "chat_template", None):
        return tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
    return f"System: {system_content}\n\nUser: {user_content}\n\nAssistant:"


def load_model(model_id: str):
    import torch

    try:
        peft_config = PeftConfig.from_pretrained(model_id)
        base_model_id = peft_config.base_model_name_or_path
        is_adapter = True
    except Exception:
        base_model_id = model_id
        is_adapter = False

    print(f"Loading tokenizer from: {base_model_id}")

    tokenizer = AutoTokenizer.from_pretrained(
        base_model_id,
        use_fast=True,
    )

    model_kwargs = {
        "dtype": torch.float16 if torch.cuda.is_available() else torch.float32,
    }

    if torch.cuda.is_available():
        model_kwargs["device_map"] = "auto"

    print(f"Loading base model from: {base_model_id}")

    base_model = AutoModelForCausalLM.from_pretrained(
        base_model_id,
        **model_kwargs,
    )

    if is_adapter:
        print(f"Loading PEFT adapter from: {model_id}")
        model = PeftModel.from_pretrained(
            base_model,
            model_id,
        )
    else:
        model = base_model

    if not torch.cuda.is_available():
        model = model.to("cpu")

    model.eval()

    return tokenizer, model, torch


def generate_response(
    record: dict[str, Any],
    tokenizer: Any,
    model: Any,
    torch_module: Any,
    max_input_tokens: int,
    max_new_tokens: int,
) -> str:
    prompt = build_prompt(record, tokenizer)
    inputs = tokenizer(
        prompt,
        return_tensors="pt",
        truncation=True,
        max_length=max_input_tokens,
    ).to(model.device)
    with torch_module.inference_mode():
        generated = model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            do_sample=False,
            pad_token_id=tokenizer.pad_token_id,
        )
    new_tokens = generated[0, inputs["input_ids"].shape[1] :]
    response = tokenizer.decode(new_tokens, skip_special_tokens=True).strip()
    return response


def blank_human_review() -> dict[str, Any]:
    """Return explicitly unassigned fields for later human scoring."""
    return {
        "reviewer": "",
        **{field: None for field in HUMAN_SCORE_FIELDS},
        "notes": "",
    }


def run_benchmark(
    records: list[dict[str, Any]],
    output_path: Path,
    model_id: str,
    max_input_tokens: int,
    max_new_tokens: int,
    overwrite: bool = False,
) -> None:
    if output_path.exists() and not overwrite:
        raise BenchmarkError(
            f"Output already exists: {output_path}. Use --overwrite to replace it."
        )
    tokenizer, model, torch_module = load_model(model_id)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_name(f".{output_path.name}.tmp")

    try:
        with temporary_path.open("w", encoding="utf-8", newline="\n") as destination:
            for record in records:
                result = {
                    **record,
                    "model_id": model_id,
                    "response": generate_response(
                        record,
                        tokenizer,
                        model,
                        torch_module,
                        max_input_tokens,
                        max_new_tokens,
                    ),
                    "human_review": blank_human_review(),
                }
                destination.write(json.dumps(result, ensure_ascii=False) + "\n")
        os.replace(temporary_path, output_path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def positive_integer(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("value must be a positive integer")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-id", help="Local path or Hugging Face model ID")
    parser.add_argument("--benchmark", type=Path, default=DEFAULT_BENCHMARK)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--max-input-tokens", type=positive_integer, default=2048)
    parser.add_argument("--max-new-tokens", type=positive_integer, default=256)
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    model_id = (args.model_id or os.getenv("GAIABENCH_MODEL_ID", "")).strip()
    if not model_id:
        print(
            "Benchmark configuration error: provide --model-id or set "
            "GAIABENCH_MODEL_ID.",
            file=sys.stderr,
        )
        return 2
    if args.benchmark.resolve() == args.output.resolve():
        print("Benchmark configuration error: output must not overwrite the benchmark.", file=sys.stderr)
        return 2

    try:
        records = load_benchmark(args.benchmark)
        run_benchmark(
            records,
            args.output,
            model_id,
            args.max_input_tokens,
            args.max_new_tokens,
            args.overwrite,
        )
    except (BenchmarkError, ImportError, OSError, RuntimeError, ValueError) as exc:
        print(f"Benchmark failed: {exc}", file=sys.stderr)
        return 1
    print(
        f"Wrote {len(records)} unscored responses to {args.output}. "
        "A human reviewer must enter every score."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
