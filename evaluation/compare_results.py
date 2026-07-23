"""
Compare GaiaBench JSONL results from multiple model versions.

Inputs:
    evaluation/results/base_model.jsonl
    evaluation/results/adapter_v0.1.jsonl
    evaluation/results/adapter_v0.2.jsonl

Outputs:
    evaluation/reports/v0.2_comparison_report.md
    evaluation/reports/v0.2_side_by_side.jsonl
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
from collections import Counter
from pathlib import Path
from typing import Any


DEFAULT_RESULT_FILES = {
    "Base Qwen": Path("evaluation/results/base_model.jsonl"),
    "GaiaLab v0.1": Path("evaluation/results/adapter_v0.1.jsonl"),
    "GaiaLab v0.2": Path("evaluation/results/adapter_v0.2.jsonl"),
}

DEFAULT_REPORT_PATH = Path(
    "evaluation/reports/v0.2_comparison_report.md"
)

DEFAULT_COMBINED_PATH = Path(
    "evaluation/reports/v0.2_side_by_side.jsonl"
)


PIDGIN_MARKERS = {
    "abeg",
    "abi",
    "dey",
    "dem",
    "don",
    "fit",
    "make",
    "na",
    "no be",
    "no dey",
    "oga",
    "pikin",
    "shey",
    "sabi",
    "wahala",
    "wetin",
    "una",
    "e go",
    "e no",
    "you go",
    "how far",
}


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    """Load a JSONL file and validate every line."""

    if not path.exists():
        raise FileNotFoundError(f"Result file not found: {path}")

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
                    f"Invalid JSON in {path} on line "
                    f"{line_number}: {exc}"
                ) from exc

            if not isinstance(record, dict):
                raise ValueError(
                    f"Expected an object in {path} on line "
                    f"{line_number}."
                )

            records.append(record)

    return records


def first_present(
    record: dict[str, Any],
    field_names: list[str],
    default: Any = "",
) -> Any:
    """Return the first non-empty field found in a record."""

    for field_name in field_names:
        value = record.get(field_name)

        if value is not None and value != "":
            return value

    return default


def get_record_id(
    record: dict[str, Any],
    fallback_index: int,
) -> str:
    """Find the benchmark record identifier."""

    value = first_present(
        record,
        [
            "id",
            "prompt_id",
            "benchmark_id",
            "case_id",
            "record_id",
            "example_id",
        ],
        default=f"record_{fallback_index:03d}",
    )

    return str(value)


def get_prompt(record: dict[str, Any]) -> str:
    """Extract the input prompt from a benchmark record."""

    value = first_present(
        record,
        [
            "prompt",
            "input",
            "question",
            "instruction",
            "user_prompt",
            "test_prompt",
        ],
        default="",
    )

    if isinstance(value, list):
        return "\n".join(str(item) for item in value)

    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)

    return str(value)


def get_response(record: dict[str, Any]) -> str:
    """Extract the generated model response."""

    value = first_present(
        record,
        [
            "response",
            "output",
            "generated_text",
            "model_response",
            "assistant_response",
            "completion",
            "answer",
        ],
        default="",
    )

    if isinstance(value, list):
        return "\n".join(str(item) for item in value)

    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)

    return str(value)


def get_category(record: dict[str, Any]) -> str:
    """Extract a benchmark category when available."""

    value = first_present(
        record,
        [
            "category",
            "task",
            "task_type",
            "domain",
            "language",
            "type",
        ],
        default="Uncategorized",
    )

    return str(value)


def tokenize(text: str) -> list[str]:
    """Return lowercase word-like tokens."""

    return re.findall(
        r"[A-Za-zÀ-ÖØ-öø-ÿ0-9']+",
        text.lower(),
    )


def contains_pidgin(text: str) -> bool:
    """Use a simple marker-based Nigerian Pidgin heuristic."""

    normalized = " ".join(tokenize(text))

    return any(
        re.search(
            rf"\b{re.escape(marker)}\b",
            normalized,
        )
        for marker in PIDGIN_MARKERS
    )


def pidgin_marker_count(text: str) -> int:
    """Count unique Nigerian Pidgin markers in a response."""

    normalized = " ".join(tokenize(text))

    return sum(
        1
        for marker in PIDGIN_MARKERS
        if re.search(
            rf"\b{re.escape(marker)}\b",
            normalized,
        )
    )


def repeated_phrase_count(text: str, phrase_size: int = 3) -> int:
    """Count repeated three-word phrases."""

    words = tokenize(text)

    if len(words) < phrase_size:
        return 0

    phrases = [
        " ".join(words[index:index + phrase_size])
        for index in range(len(words) - phrase_size + 1)
    ]

    counts = Counter(phrases)

    return sum(
        count - 1
        for count in counts.values()
        if count > 1
    )


def calculate_metrics(
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    """Calculate descriptive metrics for one model."""

    responses = [get_response(record) for record in records]
    word_counts = [len(tokenize(response)) for response in responses]
    character_counts = [len(response) for response in responses]

    empty_count = sum(
        1 for response in responses if not response.strip()
    )

    pidgin_count = sum(
        1 for response in responses if contains_pidgin(response)
    )

    total_pidgin_markers = sum(
        pidgin_marker_count(response)
        for response in responses
    )

    responses_with_repetition = sum(
        1
        for response in responses
        if repeated_phrase_count(response) > 0
    )

    total_records = len(records)

    return {
        "record_count": total_records,
        "empty_count": empty_count,
        "empty_rate": (
            empty_count / total_records * 100
            if total_records
            else 0.0
        ),
        "average_words": (
            statistics.mean(word_counts)
            if word_counts
            else 0.0
        ),
        "median_words": (
            statistics.median(word_counts)
            if word_counts
            else 0.0
        ),
        "minimum_words": min(word_counts, default=0),
        "maximum_words": max(word_counts, default=0),
        "average_characters": (
            statistics.mean(character_counts)
            if character_counts
            else 0.0
        ),
        "pidgin_response_count": pidgin_count,
        "pidgin_response_rate": (
            pidgin_count / total_records * 100
            if total_records
            else 0.0
        ),
        "average_pidgin_markers": (
            total_pidgin_markers / total_records
            if total_records
            else 0.0
        ),
        "responses_with_repetition": responses_with_repetition,
        "repetition_rate": (
            responses_with_repetition / total_records * 100
            if total_records
            else 0.0
        ),
    }


def index_records(
    records: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Create an ID-to-record mapping."""

    indexed: dict[str, dict[str, Any]] = {}

    for index, record in enumerate(records, start=1):
        record_id = get_record_id(record, index)

        if record_id in indexed:
            raise ValueError(
                f"Duplicate benchmark ID detected: {record_id}"
            )

        indexed[record_id] = record

    return indexed


