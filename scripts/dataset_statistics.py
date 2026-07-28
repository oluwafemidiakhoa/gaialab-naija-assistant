from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter
from pathlib import Path
from typing import Any


DEFAULT_DATASET_FILE = Path("data/v0.5/v0.5_training.jsonl")
DEFAULT_REPORT_FILE = Path("data/v0.5/dataset_statistics.json")


class DatasetStatisticsError(Exception):
    """Raised when statistics cannot be generated."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate statistics for the GaiaLab Naija Assistant dataset."
    )
    parser.add_argument(
        "--dataset-file",
        type=Path,
        default=DEFAULT_DATASET_FILE,
        help="JSONL dataset to analyze.",
    )
    parser.add_argument(
        "--report-file",
        type=Path,
        default=DEFAULT_REPORT_FILE,
        help="JSON file where statistics will be saved.",
    )
    return parser.parse_args()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise DatasetStatisticsError(f"Dataset file not found: {path}")

    records: list[dict[str, Any]] = []

    with path.open("r", encoding="utf-8-sig") as file:
        for line_number, raw_line in enumerate(file, start=1):
            line = raw_line.strip()

            if not line:
                continue

            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise DatasetStatisticsError(
                    f"{path}, line {line_number}: invalid JSON: {exc.msg}"
                ) from exc

            if not isinstance(record, dict):
                raise DatasetStatisticsError(
                    f"{path}, line {line_number}: expected a JSON object."
                )

            records.append(record)

    if not records:
        raise DatasetStatisticsError(f"No records found in: {path}")

    return records


def get_message_content(record: dict[str, Any], role: str) -> str:
    messages = record.get("messages", [])

    for message in messages:
        if isinstance(message, dict) and message.get("role") == role:
            content = message.get("content", "")
            return content if isinstance(content, str) else ""

    return ""


def normalize_text(text: str) -> str:
    return " ".join(text.lower().split())


def calculate_health_score(
    total_examples: int,
    duplicate_ids: int,
    duplicate_prompts: int,
    missing_user_prompts: int,
    missing_assistant_responses: int,
    category_counts: Counter[str],
) -> int:
    score = 100

    score -= min(30, duplicate_ids * 10)
    score -= min(20, duplicate_prompts * 5)
    score -= min(20, missing_user_prompts * 10)
    score -= min(20, missing_assistant_responses * 10)

    if total_examples < 100:
        score -= 5

    if len(category_counts) < 5:
        score -= 5

    if category_counts:
        largest_category = max(category_counts.values())
        if largest_category / total_examples > 0.50:
            score -= 5

    return max(0, score)


def build_statistics(records: list[dict[str, Any]]) -> dict[str, Any]:
    ids = [str(record.get("id", "")).strip() for record in records]
    categories = [
        str(record.get("category", "unknown")).strip() or "unknown"
        for record in records
    ]
    risk_levels = [
        str(record.get("risk_level", "unknown")).strip() or "unknown"
        for record in records
    ]

    user_prompts = [get_message_content(record, "user") for record in records]
    assistant_responses = [
        get_message_content(record, "assistant") for record in records
    ]

    prompt_word_counts = [len(text.split()) for text in user_prompts if text.strip()]
    response_word_counts = [
        len(text.split()) for text in assistant_responses if text.strip()
    ]

    id_counts = Counter(ids)
    normalized_prompt_counts = Counter(
        normalize_text(prompt)
        for prompt in user_prompts
        if prompt.strip()
    )

    duplicate_ids = sorted(
        item for item, count in id_counts.items() if item and count > 1
    )
    duplicate_prompts = sorted(
        item
        for item, count in normalized_prompt_counts.items()
        if item and count > 1
    )

    missing_user_prompts = sum(not prompt.strip() for prompt in user_prompts)
    missing_assistant_responses = sum(
        not response.strip() for response in assistant_responses
    )

    category_counts = Counter(categories)
    risk_counts = Counter(risk_levels)

    longest_prompt_index = max(
        range(len(user_prompts)),
        key=lambda index: len(user_prompts[index]),
    )
    shortest_prompt_index = min(
        (
            index
            for index, prompt in enumerate(user_prompts)
            if prompt.strip()
        ),
        key=lambda index: len(user_prompts[index]),
    )
    longest_response_index = max(
        range(len(assistant_responses)),
        key=lambda index: len(assistant_responses[index]),
    )
    shortest_response_index = min(
        (
            index
            for index, response in enumerate(assistant_responses)
            if response.strip()
        ),
        key=lambda index: len(assistant_responses[index]),
    )

    health_score = calculate_health_score(
        total_examples=len(records),
        duplicate_ids=len(duplicate_ids),
        duplicate_prompts=len(duplicate_prompts),
        missing_user_prompts=missing_user_prompts,
        missing_assistant_responses=missing_assistant_responses,
        category_counts=category_counts,
    )

    return {
        "total_examples": len(records),
        "categories": dict(sorted(category_counts.items())),
        "risk_levels": dict(sorted(risk_counts.items())),
        "prompt_words": {
            "average": round(statistics.mean(prompt_word_counts), 2),
            "median": round(statistics.median(prompt_word_counts), 2),
            "minimum": min(prompt_word_counts),
            "maximum": max(prompt_word_counts),
        },
        "response_words": {
            "average": round(statistics.mean(response_word_counts), 2),
            "median": round(statistics.median(response_word_counts), 2),
            "minimum": min(response_word_counts),
            "maximum": max(response_word_counts),
        },
        "longest_prompt": {
            "id": ids[longest_prompt_index],
            "text": user_prompts[longest_prompt_index],
        },
        "shortest_prompt": {
            "id": ids[shortest_prompt_index],
            "text": user_prompts[shortest_prompt_index],
        },
        "longest_response": {
            "id": ids[longest_response_index],
            "text": assistant_responses[longest_response_index],
        },
        "shortest_response": {
            "id": ids[shortest_response_index],
            "text": assistant_responses[shortest_response_index],
        },
        "quality_checks": {
            "duplicate_ids": duplicate_ids,
            "duplicate_prompts": duplicate_prompts,
            "missing_user_prompts": missing_user_prompts,
            "missing_assistant_responses": missing_assistant_responses,
        },
        "dataset_health_score": health_score,
    }


def write_report(path: Path, statistics_data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(statistics_data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def print_table(title: str, values: dict[str, int]) -> None:
    print()
    print(title)
    print("-" * 42)

    width = max(len(key) for key in values)
    for key, value in values.items():
        print(f"{key:<{width}}  {value:>4}")


def print_summary(
    dataset_file: Path,
    report_file: Path,
    data: dict[str, Any],
) -> None:
    print()
    print("GaiaLab Dataset Statistics")
    print("=" * 42)
    print(f"Dataset file      : {dataset_file}")
    print(f"Total examples    : {data['total_examples']}")

    print_table("Categories", data["categories"])
    print_table("Risk Levels", data["risk_levels"])

    print()
    print("Prompt Lengths (words)")
    print("-" * 42)
    print(f"Average           : {data['prompt_words']['average']}")
    print(f"Median            : {data['prompt_words']['median']}")
    print(f"Minimum           : {data['prompt_words']['minimum']}")
    print(f"Maximum           : {data['prompt_words']['maximum']}")

    print()
    print("Response Lengths (words)")
    print("-" * 42)
    print(f"Average           : {data['response_words']['average']}")
    print(f"Median            : {data['response_words']['median']}")
    print(f"Minimum           : {data['response_words']['minimum']}")
    print(f"Maximum           : {data['response_words']['maximum']}")

    checks = data["quality_checks"]

    print()
    print("Quality Checks")
    print("-" * 42)
    print(f"Duplicate IDs     : {len(checks['duplicate_ids'])}")
    print(f"Duplicate prompts : {len(checks['duplicate_prompts'])}")
    print(f"Missing prompts   : {checks['missing_user_prompts']}")
    print(f"Missing responses : {checks['missing_assistant_responses']}")

    print()
    print(f"Dataset health    : {data['dataset_health_score']}/100")
    print(f"Report file       : {report_file}")
    print()
    print("STATISTICS COMPLETE")


def main() -> int:
    args = parse_args()

    try:
        records = load_jsonl(args.dataset_file)
        statistics_data = build_statistics(records)
        write_report(args.report_file, statistics_data)
        print_summary(args.dataset_file, args.report_file, statistics_data)
        return 0

    except DatasetStatisticsError as exc:
        print()
        print("STATISTICS FAILED")
        print("=" * 42)
        print(exc)
        return 1

    except (OSError, ValueError, statistics.StatisticsError) as exc:
        print()
        print("STATISTICS FAILED")
        print("=" * 42)
        print(f"Unexpected error: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
