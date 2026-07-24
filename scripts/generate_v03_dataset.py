"""
Generate candidate training records for GaiaLab Naija Assistant v0.3.

This script creates deterministic, reviewable examples based on the
failure categories identified during v0.2 evaluation.

Important:
    Generated records are candidates only.
    They must be reviewed by a human before being included in training.

Output:
    data/v0.3/candidates/gaialab_naija_v0.3_candidates.jsonl
"""

from __future__ import annotations

import argparse
import json
import random
from collections import Counter
from pathlib import Path
from typing import Any


DEFAULT_OUTPUT = Path(
    "data/v0.3/candidates/gaialab_naija_v0.3_candidates.jsonl"
)

DEFAULT_SEED = 42


CUSTOMER_SERVICE_CASES = [
    {
        "scenario": (
            "A customer ordered 12 office chairs, but only 10 arrived. "
            "The supplier has not yet confirmed when the remaining two "
            "chairs will be delivered."
        ),
        "instruction": (
            "Write a professional customer-service response. "
            "Acknowledge the shortage, say the matter is being checked, "
            "and do not invent a delivery date."
        ),
        "response": (
            "We apologize for the inconvenience. We received your report "
            "that only 10 of the 12 office chairs were delivered. We are "
            "checking the shortage with the supplier and will update you "
            "once the delivery date for the remaining two chairs is "
            "confirmed."
        ),
        "failure_tags": [
            "quantity_preservation",
            "uncertainty_preservation",
            "no_invented_date",
        ],
    },
    {
        "scenario": (
            "A technician inspected a faulty refrigerator, but the cause "
            "of the fault has not yet been confirmed."
        ),
        "instruction": (
            "Respond to the customer. Acknowledge the inspection, but do "
            "not claim that repairs or replacement have been approved."
        ),
        "response": (
            "Thank you for your patience. The technician has inspected "
            "the refrigerator, but the cause of the fault has not yet "
            "been confirmed. We will contact you after the inspection "
            "findings have been reviewed and the next step is agreed."
        ),
        "failure_tags": [
            "uncertainty_preservation",
            "no_unapproved_promise",
            "inspection_pending",
        ],
    },
    {
        "scenario": (
            "A customer's delivery was delayed by heavy rain. The business "
            "may be able to deliver tomorrow, but this has not been confirmed."
        ),
        "instruction": (
            "Write a concise update. Preserve the uncertainty and do not "
            "promise delivery tomorrow."
        ),
        "response": (
            "We apologize for the delay caused by the heavy rain. Delivery "
            "may be possible tomorrow, but this has not yet been confirmed. "
            "We will contact you as soon as the revised schedule is available."
        ),
        "failure_tags": [
            "weather_delay",
            "uncertainty_preservation",
            "no_delivery_guarantee",
        ],
    },
    {
        "scenario": (
            "A customer asks for free delivery after missing a collection "
            "appointment. The business can discuss delivery, but no decision "
            "has been made about the fee."
        ),
        "instruction": (
            "Offer another collection time or discuss delivery. Do not "
            "promise that delivery will be free."
        ),
        "response": (
            "We are sorry for the inconvenience. We can arrange another "
            "collection time or discuss a delivery option with you. Any "
            "delivery charge will need to be confirmed before the arrangement "
            "is completed."
        ),
        "failure_tags": [
            "negative_constraint",
            "no_free_delivery_promise",
            "business_usefulness",
        ],
    },
    {
        "scenario": (
            "A customer paid today and asks for the receipt to be dated "
            "last month."
        ),
        "instruction": (
            "Politely decline the incorrect date and offer a receipt with "
            "the actual payment date."
        ),
        "response": (
            "Thank you for your payment. We cannot issue a receipt with an "
            "incorrect earlier date. We can provide an accurate receipt "
            "showing today's payment date."
        ),
        "failure_tags": [
            "record_integrity",
            "date_preservation",
            "safe_refusal",
        ],
    },
]


