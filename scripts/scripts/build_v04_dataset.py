from __future__ import annotations

import argparse
import hashlib
import json
import random
from pathlib import Path

REQUIRED_ROLES = ("system", "user", "assistant")
DEFAULT_SYSTEM = (
    "You are GaiaLab Naija Assistant. Be helpful, concise, culturally aware, "
    "truthful, and safe. Never invent facts or request passwords, PINs, or OTPs."
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate, deduplicate, merge, and split GaiaLab v0.4 JSONL data.")
    parser.add_argument("--input-dir", default="data/raw")
    parser.add_argument("--output-dir", default="data/v0.4")
    parser.add_argument("--validation-ratio", type=float, default=0.10)
    parser.add_argument("--seed", type=int, default=42)
    return parser.parse_args()


def normalize_text(value: str) -> str:
    return " ".join((value or "").strip().split())


def validate_example(obj: dict, source: Path, line_number: int) -> dict:
    if not isinstance(obj, dict):
        raise ValueError(f"{source}:{line_number}: each line must be a JSON object")

    messages = obj.get("messages")
    if not isinstance(messages, list) or len(messages) != 3:
        raise ValueError(f"{source}:{line_number}: messages must contain exactly 3 items")

    cleaned = []
    for expected_role, message in zip(REQUIRED_ROLES, messages):
        if not isinstance(message, dict):
            raise ValueError(f"{source}:{line_number}: each message must be an object")
        role = message.get("role")
        content = normalize_text(str(message.get("content", "")))
        if role != expected_role:
            raise ValueError(
                f"{source}:{line_number}: expected role '{expected_role}', found '{role}'"
            )
        if not content:
            raise ValueError(f"{source}:{line_number}: empty content for role '{role}'")
        cleaned.append({"role": role, "content": content})

    category = normalize_text(str(obj.get("category", "uncategorized"))) or "uncategorized"
    risk_level = normalize_text(str(obj.get("risk_level", "low"))).lower() or "low"
    if risk_level not in {"low", "medium", "high"}:
        raise ValueError(f"{source}:{line_number}: risk_level must be low, medium, or high")

    return {
        "id": normalize_text(str(obj.get("id", ""))),
        "category": category,
        "risk_level": risk_level,
        "messages": cleaned,
    }


def fingerprint(example: dict) -> str:
    user_text = example["messages"][1]["content"].lower()
    assistant_text = example["messages"][2]["content"].lower()
    return hashlib.sha256(f"{user_text}\n{assistant_text}".encode("utf-8")).hexdigest()


def read_examples(input_dir: Path) -> list[dict]:
    files = sorted(input_dir.glob("*.jsonl"))
    if not files:
        raise FileNotFoundError(f"No .jsonl files found in {input_dir}")

    examples: list[dict] = []
    seen: set[str] = set()

    for source in files:
        with source.open("r", encoding="utf-8-sig") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"{source}:{line_number}: invalid JSON: {exc}") from exc

                example = validate_example(obj, source, line_number)
                key = fingerprint(example)
                if key in seen:
                    continue
                seen.add(key)
                examples.append(example)

    if not examples:
        raise ValueError("No valid examples were found")

    for index, example in enumerate(examples, start=1):
        if not example["id"]:
            example["id"] = f"v04-train-{index:04d}"
        if not example["messages"][0]["content"]:
            example["messages"][0]["content"] = DEFAULT_SYSTEM

    return examples


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> None:
    args = parse_args()
    if not 0.0 <= args.validation_ratio < 1.0:
        raise ValueError("--validation-ratio must be between 0 and 1")

    examples = read_examples(Path(args.input_dir))
    random.Random(args.seed).shuffle(examples)

    validation_count = int(round(len(examples) * args.validation_ratio))
    if len(examples) > 1 and args.validation_ratio > 0 and validation_count == 0:
        validation_count = 1

    validation = examples[:validation_count]
    training = examples[validation_count:]

    output_dir = Path(args.output_dir)
    write_jsonl(output_dir / "v0.4_training.jsonl", training)
    write_jsonl(output_dir / "v0.4_validation.jsonl", validation)
    write_jsonl(output_dir / "v0.4_all_reviewed.jsonl", examples)

    category_counts: dict[str, int] = {}
    risk_counts: dict[str, int] = {}
    for example in examples:
        category_counts[example["category"]] = category_counts.get(example["category"], 0) + 1
        risk_counts[example["risk_level"]] = risk_counts.get(example["risk_level"], 0) + 1

    manifest = {
        "dataset_version": "v0.4",
        "total_examples": len(examples),
        "training_examples": len(training),
        "validation_examples": len(validation),
        "validation_ratio": args.validation_ratio,
        "seed": args.seed,
        "category_counts": dict(sorted(category_counts.items())),
        "risk_counts": dict(sorted(risk_counts.items())),
    }
    (output_dir / "dataset_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print("GaiaLab v0.4 dataset prepared successfully.")
    print(f"Total reviewed examples: {len(examples)}")
    print(f"Training examples: {len(training)}")
    print(f"Validation examples: {len(validation)}")
    print(f"Output directory: {output_dir}")


if __name__ == "__main__":
    main()
