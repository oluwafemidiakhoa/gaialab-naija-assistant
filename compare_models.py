"""Generate unscored GaiaBench comparisons for a base model and LoRA adapter."""

from __future__ import annotations

import argparse
import csv
import gc
import hashlib
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evaluation.run_benchmark import (
    DEFAULT_BENCHMARK,
    HUMAN_SCORE_FIELDS,
    blank_human_review,
    generate_response,
    load_benchmark,
    load_model,
    positive_integer,
)

DEFAULT_BASE_MODEL = "Qwen/Qwen2.5-0.5B-Instruct"
DEFAULT_OUTPUT_DIR = Path("outputs/comparison")


class ComparisonError(ValueError):
    """Raised when comparison inputs or outputs are invalid."""


def comparison_paths(output_dir: Path) -> dict[str, Path]:
    return {
        "json": output_dir / "comparison.json",
        "csv": output_dir / "comparison.csv",
        "markdown": output_dir / "comparison.md",
    }


def validate_comparison_outputs(output_dir: Path, overwrite: bool) -> None:
    existing = [
        str(path) for path in comparison_paths(output_dir).values() if path.exists()
    ]
    if existing and not overwrite:
        raise ComparisonError(
            "Comparison output already exists. Use --overwrite to replace: "
            + ", ".join(existing)
        )


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def generate_for_model(
    records: list[dict[str, Any]],
    base_model_id: str,
    adapter_path: Path | None,
    max_input_tokens: int,
    max_new_tokens: int,
) -> list[str]:
    tokenizer, model, torch_module = load_model(base_model_id)
    if adapter_path is not None:
        if not (adapter_path / "adapter_config.json").is_file():
            raise ComparisonError(
                f"LoRA adapter configuration not found under {adapter_path}."
            )
        from peft import PeftModel

        model = PeftModel.from_pretrained(model, str(adapter_path))
        model.eval()
    responses = [
        generate_response(
            record,
            tokenizer,
            model,
            torch_module,
            max_input_tokens,
            max_new_tokens,
        )
        for record in records
    ]
    del model
    del tokenizer
    gc.collect()
    if torch_module.cuda.is_available():
        torch_module.cuda.empty_cache()
    return responses


def build_comparison(
    records: list[dict[str, Any]],
    base_responses: list[str],
    adapter_responses: list[str],
    base_model_id: str,
    adapter_path: Path,
    benchmark_path: Path,
) -> dict[str, Any]:
    if not len(records) == len(base_responses) == len(adapter_responses):
        raise ComparisonError("Response counts must match the benchmark prompt count.")
    average_placeholders = {
        "base_model": {**{field: None for field in HUMAN_SCORE_FIELDS}, "overall": None},
        "lora_adapter": {
            **{field: None for field in HUMAN_SCORE_FIELDS},
            "overall": None,
        },
    }
    results = []
    for record, base_response, adapter_response in zip(
        records, base_responses, adapter_responses
    ):
        results.append(
            {
                "id": record["id"],
                "instruction": record["instruction"],
                "input": record["input"],
                "expected_characteristics": record["expected_characteristics"],
                "language": record["language"],
                "category": record["category"],
                "difficulty": record["difficulty"],
                "base_response": base_response,
                "adapter_response": adapter_response,
                "human_review": {
                    "base_model": blank_human_review(),
                    "lora_adapter": blank_human_review(),
                    "preferred_response": None,
                    "comparison_notes": "",
                },
            }
        )
    return {
        "benchmark_metadata": {
            "name": "GaiaBench Africa",
            "version": "v0.1",
            "path": str(benchmark_path),
            "sha256": file_sha256(benchmark_path),
            "prompt_count": len(records),
            "category_counts": dict(
                sorted(Counter(record["category"] for record in records).items())
            ),
            "scores_assigned_by_runner": False,
        },
        "model_metadata": {
            "base_model": base_model_id,
            "lora_adapter": str(adapter_path),
        },
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "average_score_placeholders": average_placeholders,
        "results": results,
    }


def _markdown_cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", "<br>")