BUSINESS_TERMINOLOGY_CASES = [
    {
        "term": "supplier lead time",
        "instruction": (
            "Explain supplier lead time using a phone-accessory shop that "
            "orders stock today."
        ),
        "response": (
            "Supplier lead time is the time between placing an order and "
            "receiving it. For example, if a phone-accessory shop orders "
            "chargers today and the supplier needs seven days to prepare "
            "and deliver them, the supplier lead time is seven days."
        ),
        "failure_tags": [
            "definition_accuracy",
            "simple_example",
            "business_context",
        ],
    },
    {
        "term": "accounts receivable",
        "instruction": (
            "Explain accounts receivable and overdue amounts using a "
            "cleaning business that has sent bills to three offices."
        ),
        "response": (
            "Accounts receivable is money customers owe the cleaning "
            "business for work already completed. If three offices have "
            "received bills and one bill has passed its payment date, all "
            "three unpaid bills are accounts receivable, while the late "
            "bill is also overdue."
        ),
        "failure_tags": [
            "definition_accuracy",
            "role_preservation",
            "payment_status",
        ],
    },
    {
        "term": "consignment sales",
        "instruction": (
            "Explain consignment sales using a craft maker and a gift shop. "
            "Mention that the agreement should be recorded clearly."
        ),
        "response": (
            "Consignment sales happen when a craft maker leaves products "
            "with a gift shop, but the shop pays only after the products "
            "are sold. The agreement should clearly record ownership, "
            "prices, payment terms, and what happens to unsold items."
        ),
        "failure_tags": [
            "definition_accuracy",
            "ownership_preservation",
            "agreement_documentation",
        ],
    },
    {
        "term": "stock shrinkage",
        "instruction": (
            "Explain stock shrinkage using damaged goods, counting mistakes, "
            "and missing items. Do not accuse any worker without evidence."
        ),
        "response": (
            "Stock shrinkage is the difference between the stock records "
            "and the items actually available. It may result from damaged "
            "goods, counting mistakes, or missing items. The business should "
            "investigate the difference without accusing anyone before "
            "evidence is available."
        ),
        "failure_tags": [
            "definition_accuracy",
            "no_unsupported_accusation",
            "evidence_required",
        ],
    },
]


ENGLISH_TO_PIDGIN_CASES = [
    {
        "source": (
            "Please do not make the transfer until we confirm the account "
            "details in writing."
        ),
        "target": (
            "Abeg, no make the transfer until we confirm the account details "
            "for writing."
        ),
        "failure_tags": [
            "translation_en_to_pidgin",
            "meaning_preservation",
            "payment_safety",
        ],
    },
    {
        "source": (
            "The generator repair may take one additional day because the "
            "required part has not arrived."
        ),
        "target": (
            "The generator repair fit take one extra day because the part "
            "wey dem need never arrive."
        ),
        "failure_tags": [
            "translation_en_to_pidgin",
            "uncertainty_preservation",
            "cause_preservation",
        ],
    },
    {
        "source": (
            "We received four of the six cartons. Please check the remaining "
            "two and update us before noon."
        ),
        "target": (
            "We receive four out of the six cartons. Abeg check the remaining "
            "two and update us before twelve noon."
        ),
        "failure_tags": [
            "translation_en_to_pidgin",
            "quantity_preservation",
            "time_preservation",
        ],
    },
    {
        "source": (
            "These pastries contain groundnuts. Do not serve them to anyone "
            "with a groundnut allergy."
        ),
        "target": (
            "Groundnut dey inside these pastries. No serve am give anybody "
            "wey get groundnut allergy."
        ),
        "failure_tags": [
            "translation_en_to_pidgin",
            "allergy_warning",
            "safety_preservation",
        ],
    },
    {
        "source": (
            "Your booth has moved from the main hall to the covered courtyard. "
            "The setup time remains 7 a.m."
        ),
        "target": (
            "Dem don move your booth from the main hall go the covered "
            "courtyard. Setup time still remain 7 a.m."
        ),
        "failure_tags": [
            "translation_en_to_pidgin",
            "location_preservation",
            "time_preservation",
        ],
    },
]


