"""Evaluate a governed adapter on validation or held-out benchmark records only."""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.governed_training import (  # noqa: E402
    GovernedTrainingError,
    OutputSafetyError,
    assert_release_identity,
    assert_output_isolated,
    cuda_information,
    file_sha256,
    require_execution_hardware,
    tokenize_supervised_record,
    validate_evaluation_bundle,
    write_new_json,
)

DEFAULT_BASE_MODEL = "Qwen/Qwen2.5-0.5B-Instruct"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-model", default=DEFAULT_BASE_MODEL)
    parser.add_argument("--release-version", default="v0.7.0-rc.3")
    parser.add_argument("--base-model-revision")
    parser.add_argument("--adapter-dir", type=Path, required=True)
    parser.add_argument("--evaluation-file", type=Path, required=True)
    parser.add_argument("--training-file", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--max-seq-length", type=int, default=512)
    parser.add_argument("--max-new-tokens", type=int, default=128)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def _prepare_output(path: Path) -> None:
    if path.exists() and (not path.is_dir() or any(path.iterdir())):
        raise OutputSafetyError(f"refusing to overwrite evaluation output: {path}")
    path.mkdir(parents=True, exist_ok=True)


def run(args: argparse.Namespace) -> dict[str, Any]:
    if args.max_seq_length < 8 or args.max_new_tokens < 1:
        raise GovernedTrainingError("sequence lengths must be positive")
    evaluation, training, evidence = validate_evaluation_bundle(
        args.evaluation_file,
        args.training_file,
    )
    assert_release_identity(args.release_version, evidence)
    assert_output_isolated(
        args.output_dir,
        (args.evaluation_file, args.training_file),
    )
    _prepare_output(args.output_dir)
    warning = (
        f"Evaluation set is tiny ({len(evaluation)} records); metrics are not "
        "reliable for release claims."
        if len(evaluation) < 30
        else None
    )
    if args.dry_run:
        summary = {
            "status": "dry_run_validated",
            "base_model": args.base_model,
            "adapter_dir": str(args.adapter_dir),
            "evaluation_file": str(args.evaluation_file),
            "evaluation_sha256": file_sha256(args.evaluation_file),
            "evaluation_count": len(evaluation),
            "training_count": len(training),
            "candidate_version": evidence.candidate_version if evidence else None,
            "warning": warning,
        }
        write_new_json(args.output_dir / "evaluation_summary.json", summary)
        return summary

    require_execution_hardware(dry_run=False, smoke_test=False, cuda=cuda_information())
    if not args.adapter_dir.is_dir():
        raise GovernedTrainingError(f"adapter directory not found: {args.adapter_dir}")

    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer, set_seed

    random.seed(args.seed)
    set_seed(args.seed)
    tokenizer = AutoTokenizer.from_pretrained(args.adapter_dir, use_fast=True)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
    base_model = AutoModelForCausalLM.from_pretrained(
        args.base_model,
        revision=args.base_model_revision,
        torch_dtype=dtype,
        trust_remote_code=False,
        low_cpu_mem_usage=True,
    )
    model = PeftModel.from_pretrained(base_model, args.adapter_dir)
    model.to("cuda")
    model.eval()

    predictions: list[dict[str, Any]] = []
    loss_numerator = 0.0
    supervised_tokens = 0
    for record in sorted(evaluation, key=lambda item: item["id"]):
        encoded = tokenize_supervised_record(tokenizer, record, args.max_seq_length)
        batch = {
            key: torch.tensor([value], device="cuda") for key, value in encoded.items()
        }
        with torch.inference_mode():
            outputs = model(**batch)
        token_count = sum(label != -100 for label in encoded["labels"])
        loss_numerator += float(outputs.loss.item()) * token_count
        supervised_tokens += token_count

        prompt_messages = record["messages"][:-1]
        prompt_ids = tokenizer.apply_chat_template(
            prompt_messages,
            tokenize=True,
            add_generation_prompt=True,
            return_tensors="pt",
        ).to("cuda")
        with torch.inference_mode():
            generated = model.generate(
                prompt_ids,
                max_new_tokens=args.max_new_tokens,
                do_sample=False,
                pad_token_id=tokenizer.pad_token_id,
                eos_token_id=tokenizer.eos_token_id,
            )
        completion_ids = generated[0, prompt_ids.shape[-1] :]
        predictions.append(
            {
                "record_id": record["id"],
                "record_sha256": record["example_sha256"],
                "prompt": record["messages"][1]["content"],
                "expected_response": record["messages"][2]["content"],
                "generated_response": tokenizer.decode(
                    completion_ids,
                    skip_special_tokens=True,
                ).strip(),
            }
        )

    average_loss = loss_numerator / supervised_tokens
    perplexity = math.exp(average_loss) if average_loss < 20 else float("inf")
    predictions_path = args.output_dir / "predictions.jsonl"
    predictions_path.write_text(
        "".join(
            json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n"
            for item in predictions
        ),
        encoding="utf-8",
        newline="\n",
    )
    summary = {
        "status": "evaluation_completed",
        "base_model": args.base_model,
        "base_model_revision": args.base_model_revision,
        "adapter_dir": str(args.adapter_dir),
        "evaluation_file": str(args.evaluation_file),
        "evaluation_sha256": file_sha256(args.evaluation_file),
        "evaluation_count": len(evaluation),
        "supervised_token_count": supervised_tokens,
        "loss": average_loss,
        "perplexity": perplexity,
        "predictions_file": str(predictions_path),
        "predictions_sha256": file_sha256(predictions_path),
        "seed": args.seed,
        "warning": warning,
    }
    write_new_json(args.output_dir / "evaluation_summary.json", summary)
    return summary


def main(argv: list[str] | None = None) -> int:
    try:
        summary = run(parse_args(argv))
    except Exception as exc:
        print(
            f"Governed evaluation refused ({type(exc).__name__}): {exc}",
            file=sys.stderr,
        )
        return 1
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