def escape_markdown_cell(value: str) -> str:
    """Make text safe for a compact Markdown table cell."""

    cleaned = value.replace("|", "\\|")
    cleaned = cleaned.replace("\r", " ")
    cleaned = cleaned.replace("\n", "<br>")

    if len(cleaned) > 240:
        return cleaned[:237] + "..."

    return cleaned


def format_response_block(
    model_name: str,
    response: str,
) -> str:
    """Format one full model response for Markdown."""

    return (
        f"#### {model_name}\n\n"
        f"{response.strip() or '*No response generated.*'}\n"
    )


def build_combined_records(
    indexed_results: dict[
        str,
        dict[str, dict[str, Any]],
    ],
) -> list[dict[str, Any]]:
    """Align model responses using benchmark IDs."""

    all_ids: set[str] = set()

    for records in indexed_results.values():
        all_ids.update(records.keys())

    combined: list[dict[str, Any]] = []

    for record_id in sorted(all_ids):
        source_record = None

        for model_records in indexed_results.values():
            if record_id in model_records:
                source_record = model_records[record_id]
                break

        if source_record is None:
            continue

        item: dict[str, Any] = {
            "id": record_id,
            "category": get_category(source_record),
            "prompt": get_prompt(source_record),
            "responses": {},
        }

        for model_name, model_records in indexed_results.items():
            record = model_records.get(record_id)

            item["responses"][model_name] = (
                get_response(record)
                if record
                else ""
            )

        combined.append(item)

    return combined


def write_combined_jsonl(
    combined_records: list[dict[str, Any]],
    output_path: Path,
) -> None:
    """Write aligned model responses to JSONL."""

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8") as file:
        for record in combined_records:
            file.write(
                json.dumps(record, ensure_ascii=False) + "\n"
            )