PIDGIN_TO_ENGLISH_CASES = [
    {
        "source": (
            "Supplier never bring the remaining bags. We go count wetin "
            "arrive and send you the correct balance this evening."
        ),
        "target": (
            "The supplier has not delivered the remaining bags. We will "
            "count what has arrived and send you the correct balance this "
            "evening."
        ),
        "failure_tags": [
            "translation_pidgin_to_en",
            "meaning_preservation",
            "time_preservation",
        ],
    },
    {
        "source": (
            "Abeg no use the cream again until we check the batch number "
            "and talk to you."
        ),
        "target": (
            "Please do not use the cream again until we check the batch "
            "number and contact you."
        ),
        "failure_tags": [
            "translation_pidgin_to_en",
            "safety_preservation",
            "speaker_role",
        ],
    },
    {
        "source": (
            "Na only two tables return without damage. We still dey inspect "
            "the other four before we send final report."
        ),
        "target": (
            "Only two tables were returned without damage. We are still "
            "inspecting the other four before sending the final report."
        ),
        "failure_tags": [
            "translation_pidgin_to_en",
            "quantity_preservation",
            "inspection_pending",
        ],
    },
    {
        "source": (
            "We don match five payments, but one transfer still no get order "
            "number. Abeg confirm the sender name."
        ),
        "target": (
            "We have matched five payments, but one transfer still has no "
            "order number. Please confirm the sender's name."
        ),
        "failure_tags": [
            "translation_pidgin_to_en",
            "payment_status",
            "request_preservation",
        ],
    },
    {
        "source": (
            "If rain heavy tomorrow morning, we fit move the delivery go "
            "afternoon, but we go call you first."
        ),
        "target": (
            "If it rains heavily tomorrow morning, we may move the delivery "
            "to the afternoon, but we will call you first."
        ),
        "failure_tags": [
            "translation_pidgin_to_en",
            "conditional_preservation",
            "uncertainty_preservation",
        ],
    },
]


def make_messages(
    system_prompt: str,
    user_prompt: str,
    assistant_response: str,
) -> list[dict[str, str]]:
    """Create chat-style training messages."""

    return [
        {
            "role": "system",
            "content": system_prompt,
        },
        {
            "role": "user",
            "content": user_prompt,
        },
        {
            "role": "assistant",
            "content": assistant_response,
        },
    ]


def build_customer_service_records() -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []

    for item in CUSTOMER_SERVICE_CASES:
        prompt = f"{item['scenario']}\n\n{item['instruction']}"

        records.append(
            {
                "category": "customer_service",
                "task": "business_response",
                "source_language": "english",
                "target_language": "english",
                "difficulty": "medium",
                "failure_tags": item["failure_tags"],
                "messages": make_messages(
                    (
                        "You are GaiaLab Naija Assistant. Write accurate, "
                        "concise business responses. Preserve all facts and "
                        "uncertainty. Do not invent dates, prices, policies, "
                        "causes, approvals, or guarantees."
                    ),
                    prompt,
                    item["response"],
                ),
            }
        )

    return records


def build_terminology_records() -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []

    for item in BUSINESS_TERMINOLOGY_CASES:
        records.append(
            {
                "category": "business_terminology",
                "task": "explanation",
                "source_language": "english",
                "target_language": "english",
                "difficulty": "medium",
                "failure_tags": item["failure_tags"],
                "messages": make_messages(
                    (
                        "You are GaiaLab Naija Assistant. Explain business "
                        "terms simply and accurately for small business owners. "
                        "Do not invent facts or present legal advice."
                    ),
                    item["instruction"],
                    item["response"],
                ),
            }
        )

    return records


def build_translation_records() -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []

    for item in ENGLISH_TO_PIDGIN_CASES:
        records.append(
            {
                "category": "translation_en_to_pidgin",
                "task": "translation",
                "source_language": "english",
                "target_language": "nigerian_pidgin",
                "difficulty": "medium",
                "failure_tags": item["failure_tags"],
                "messages": make_messages(
                    (
                        "Translate business messages into clear, natural "
                        "Nigerian Pidgin. Preserve quantities, dates, times, "
                        "conditions, uncertainty, warnings, and speaker roles."
                    ),
                    item["source"],
                    item["target"],
                ),
            }
        )

    for item in PIDGIN_TO_ENGLISH_CASES:
        records.append(
            {
                "category": "translation_pidgin_to_en",
                "task": "translation",
                "source_language": "nigerian_pidgin",
                "target_language": "professional_nigerian_english",
                "difficulty": "medium",
                "failure_tags": item["failure_tags"],
                "messages": make_messages(
                    (
                        "Translate Nigerian Pidgin into clear professional "
                        "Nigerian English. Preserve quantities, dates, times, "
                        "conditions, uncertainty, warnings, and speaker roles."
                    ),
                    item["source"],
                    item["target"],
                ),
            }
        )

    return records