def write_reports(comparison: dict[str, Any], output_dir: Path, overwrite: bool) -> None:
    paths = comparison_paths(output_dir)
    validate_comparison_outputs(output_dir, overwrite)
    output_dir.mkdir(parents=True, exist_ok=True)
    paths["json"].write_text(
        json.dumps(comparison, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    score_columns = [
        f"{model}_{field}"
        for model in ("base", "adapter")
        for field in (*HUMAN_SCORE_FIELDS, "overall")
    ]
    fieldnames = [
        "benchmark_name",
        "benchmark_version",
        "benchmark_sha256",
        "base_model_id",
        "adapter_path",
        "id",
        "category",
        "difficulty",
        "language",
        "instruction",
        "input",
        "base_response",
        "adapter_response",
        *score_columns,
        "preferred_response",
        "comparison_notes",
    ]
    with paths["csv"].open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for result in comparison["results"]:
            writer.writerow(
                {
                    **{field: result.get(field, "") for field in fieldnames},
                    "benchmark_name": comparison["benchmark_metadata"]["name"],
                    "benchmark_version": comparison["benchmark_metadata"]["version"],
                    "benchmark_sha256": comparison["benchmark_metadata"]["sha256"],
                    "base_model_id": comparison["model_metadata"]["base_model"],
                    "adapter_path": comparison["model_metadata"]["lora_adapter"],
                    **{field: "" for field in score_columns},
                    "preferred_response": "",
                    "comparison_notes": "",
                }
            )
        writer.writerow(
            {
                "benchmark_name": comparison["benchmark_metadata"]["name"],
                "benchmark_version": comparison["benchmark_metadata"]["version"],
                "benchmark_sha256": comparison["benchmark_metadata"]["sha256"],
                "base_model_id": comparison["model_metadata"]["base_model"],
                "adapter_path": comparison["model_metadata"]["lora_adapter"],
                "id": "AVERAGE_SCORE_PLACEHOLDER",
                **{field: "" for field in score_columns},
            }
        )

    metadata = comparison["benchmark_metadata"]
    averages = comparison["average_score_placeholders"]
    lines = [
        "# GaiaLab Adapter v0.1 comparison",
        "",
        "> Pending human review: all score fields are placeholders. This report does not claim that either model performs better.",
        "",
        "## Benchmark metadata",
        "",
        f"- Benchmark: {metadata['name']} {metadata['version']}",
        f"- Prompts: {metadata['prompt_count']}",
        f"- SHA-256: `{metadata['sha256']}`",
        f"- Base model: `{comparison['model_metadata']['base_model']}`",
        f"- LoRA adapter: `{comparison['model_metadata']['lora_adapter']}`",
        "",
        "## Average score placeholders",
        "",
        "| Dimension | Base model | LoRA adapter |",
        "| --- | ---: | ---: |",
    ]
    for field in (*HUMAN_SCORE_FIELDS, "overall"):
        lines.append(
            f"| {field.replace('_', ' ').title()} | "
            f"{averages['base_model'][field] or 'Pending'} | "
            f"{averages['lora_adapter'][field] or 'Pending'} |"
        )
    lines.extend(
        [
            "",
            "## Prompt-level responses",
            "",
            "| ID | Category | Base response | Adapter response | Human review |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    for result in comparison["results"]:
        lines.append(
            "| {id} | {category} | {base} | {adapter} | Pending |".format(
                id=_markdown_cell(result["id"]),
                category=_markdown_cell(result["category"]),
                base=_markdown_cell(result["base_response"]),
                adapter=_markdown_cell(result["adapter_response"]),
            )
        )
    paths["markdown"].write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-model", default=DEFAULT_BASE_MODEL)
    parser.add_argument("--adapter-path", type=Path, required=True)
    parser.add_argument("--benchmark", type=Path, default=DEFAULT_BENCHMARK)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--max-input-tokens", type=positive_integer, default=2048)
    parser.add_argument("--max-new-tokens", type=positive_integer, default=256)
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        validate_comparison_outputs(args.output_dir, args.overwrite)
        if not (args.adapter_path / "adapter_config.json").is_file():
            raise ComparisonError(
                f"LoRA adapter configuration not found under {args.adapter_path}."
            )
        records = load_benchmark(args.benchmark)
        base_responses = generate_for_model(
            records,
            args.base_model,
            None,
            args.max_input_tokens,
            args.max_new_tokens,
        )
        adapter_responses = generate_for_model(
            records,
            args.base_model,
            args.adapter_path,
            args.max_input_tokens,
            args.max_new_tokens,
        )
        comparison = build_comparison(
            records,
            base_responses,
            adapter_responses,
            args.base_model,
            args.adapter_path,
            args.benchmark,
        )
        write_reports(comparison, args.output_dir, args.overwrite)
    except (ComparisonError, ImportError, OSError, RuntimeError, ValueError) as exc:
        print(f"Model comparison failed: {exc}", file=sys.stderr)
        return 1
    print(
        f"Wrote unscored comparison.json, comparison.csv, and comparison.md to "
        f"{args.output_dir}. Human review is required."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