def write_markdown_report(
    combined_records: list[dict[str, Any]],
    metrics_by_model: dict[str, dict[str, Any]],
    output_path: Path,
) -> None:
    """Generate the full Markdown comparison report."""

    output_path.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = [
        "# GaiaLab Naija Assistant",
        "",
        "## GaiaBench Model Comparison Report",
        "",
        (
            "This report compares the Qwen base model with "
            "GaiaLab Naija Assistant adapters v0.1 and v0.2."
        ),
        "",
        "> Important: Pidgin detection and repetition checks in this "
        "report are automated heuristics. They are not substitutes "
        "for human linguistic evaluation.",
        "",
        "## Summary Statistics",
        "",
        (
            "| Model | Responses | Avg. words | Median words | "
            "Empty | Pidgin detected | Repetition detected |"
        ),
        (
            "|---|---:|---:|---:|---:|---:|---:|"
        ),
    ]

    for model_name, metrics in metrics_by_model.items():
        lines.append(
            f"| {model_name} "
            f"| {metrics['record_count']} "
            f"| {metrics['average_words']:.1f} "
            f"| {metrics['median_words']:.1f} "
            f"| {metrics['empty_rate']:.1f}% "
            f"| {metrics['pidgin_response_rate']:.1f}% "
            f"| {metrics['repetition_rate']:.1f}% |"
        )

    lines.extend(
        [
            "",
            "## Additional Metrics",
            "",
            (
                "| Model | Min words | Max words | "
                "Avg. characters | Avg. Pidgin markers |"
            ),
            "|---|---:|---:|---:|---:|",
        ]
    )

    for model_name, metrics in metrics_by_model.items():
        lines.append(
            f"| {model_name} "
            f"| {metrics['minimum_words']} "
            f"| {metrics['maximum_words']} "
            f"| {metrics['average_characters']:.1f} "
            f"| {metrics['average_pidgin_markers']:.2f} |"
        )

    lines.extend(
        [
            "",
            "## Compact Side-by-Side View",
            "",
            (
                "| ID | Category | Prompt | Base Qwen | "
                "GaiaLab v0.1 | GaiaLab v0.2 |"
            ),
            "|---|---|---|---|---|---|",
        ]
    )

    for record in combined_records:
        responses = record["responses"]

        lines.append(
            f"| {escape_markdown_cell(record['id'])} "
            f"| {escape_markdown_cell(record['category'])} "
            f"| {escape_markdown_cell(record['prompt'])} "
            f"| {escape_markdown_cell(responses.get('Base Qwen', ''))} "
            f"| {escape_markdown_cell(responses.get('GaiaLab v0.1', ''))} "
            f"| {escape_markdown_cell(responses.get('GaiaLab v0.2', ''))} |"
        )

    lines.extend(
        [
            "",
            "## Full Responses",
            "",
        ]
    )

    for number, record in enumerate(combined_records, start=1):
        lines.extend(
            [
                f"### {number}. {record['id']}",
                "",
                f"**Category:** {record['category']}",
                "",
                "**Prompt**",
                "",
                record["prompt"].strip() or "*Prompt unavailable.*",
                "",
            ]
        )

        for model_name, response in record["responses"].items():
            lines.append(
                format_response_block(model_name, response)
            )

        lines.extend(["", "---", ""])

    lines.extend(
        [
            "## Human Evaluation",
            "",
            (
                "A human reviewer should score the three responses "
                "for each benchmark item using the existing "
                "`evaluation/reviewer_guide.md`."
            ),
            "",
            "Recommended dimensions:",
            "",
            "1. Correctness",
            "2. Instruction following",
            "3. Helpfulness",
            "4. Nigerian Pidgin quality",
            "5. Cultural appropriateness",
            "6. Safety and hallucination risk",
            "",
            (
                "Do not claim that one model is better based only "
                "on response length or automated Pidgin markers."
            ),
            "",
        ]
    )

    output_path.write_text(
        "\n".join(lines),
        encoding="utf-8",
    )


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compare base Qwen, GaiaLab v0.1, and GaiaLab v0.2 "
            "GaiaBench result files."
        )
    )

    parser.add_argument(
        "--report",
        type=Path,
        default=DEFAULT_REPORT_PATH,
        help="Path for the generated Markdown report.",
    )

    parser.add_argument(
        "--combined-output",
        type=Path,
        default=DEFAULT_COMBINED_PATH,
        help="Path for aligned side-by-side JSONL output.",
    )

    return parser.parse_args()


def main() -> int:
    args = parse_arguments()

    try:
        loaded_results = {
            model_name: load_jsonl(file_path)
            for model_name, file_path
            in DEFAULT_RESULT_FILES.items()
        }

        indexed_results = {
            model_name: index_records(records)
            for model_name, records in loaded_results.items()
        }

        metrics_by_model = {
            model_name: calculate_metrics(records)
            for model_name, records in loaded_results.items()
        }

        combined_records = build_combined_records(
            indexed_results
        )

        write_combined_jsonl(
            combined_records,
            args.combined_output,
        )

        write_markdown_report(
            combined_records,
            metrics_by_model,
            args.report,
        )

    except (FileNotFoundError, ValueError) as exc:
        print(f"Comparison failed: {exc}")
        return 1

    print(
        f"Compared {len(combined_records)} benchmark items."
    )
    print(f"Markdown report: {args.report}")
    print(f"Combined JSONL: {args.combined_output}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())