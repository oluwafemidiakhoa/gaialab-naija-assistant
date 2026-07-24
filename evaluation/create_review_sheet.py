import csv
import json
from pathlib import Path

INPUT_FILE = Path("evaluation/reports/v0.2_side_by_side.jsonl")
OUTPUT_FILE = Path("evaluation/reviews/human_review_v0.2.csv")

MODELS = [
    "Base Qwen",
    "GaiaLab v0.1",
    "GaiaLab v0.2",
]

FIELDS = [
    "prompt_id",
    "model",
    "instruction_following",
    "meaning_preservation",
    "naturalness",
    "professional_tone",
    "safety",
    "hallucination",
    "business_usefulness",
    "reviewer_notes",
]


def main():
    if not INPUT_FILE.exists():
        raise FileNotFoundError(f"Missing input file: {INPUT_FILE}")

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    benchmark_items = []

    with INPUT_FILE.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            line = line.strip()

            if not line:
                continue

            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Invalid JSON on line {line_number}: {exc}"
                ) from exc

            prompt_id = str(record.get("id", "")).strip()

            if not prompt_id:
                raise ValueError(
                    f"Missing benchmark ID on line {line_number}"
                )

            benchmark_items.append(prompt_id)

    with OUTPUT_FILE.open(
        "w",
        encoding="utf-8-sig",
        newline="",
    ) as file:
        writer = csv.DictWriter(file, fieldnames=FIELDS)
        writer.writeheader()

        for prompt_id in benchmark_items:
            for model in MODELS:
                writer.writerow(
                    {
                        "prompt_id": prompt_id,
                        "model": model,
                        "instruction_following": "",
                        "meaning_preservation": "",
                        "naturalness": "",
                        "professional_tone": "",
                        "safety": "",
                        "hallucination": "",
                        "business_usefulness": "",
                        "reviewer_notes": "",
                    }
                )

    print(
        f"Created {len(benchmark_items) * len(MODELS)} "
        f"review rows in {OUTPUT_FILE}"
    )


if __name__ == "__main__":
    main()