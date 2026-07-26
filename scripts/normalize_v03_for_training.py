import json
from pathlib import Path
from typing import Any


INPUT_FILE = Path(
    "data/v0.3/prepared/gaialab_naija_v0.3_combined.jsonl"
)

OUTPUT_FILE = Path(
    "data/v0.3/prepared/gaialab_naija_v0.3_training_ready.jsonl"
)

REQUIRED_FIELDS = {
    "instruction",
    "input",
    "output",
    "language",
    "category",
    "source",
    "license",
}


def clean_text(value: Any) -> str:
    """Convert a value to clean text."""
    if value is None:
        return ""

    return str(value).strip()


def infer_category(record: dict[str, Any]) -> str:
    """Return an existing category or a safe default."""
    category = clean_text(record.get("category"))

    if category:
        return category

    return "general_assistance"


def infer_language(record: dict[str, Any]) -> str:
    """Return an existing language or a safe default."""
    language = clean_text(record.get("language"))

    if language:
        return language

    return "English"


def validate_legacy_record(
    record: dict[str, Any],
    record_number: int,
) -> dict[str, Any]:
    """Validate a record already using the trainer schema."""
    missing_fields = [
        field
        for field in REQUIRED_FIELDS
        if field not in record
    ]

    if missing_fields:
        missing_text = ", ".join(sorted(missing_fields))
        raise ValueError(
            f"Record {record_number}: missing required field(s): "
            f"{missing_text}"
        )

    normalized = {
        "instruction": clean_text(record.get("instruction")),
        "input": clean_text(record.get("input")),
        "output": clean_text(record.get("output")),
        "language": infer_language(record),
        "category": infer_category(record),
        "source": clean_text(record.get("source")),
        "license": clean_text(record.get("license")),
    }

    if not normalized["instruction"]:
        raise ValueError(
            f"Record {record_number}: instruction is empty"
        )

    if not normalized["output"]:
        raise ValueError(
            f"Record {record_number}: output is empty"
        )

    if not normalized["source"]:
        normalized["source"] = "GaiaLab Naija"

    if not normalized["license"]:
        normalized["license"] = "Apache-2.0"

    return normalized


def convert_messages_record(
    record: dict[str, Any],
    record_number: int,
) -> dict[str, Any]:
    """Convert a chat-messages record into the trainer schema."""
    messages = record.get("messages")

    if not isinstance(messages, list):
        raise ValueError(
            f"Record {record_number}: messages must be a list"
        )

    system_parts: list[str] = []
    user_parts: list[str] = []
    assistant_parts: list[str] = []

    for message_number, message in enumerate(messages, start=1):
        if not isinstance(message, dict):
            raise ValueError(
                f"Record {record_number}, message {message_number}: "
                "message must be an object"
            )

        role = clean_text(message.get("role")).lower()
        content = clean_text(message.get("content"))

        if not content:
            continue

        if role == "system":
            system_parts.append(content)
        elif role == "user":
            user_parts.append(content)
        elif role == "assistant":
            assistant_parts.append(content)

    if not user_parts:
        raise ValueError(
            f"Record {record_number}: no user message found"
        )

    if not assistant_parts:
        raise ValueError(
            f"Record {record_number}: no assistant message found"
        )

    instruction = "\n\n".join(user_parts)
    input_text = "\n\n".join(system_parts)
    output = "\n\n".join(assistant_parts)

    return {
        "instruction": instruction,
        "input": input_text,
        "output": output,
        "language": infer_language(record),
        "category": infer_category(record),
        "source": clean_text(
            record.get("source")
        ) or "GaiaLab Naija v0.3",
        "license": clean_text(
            record.get("license")
        ) or "Apache-2.0",
    }


def convert_record(
    record: dict[str, Any],
    record_number: int,
) -> dict[str, Any]:
    """Convert any supported dataset record into trainer format."""
    if not isinstance(record, dict):
        raise ValueError(
            f"Record {record_number}: record must be a JSON object"
        )

    if "messages" in record:
        return convert_messages_record(record, record_number)

    legacy_core_fields = {
        "instruction",
        "input",
        "output",
    }

    if legacy_core_fields.issubset(record):
        completed_record = dict(record)

        completed_record.setdefault(
            "language",
            infer_language(record),
        )
        completed_record.setdefault(
            "category",
            infer_category(record),
        )
        completed_record.setdefault(
            "source",
            "GaiaLab Naija",
        )
        completed_record.setdefault(
            "license",
            "Apache-2.0",
        )

        return validate_legacy_record(
            completed_record,
            record_number,
        )

    raise ValueError(
        f"Record {record_number}: unsupported dataset schema"
    )


def load_records(path: Path) -> list[dict[str, Any]]:
    """Read and convert records from a JSONL file."""
    if not path.exists():
        raise FileNotFoundError(
            f"Input dataset was not found: {path}"
        )

    converted_records: list[dict[str, Any]] = []

    with path.open("r", encoding="utf-8") as source_file:
        for record_number, line in enumerate(
            source_file,
            start=1,
        ):
            stripped_line = line.strip()

            if not stripped_line:
                continue

            try:
                record = json.loads(stripped_line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Record {record_number}: invalid JSON: {exc}"
                ) from exc

            converted_record = convert_record(
                record,
                record_number,
            )

            converted_records.append(converted_record)

    if not converted_records:
        raise ValueError(
            "No valid records were found in the input dataset"
        )

    return converted_records


def write_records(
    records: list[dict[str, Any]],
    path: Path,
) -> None:
    """Write records to a UTF-8 JSONL file."""
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open(
        "w",
        encoding="utf-8",
        newline="\n",
    ) as output_file:
        for record in records:
            output_file.write(
                json.dumps(
                    record,
                    ensure_ascii=False,
                )
                + "\n"
            )


def main() -> None:
    """Normalize the v0.3 dataset for adapter training."""
    records = load_records(INPUT_FILE)

    write_records(
        records,
        OUTPUT_FILE,
    )

    print("GaiaLab Naija v0.3 normalization complete")
    print(f"Input file:     {INPUT_FILE}")
    print(f"Output file:    {OUTPUT_FILE}")
    print(f"Records written: {len(records)}")
    print("Required fields:")
    print("  instruction")
    print("  input")
    print("  output")
    print("  language")
    print("  category")
    print("  source")
    print("  license")


if __name__ == "__main__":
    main()