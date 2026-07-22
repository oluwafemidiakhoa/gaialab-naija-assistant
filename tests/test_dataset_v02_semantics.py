import json
from pathlib import Path


DATASET_PATH = Path("data/v0.2/english_to_pidgin_100.jsonl")
REVIEW_REPORT_PATH = Path("outputs/v0.2/semantic_review_warnings.json")


def load_records():
    records = []

    with DATASET_PATH.open("r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()

            if line:
                records.append(json.loads(line))

    return records


def test_directional_business_terms_generate_review_report():
    term_groups = {
        "paid": {
            "paid",
            "pay",
            "don pay",
            "payment don enter",
            "receive the payment",
            "receive your payment",
            "money don enter",
        },
        "unpaid": {
            "unpaid",
            "never pay",
            "no pay",
            "payment never enter",
            "money never enter",
        },
        "accepted": {
            "accepted",
            "accept",
        },
        "rejected": {
            "rejected",
            "reject",
        },
        "approved": {
            "approved",
            "approve",
        },
        "cancelled": {
            "cancelled",
            "canceled",
            "cancel",
        },
        "refunded": {
            "refunded",
            "refund",
            "return the money",
            "money don return",
        },
    }

    warnings = []

    for record in load_records():
        input_text = record["input"].lower()
        output_text = record["output"].lower()

        for source_term, valid_outputs in term_groups.items():
            if source_term not in input_text:
                continue

            meaning_found = any(
                valid_term in output_text
                for valid_term in valid_outputs
            )

            if not meaning_found:
                warnings.append(
                    {
                        "id": record["id"],
                        "term": source_term,
                        "input": record["input"],
                        "output": record["output"],
                        "reason": (
                            f"Translation may not clearly preserve "
                            f"the meaning of '{source_term}'."
                        ),
                        "review_status": "pending",
                    }
                )

    REVIEW_REPORT_PATH.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    with REVIEW_REPORT_PATH.open(
        "w",
        encoding="utf-8"
    ) as file:
        json.dump(
            warnings,
            file,
            ensure_ascii=False,
            indent=2
        )

    print(
        f"\nSemantic review warnings: {len(warnings)}"
    )

    print(
        f"Review report: {REVIEW_REPORT_PATH}"
    )