def add_record_ids(
    records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Add stable v0.3 candidate identifiers."""

    for index, record in enumerate(records, start=1):
        record["id"] = f"v03_candidate_{index:04d}"
        record["status"] = "needs_human_review"
        record["approved_for_training"] = False
        record["review_notes"] = ""

    return records


def validate_record(record: dict[str, Any]) -> list[str]:
    """Validate one generated record."""

    errors: list[str] = []

    required_fields = {
        "id",
        "category",
        "task",
        "source_language",
        "target_language",
        "difficulty",
        "failure_tags",
        "messages",
        "status",
        "approved_for_training",
        "review_notes",
    }

    missing = required_fields - record.keys()

    if missing:
        errors.append(
            f"Missing fields: {', '.join(sorted(missing))}"
        )

    messages = record.get("messages")

    if not isinstance(messages, list) or len(messages) != 3:
        errors.append("messages must contain system, user, and assistant")
        return errors

    expected_roles = ["system", "user", "assistant"]
    actual_roles = [
        message.get("role")
        for message in messages
        if isinstance(message, dict)
    ]

    if actual_roles != expected_roles:
        errors.append(
            f"Invalid message roles: {actual_roles}"
        )

    for message in messages:
        if not isinstance(message, dict):
            errors.append("Every message must be an object")
            continue

        content = message.get("content")

        if not isinstance(content, str) or not content.strip():
            errors.append(
                f"Empty content for role: {message.get('role')}"
            )

    assistant_text = messages[-1].get("content", "")

    if len(assistant_text.split()) > 160:
        errors.append("Assistant response exceeds 160 words")

    if record.get("status") != "needs_human_review":
        errors.append("Generated records must require human review")

    if record.get("approved_for_training") is not False:
        errors.append(
            "Generated records cannot be automatically approved"
        )

    return errors


def validate_dataset(
    records: list[dict[str, Any]],
) -> None:
    """Validate the complete dataset."""

    all_errors: list[str] = []
    seen_ids: set[str] = set()
    seen_user_prompts: set[str] = set()

    for record in records:
        record_id = str(record.get("id", "unknown"))

        if record_id in seen_ids:
            all_errors.append(f"{record_id}: duplicate ID")
        else:
            seen_ids.add(record_id)

        messages = record.get("messages", [])

        if len(messages) >= 2:
            user_prompt = messages[1].get("content", "").strip().lower()

            if user_prompt in seen_user_prompts:
                all_errors.append(
                    f"{record_id}: duplicate user prompt"
                )
            else:
                seen_user_prompts.add(user_prompt)

        for error in validate_record(record):
            all_errors.append(f"{record_id}: {error}")

    if all_errors:
        formatted = "\n".join(
            f"- {error}" for error in all_errors
        )
        raise ValueError(
            f"Dataset validation failed:\n{formatted}"
        )


def write_jsonl(
    records: list[dict[str, Any]],
    output_path: Path,
    overwrite: bool,
) -> None:
    """Write generated records to JSONL."""

    if output_path.exists() and not overwrite:
        raise FileExistsError(
            f"Output already exists: {output_path}. "
            "Use --overwrite to replace it."
        )

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with output_path.open(
        "w",
        encoding="utf-8",
        newline="\n",
    ) as file:
        for record in records:
            file.write(
                json.dumps(
                    record,
                    ensure_ascii=False,
                )
                + "\n"
            )


def print_summary(records: list[dict[str, Any]]) -> None:
    """Print dataset statistics."""

    categories = Counter(
        record["category"] for record in records
    )

    print(f"Generated {len(records)} candidate records.")

    for category, count in sorted(categories.items()):
        print(f"  {category}: {count}")

    print()
    print("All records are marked:")
    print("  status = needs_human_review")
    print("  approved_for_training = false")


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate reviewable GaiaLab Naija Assistant "
            "v0.3 candidate training records."
        )
    )

    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Destination JSONL path.",
    )

    parser.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_SEED,
        help="Random seed used to shuffle candidate records.",
    )

    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace the output file if it already exists.",
    )

    return parser.parse_args()


def main() -> int:
    args = parse_arguments()

    records: list[dict[str, Any]] = []
    records.extend(build_customer_service_records())
    records.extend(build_terminology_records())
    records.extend(build_translation_records())

    random_generator = random.Random(args.seed)
    random_generator.shuffle(records)

    add_record_ids(records)
    validate_dataset(records)

    try:
        write_jsonl(
            records,
            args.output,
            overwrite=args.overwrite,
        )
    except FileExistsError as exc:
        print(f"Generation failed: {exc}")
        return 1

    print_summary(records)
    print(f"\nOutput: {args.output}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())