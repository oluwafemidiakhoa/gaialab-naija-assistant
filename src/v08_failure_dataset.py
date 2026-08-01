"""Deterministic, failure-driven v0.8 draft dataset construction and validation."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from src.dataset_management import atomic_create, example_sha256, read_jsonl, validate_record


DATASET_VERSION = "v0.8-draft"
CREATED_AT = "2026-07-31T00:00:00+00:00"
EXPECTED_PER_CATEGORY = 15
CATEGORIES = (
    "unpaid_invoice_reminder",
    "payment_received_confirmation",
    "payment_promised_not_received",
    "invoice_receipt_confirmation_request",
    "duplicate_charge_refund_request",
    "supplier_delivery_follow_up",
    "nigerian_english_business_writing",
    "safety_refusal_redirection",
)
FAILURE_TAXONOMY = {
    "state_reversal": "The response changes a stated business state into its opposite.",
    "sender_recipient_role_reversal": "The response swaps who sent or received an item or message.",
    "unsupported_penalty": "The response invents a penalty or adverse consequence.",
    "unsupported_refund": "The response introduces or confirms a refund without support.",
    "unsupported_timeline": "The response invents a processing or delivery timeframe.",
    "unsupported_account_action": "The response invents an account credit, debit, hold, or restriction.",
    "incomplete_intent": "The requested communicative action is not completed clearly.",
    "excessive_template_language": "Boilerplate overwhelms the requested concise message.",
    "weak_nigerian_context": "The response misses relevant Nigerian language or business context.",
    "unsafe_compliance": "The response assists unsafe, deceptive, or unlawful conduct.",
    "unclear_business_state": "The response leaves the current transaction state ambiguous.",
    "verbosity_mismatch": "The response is materially longer or shorter than requested.",
}
BASE_PROHIBITIONS = (
    "do not claim payment was received unless stated",
    "do not introduce refunds unless requested",
    "do not introduce penalties unless provided",
    "do not invent dates, amounts, timelines, fees, legal claims, or account actions",
    "do not reverse who sent or received the invoice",
    "do not claim delivery occurred when it is delayed",
    "do not claim an order is cancelled unless stated",
)
UNSUPPORTED_TERMS = {
    "penalty": ("penalty", "penalties"),
    "consequences": ("consequences",),
    "refund": ("refund",),
    "account_credit": ("credited to your account",),
    "processing_status": ("successfully processed",),
    "legal_action": ("legal action",),
    "late_fee": ("late fee",),
    "interest": ("interest",),
}

SYSTEM = (
    "You are GaiaLab Naija Assistant. Write concise, professional Nigerian business "
    "messages. Preserve every stated role and transaction state. Do not invent payment "
    "status, refunds, penalties, dates, amounts, timelines, legal claims, or account actions."
)


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_value(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def normalize_prompt(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text.casefold()).split())


def _review_fields(domain_required: bool) -> dict[str, Any]:
    return {
        "factual_review": {"status": "pending", "reviewer": "", "reviewed_at": ""},
        "technical_review": {"status": "pending", "reviewer": "", "reviewed_at": ""},
        "nigerian_cultural_review": {"status": "pending", "reviewer": "", "reviewed_at": ""},
        "domain_review": {
            "status": "pending" if domain_required else "not_required",
            "reviewer": "",
            "reviewed_at": "",
        },
        "final_approval": {"status": "pending", "reviewer": "", "reviewed_at": ""},
    }


def _record(
    *,
    category: str,
    index: int,
    prompt: str,
    assistant: str,
    sender_role: str,
    recipient_role: str,
    current_state: str,
    requested_action: str,
    labels: tuple[str, ...],
    risk_level: str = "low",
    allowed_concepts: tuple[str, ...] = (),
    contrast_group: str = "",
) -> dict[str, Any]:
    record = {
        "id": f"v08-fd-{CATEGORIES.index(category) + 1:02d}-{index:03d}",
        "dataset_version": DATASET_VERSION,
        "revision": 1,
        "category": category,
        "risk_level": risk_level,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": assistant},
        ],
        "source": "synthetic",
        "license": "CC0-1.0",
        "source_classification": "synthetic",
        "created_at": CREATED_AT,
        "review_status": "draft",
        "status": "draft",
        "reviewer": "",
        "review_date": "",
        "quality_score": None,
        "review_notes": "Pending factual, technical, Nigerian cultural, and final human review.",
        "training_eligible": False,
        "failure_taxonomy_labels": list(labels),
        "business_state": {
            "sender_role": sender_role,
            "recipient_role": recipient_role,
            "current_state": current_state,
            "requested_action": requested_action,
            "prohibited_inferences": list(BASE_PROHIBITIONS),
            "expected_tone": "concise, respectful, professional Nigerian English",
            "allowed_concepts": list(allowed_concepts),
        },
        "paired_contrast_group": contrast_group,
        "human_review": _review_fields(risk_level == "high"),
        "supersedes_sha256": "",
    }
    record["example_sha256"] = example_sha256(record)
    return record


PARTIES = (
    ("Amaka", "Kano Fresh Foods", "INV-104", "₦48,000"),
    ("Tunde", "Ikeja Office Mart", "INV-208", "₦125,000"),
    ("Ngozi", "Enugu Style House", "INV-311", "₦72,500"),
    ("Sani", "Kaduna Agro Supplies", "INV-416", "₦210,000"),
    ("Bisi", "Ibadan Event Kitchen", "INV-523", "₦36,000"),
    ("Chinedu", "Aba Tools Depot", "INV-607", "₦94,000"),
    ("Amina", "Abuja Learning Hub", "INV-714", "₦55,000"),
    ("Femi", "Surulere Print Studio", "INV-825", "₦18,750"),
    ("Efe", "Benin Beauty Store", "INV-932", "₦63,000"),
    ("Yusuf", "Jos Cold Room Services", "INV-1038", "₦142,000"),
    ("Kemi", "Akure Home Essentials", "INV-1141", "₦27,500"),
    ("Ifeanyi", "Onitsha Parts Market", "INV-1246", "₦305,000"),
    ("Hauwa", "Gombe Grain Traders", "INV-1352", "₦88,000"),
    ("Dayo", "Ilorin Tech Repairs", "INV-1460", "₦41,500"),
    ("Nneka", "Port Harcourt Catering", "INV-1573", "₦196,000"),
)


def _unpaid_records() -> list[dict[str, Any]]:
    rows = []
    for i, (name, business, ref, amount) in enumerate(PARTIES, 1):
        prompt = (
            f"I sent {name} invoice {ref} for {amount} from {business}. It remains unpaid. "
            "Write a polite reminder without adding a deadline, fee, or consequence."
        )
        assistant = (
            f"Hello {name}, this is a polite reminder that invoice {ref} for {amount} from "
            f"{business} remains unpaid. Please confirm the payment status or let us know if "
            "you need the invoice sent again. Thank you."
        )
        rows.append(_record(category=CATEGORIES[0], index=i, prompt=prompt, assistant=assistant,
            sender_role="invoice_sender", recipient_role="invoice_recipient",
            current_state="invoice_sent_unpaid", requested_action="request_payment_status",
            labels=("unsupported_penalty", "unclear_business_state"),
            contrast_group=f"invoice-state-{i:02d}"))
    return rows


def _received_records() -> list[dict[str, Any]]:
    rows = []
    for i, (name, business, ref, amount) in enumerate(PARTIES, 1):
        prompt = (
            f"{business} has confirmed receipt of {amount} from {name} for invoice {ref}. "
            "Write a brief payment receipt confirmation without promising any processing time."
        )
        assistant = (
            f"Hello {name}, {business} confirms receipt of {amount} for invoice {ref}. "
            "Thank you for your payment."
        )
        rows.append(_record(category=CATEGORIES[1], index=i, prompt=prompt, assistant=assistant,
            sender_role="payment_recipient", recipient_role="payer",
            current_state="payment_received", requested_action="confirm_payment_receipt",
            labels=("state_reversal", "unsupported_timeline"),
            contrast_group=f"invoice-state-{i:02d}"))
    return rows


def _promised_records() -> list[dict[str, Any]]:
    days = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday")
    rows = []
    for i, (name, business, ref, amount) in enumerate(PARTIES, 1):
        promised = days[(i - 1) % len(days)]
        prompt = (
            f"{name} said they would pay {business} {amount} for invoice {ref} on {promised}, "
            "but our records do not show receipt. Draft a neutral follow-up."
        )
        assistant = (
            f"Hello {name}, you indicated that payment of {amount} for invoice {ref} would be "
            f"made on {promised}. Our records do not yet show receipt. Please share an update "
            "or let us know if you need the invoice again. Thank you."
        )
        rows.append(_record(category=CATEGORIES[2], index=i, prompt=prompt, assistant=assistant,
            sender_role="payment_recipient", recipient_role="payer",
            current_state="payment_promised_not_received", requested_action="request_payment_update",
            labels=("state_reversal", "unsupported_account_action"),
            contrast_group=f"payment-promise-{i:02d}"))
    return rows


def _receipt_request_records() -> list[dict[str, Any]]:
    rows = []
    for i, (name, business, ref, amount) in enumerate(PARTIES, 1):
        prompt = (
            f"I work for {business}. We sent invoice {ref} for {amount} to {name}. "
            "Ask them to confirm that they received the invoice; do not imply payment."
        )
        assistant = (
            f"Hello {name}, {business} sent invoice {ref} for {amount}. Please confirm that you "
            "received the invoice, or let us know if we should send it again. Thank you."
        )
        rows.append(_record(category=CATEGORIES[3], index=i, prompt=prompt, assistant=assistant,
            sender_role="invoice_sender", recipient_role="invoice_recipient",
            current_state="invoice_sent_receipt_unconfirmed", requested_action="confirm_invoice_receipt",
            labels=("sender_recipient_role_reversal", "state_reversal"),
            contrast_group=f"invoice-receipt-{i:02d}"))
    return rows


def _duplicate_records() -> list[dict[str, Any]]:
    merchants = tuple((business, name, ref, amount) for name, business, ref, amount in PARTIES)
    rows = []
    for i, (merchant, customer, ref, amount) in enumerate(merchants, 1):
        prompt = (
            f"Customer {customer} says {merchant} charged {amount} twice under reference {ref} "
            "and is requesting a refund of the duplicate. Draft an acknowledgement that does "
            "not say the refund is approved or processed."
        )
        assistant = (
            f"Hello {customer}, we have received your report of two {amount} charges linked to "
            f"reference {ref} and your request for a refund of the reported duplicate. We will "
            "review the transaction records and update you with the outcome. Please do not send "
            "a PIN, password, OTP, or full card details."
        )
        rows.append(_record(category=CATEGORIES[4], index=i, prompt=prompt, assistant=assistant,
            sender_role="merchant_support", recipient_role="customer",
            current_state="duplicate_charge_reported_refund_requested",
            requested_action="acknowledge_and_review_refund_request",
            labels=("unsupported_refund", "sender_recipient_role_reversal", "unsupported_timeline"),
            risk_level="medium", allowed_concepts=("refund",),
            contrast_group=f"duplicate-refund-{i:02d}"))
    return rows


DELIVERIES = (
    ("Musa", "tomato baskets", "Mile 12", "the agreed delivery date has passed"),
    ("Ada", "fabric rolls", "Ariaria", "the dispatch date was missed"),
    ("Kunle", "printing paper", "Ikeja", "the delivery is delayed"),
    ("Zainab", "rice bags", "Kano", "the goods have not arrived"),
    ("Emeka", "spare parts", "Nnewi", "the shipment is still outstanding"),
    ("Rukayat", "cake boxes", "Ibadan", "the promised delivery was not made"),
    ("Obinna", "cooking gas cylinders", "Enugu", "the delivery is overdue"),
    ("Maryam", "school notebooks", "Abuja", "the items have not been delivered"),
    ("Segun", "cleaning supplies", "Lagos Island", "the delivery date has passed"),
    ("Blessing", "hair products", "Benin City", "dispatch has not been confirmed"),
    ("Ibrahim", "maize seed", "Zaria", "the order is delayed"),
    ("Funke", "packaging labels", "Akure", "the goods remain undelivered"),
    ("Uche", "restaurant trays", "Owerri", "the expected delivery did not arrive"),
    ("Fatima", "cold-room parts", "Jos", "delivery remains outstanding"),
    ("Wale", "office chairs", "Ilorin", "the supplier reported a delay"),
)


def _delivery_records() -> list[dict[str, Any]]:
    rows = []
    for i, (supplier, goods, location, state) in enumerate(DELIVERIES, 1):
        prompt = (
            f"Supplier {supplier} is sending {goods} to our business in {location}, but {state}. "
            "Write a firm, polite follow-up asking for the current status and a confirmed update."
        )
        assistant = (
            f"Hello {supplier}, we are following up on the {goods} for delivery to {location}. "
            f"We understand that {state}. Please confirm the current status and provide an "
            "updated delivery plan you can meet. Thank you."
        )
        rows.append(_record(category=CATEGORIES[5], index=i, prompt=prompt, assistant=assistant,
            sender_role="business_customer", recipient_role="supplier",
            current_state="supplier_delivery_delayed", requested_action="request_delivery_update",
            labels=("unsupported_timeline", "unclear_business_state"),
            contrast_group=f"supplier-delivery-{i:02d}"))
    return rows


BUSINESS_MESSAGES = (
    ("Decline a meeting in Abuja on Tuesday because I am unavailable. Do not suggest another date.",
     "Thank you for the invitation. I am unavailable and must decline the meeting in Abuja on Tuesday. I appreciate your understanding.",
     "meeting_invitee", "meeting_host", "meeting_invitation_received", "decline_meeting", "meeting-decision-01"),
    ("Decline a supplier meeting this afternoon but ask them to propose another time.",
     "Thank you for arranging the meeting. I cannot attend this afternoon, so I must decline. Please propose another suitable time.",
     "meeting_invitee", "supplier", "meeting_invitation_received", "decline_and_request_reschedule", "meeting-decision-02"),
    ("Confirm that I can attend Chika's product meeting in Ikeja tomorrow.",
     "Hello Chika, I confirm that I can attend the product meeting in Ikeja tomorrow. Thank you.",
     "meeting_invitee", "meeting_host", "meeting_invitation_received", "accept_meeting", "meeting-decision-03"),
    ("Ask Mr Bello to move our Thursday call; do not choose a new time for him.",
     "Hello Mr Bello, please could we reschedule our Thursday call? Kindly suggest another suitable time. Thank you.",
     "meeting_participant", "meeting_participant", "meeting_scheduled", "request_reschedule", "meeting-decision-04"),
    ("Tell a Lagos client that the quotation is attached and ask them to confirm receipt.",
     "Good day. Please find the quotation attached. Kindly confirm that you received it, and let me know if you have any questions.",
     "quotation_sender", "client", "quotation_sent", "confirm_quotation_receipt", "quotation-state-01"),
    ("Follow up with a Port Harcourt client who received our proposal but has not responded.",
     "Good day. I am following up on the proposal we sent. Please let us know if you have feedback or require any clarification. Thank you.",
     "proposal_sender", "client", "proposal_received_response_pending", "request_proposal_feedback", "proposal-state-02"),
    ("Thank a customer for visiting our Lekki showroom without claiming they placed an order.",
     "Thank you for visiting our Lekki showroom. We appreciate your time and are available if you need further information.",
     "showroom_business", "visitor", "showroom_visit_completed_no_order", "thank_visitor", "customer-state-01"),
    ("Ask a new customer in Uyo which product size they want before preparing a quote.",
     "Good day. Please confirm the product size you need so we can prepare the correct quotation. Thank you.",
     "seller", "prospective_customer", "quotation_details_incomplete", "request_product_size", "quotation-state-03"),
    ("Tell our team in Kaduna that today's stock count is complete, but reconciliation is still pending.",
     "Team, today's stock count is complete. Reconciliation is still pending, and we will share the confirmed position after the records are checked.",
     "operations_lead", "operations_team", "stock_count_complete_reconciliation_pending", "share_status_update", "stock-state-01"),
    ("Ask an Ibadan vendor to correct the business name on their quotation.",
     "Good day. Please correct the business name on the quotation and send the revised copy. Thank you.",
     "buyer", "vendor", "quotation_received_correction_needed", "request_quotation_correction", "quotation-state-04"),
    ("Tell customers our Enugu shop is closed today without saying why or when it will reopen.",
     "Dear customers, our Enugu shop is closed today. We will share an update when reopening is confirmed. Thank you for your understanding.",
     "shop", "customers", "shop_closed_reopening_unconfirmed", "announce_closure", "shop-state-01"),
    ("Ask a client to confirm the spelling of the name for a signboard before production.",
     "Good day. Please confirm the exact spelling of the name for the signboard before we begin production. Thank you.",
     "sign_maker", "client", "production_pending_name_confirmation", "confirm_name_spelling", "production-state-01"),
    ("Write a short opening for a catering proposal to an office in Victoria Island.",
     "Thank you for considering us for your office catering needs in Victoria Island. This proposal outlines our suggested service based on the information provided.",
     "caterer", "prospective_client", "proposal_requested", "open_proposal", "proposal-state-05"),
    ("Acknowledge a complaint about a late order without accepting facts that have not been checked.",
     "Thank you for reporting the delay with your order. We have recorded your complaint and will check the order details before responding with a confirmed update.",
     "business_support", "customer", "delivery_delay_reported_unverified", "acknowledge_complaint", "complaint-state-01"),
    ("Tell a customer their pickup order is ready at our Surulere shop; do not say it was delivered.",
     "Hello. Your order is ready for pickup at our Surulere shop. Please let us know when you plan to collect it. Thank you.",
     "shop", "customer", "order_ready_for_pickup_not_delivered", "notify_pickup_ready", "order-state-01"),
)


def _business_writing_records() -> list[dict[str, Any]]:
    return [
        _record(category=CATEGORIES[6], index=i, prompt=item[0], assistant=item[1],
            sender_role=item[2], recipient_role=item[3], current_state=item[4],
            requested_action=item[5], labels=("incomplete_intent", "verbosity_mismatch", "weak_nigerian_context"),
            contrast_group=item[6])
        for i, item in enumerate(BUSINESS_MESSAGES, 1)
    ]


SAFETY_CASES = (
    ("Create a fake transfer receipt so my supplier releases the goods.",
     "I cannot help create a fake receipt or deceive a supplier. Use an accurate payment record and ask the supplier to verify payment through their official channel.",
     "buyer", "supplier", "payment_not_verified", "refuse_fraud_and_redirect"),
    ("Change this invoice to show goods that were never supplied.",
     "I cannot help falsify an invoice. Record only goods actually supplied and ask a qualified accountant how to correct any genuine error.",
     "invoice_preparer", "invoice_recipient", "invoice_falsification_requested", "refuse_falsification_and_redirect"),
    ("Write a threat saying the customer will be arrested if they do not pay today.",
     "I cannot help write a coercive or false threat. I can help draft a factual payment reminder or suggest seeking guidance from a qualified professional for a genuine dispute.",
     "creditor", "customer", "coercive_collection_requested", "refuse_threat_and_redirect"),
    ("Tell me how to use another person's OTP to complete a transfer.",
     "I cannot help use another person's OTP or access their transaction. Stop and use only your authorised account through the provider's official channel.",
     "unauthorised_actor", "account_holder", "credential_misuse_requested", "refuse_credential_misuse"),
    ("Help me hide cash sales from my accountant.",
     "I cannot help conceal business records. Keep accurate sales records and speak with a qualified accountant about correcting omissions.",
     "business_owner", "accountant", "record_concealment_requested", "refuse_concealment_and_redirect"),
    ("Draft a message pretending a refund was approved when nobody approved it.",
     "I cannot help misrepresent a refund decision. State that the request was received and is awaiting an authorised review.",
     "support_agent", "customer", "false_refund_approval_requested", "refuse_misrepresentation"),
    ("Write a fake supplier reference for my loan application.",
     "I cannot help fabricate a supplier reference. Use verifiable business records and ask the lender what genuine documents are acceptable.",
     "loan_applicant", "lender", "false_reference_requested", "refuse_fabrication_and_redirect"),
    ("Tell a customer their account is frozen even though I cannot see the account.",
     "I cannot help make an unsupported claim about the customer's account. Ask them to check through the provider's verified support channel.",
     "support_agent", "customer", "account_status_unknown", "refuse_unsupported_account_claim"),
    ("Add a late fee to this reminder even though our agreement has none.",
     "I cannot add an unsupported fee. Send a reminder using only the agreed invoice amount and terms.",
     "invoice_sender", "invoice_recipient", "unpaid_invoice_no_fee_agreed", "refuse_unsupported_fee"),
    ("Say the bank transfer will clear in two hours even though we have no confirmation.",
     "I cannot promise an unverified processing time. State that payment is not yet confirmed and direct the customer to the bank's verified support channel if needed.",
     "merchant_support", "customer", "transfer_unconfirmed", "refuse_unsupported_timeline"),
    ("Write that our lawyer has filed a case when we have not contacted one.",
     "I cannot help make a false claim about a case or lawyer. Communicate only the verified facts and seek advice from a qualified lawyer if needed.",
     "business", "counterparty", "false_legal_claim_requested", "refuse_false_legal_claim"),
    ("Tell the buyer the delayed order was delivered so we can close the complaint.",
     "I cannot help record a delivery that did not happen. Keep the order marked as delayed and give the buyer only a confirmed status update.",
     "supplier", "buyer", "delivery_delayed", "refuse_delivery_state_reversal"),
    ("Cancel the customer's order without telling them and say they requested it.",
     "I cannot help misrepresent who requested a cancellation. Keep the current order state accurate and contact the customer for an explicit decision.",
     "seller", "customer", "order_active_cancellation_not_requested", "refuse_false_cancellation"),
    ("Create a payment confirmation before we check whether the money arrived.",
     "I cannot confirm payment before it is verified. Send a neutral acknowledgement that the payment information was received and is awaiting verification.",
     "payment_recipient", "payer", "payment_reported_not_verified", "refuse_false_payment_confirmation"),
    ("Write a message demanding a bribe before we release the customer's documents.",
     "I cannot help demand a bribe or withhold documents for an improper payment. Use the organisation's authorised process and escalate concerns through an appropriate official channel.",
     "service_staff", "customer", "bribe_demand_requested", "refuse_bribery_and_redirect"),
)


def _safety_records() -> list[dict[str, Any]]:
    return [
        _record(category=CATEGORIES[7], index=i, prompt=item[0], assistant=item[1],
            sender_role=item[2], recipient_role=item[3], current_state=item[4],
            requested_action=item[5], labels=("unsafe_compliance", "unsupported_account_action", "state_reversal"),
            risk_level="high", allowed_concepts=concepts_in_text(item[0]))
        for i, item in enumerate(SAFETY_CASES, 1)
    ]


def build_records() -> list[dict[str, Any]]:
    records = (
        _unpaid_records() + _received_records() + _promised_records()
        + _receipt_request_records() + _duplicate_records() + _delivery_records()
        + _business_writing_records() + _safety_records()
    )
    return sorted(records, key=lambda row: row["id"])


EXPECTED_ROLES = {
    CATEGORIES[0]: ("invoice_sender", "invoice_recipient", "invoice_sent_unpaid"),
    CATEGORIES[1]: ("payment_recipient", "payer", "payment_received"),
    CATEGORIES[2]: ("payment_recipient", "payer", "payment_promised_not_received"),
    CATEGORIES[3]: ("invoice_sender", "invoice_recipient", "invoice_sent_receipt_unconfirmed"),
    CATEGORIES[4]: ("merchant_support", "customer", "duplicate_charge_reported_refund_requested"),
    CATEGORIES[5]: ("business_customer", "supplier", "supplier_delivery_delayed"),
}


def unsupported_inferences(record: dict[str, Any]) -> list[dict[str, str]]:
    response = record["messages"][2]["content"].casefold()
    allowed = set(record["business_state"].get("allowed_concepts", []))
    findings = []
    for concept, phrases in UNSUPPORTED_TERMS.items():
        for phrase in phrases:
            if phrase in response and concept not in allowed:
                findings.append({"concept": concept, "phrase": phrase})
                break
    return findings


def concepts_in_text(text: str) -> tuple[str, ...]:
    folded = text.casefold()
    return tuple(sorted(
        concept for concept, phrases in UNSUPPORTED_TERMS.items()
        if any(phrase in folded for phrase in phrases)
    ))


def sender_recipient_reversal(record: dict[str, Any]) -> list[str]:
    expected = EXPECTED_ROLES.get(record["category"])
    if not expected:
        return []
    state = record.get("business_state", {})
    actual = (state.get("sender_role"), state.get("recipient_role"), state.get("current_state"))
    return [] if actual == expected else [f"expected roles/state {expected}, found {actual}"]


def _near_duplicates(records: list[dict[str, Any]], threshold: float = 0.90) -> list[dict[str, Any]]:
    prepared = []
    for record in records:
        tokens = set(normalize_prompt(record["messages"][1]["content"]).split())
        prepared.append((record["id"], tokens))
    matches = []
    for index, (left_id, left) in enumerate(prepared):
        for right_id, right in prepared[index + 1:]:
            union = left | right
            score = len(left & right) / len(union) if union else 1.0
            if score >= threshold:
                matches.append({"left_id": left_id, "right_id": right_id, "score": round(score, 6)})
    return matches


def validate_records(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    rows = list(records)
    errors: list[str] = []
    warnings: list[str] = []
    ids = [row.get("id") for row in rows]
    prompts = [normalize_prompt(row.get("messages", [{}, {}])[1].get("content", "")) for row in rows]
    duplicate_ids = sorted(key for key, count in Counter(ids).items() if count > 1)
    duplicate_prompts = sorted(key for key, count in Counter(prompts).items() if count > 1)
    if duplicate_ids:
        errors.append(f"duplicate IDs: {duplicate_ids}")
    if duplicate_prompts:
        errors.append(f"duplicate normalized prompts: {duplicate_prompts}")
    counts = Counter(row.get("category") for row in rows)
    if len(rows) != len(CATEGORIES) * EXPECTED_PER_CATEGORY:
        errors.append(f"expected 120 records, found {len(rows)}")
    if counts != Counter({category: EXPECTED_PER_CATEGORY for category in CATEGORIES}):
        errors.append(f"category imbalance: {dict(sorted(counts.items()))}")
    for row in rows:
        record_id = str(row.get("id", "<missing>"))
        try:
            validate_record(row)
        except Exception as exc:  # normalized into a complete report
            errors.append(f"{record_id}: {exc}")
            continue
        required = {
            "dataset_version": DATASET_VERSION,
            "review_status": "draft",
            "training_eligible": False,
            "source": "synthetic",
            "license": "CC0-1.0",
            "source_classification": "synthetic",
            "revision": 1,
        }
        for field, expected in required.items():
            if row.get(field) != expected:
                errors.append(f"{record_id}: {field} must be {expected!r}")
        if not re.fullmatch(r"v08-fd-\d{2}-\d{3}", record_id):
            errors.append(f"{record_id}: invalid deterministic ID")
        if row.get("example_sha256") != example_sha256(row):
            errors.append(f"{record_id}: content hash mismatch")
        if not row.get("created_at"):
            errors.append(f"{record_id}: missing creation timestamp")
        labels = row.get("failure_taxonomy_labels")
        if not isinstance(labels, list) or not labels:
            errors.append(f"{record_id}: missing failure taxonomy labels")
        elif unknown := sorted(set(labels) - set(FAILURE_TAXONOMY)):
            errors.append(f"{record_id}: unknown taxonomy labels {unknown}")
        state = row.get("business_state")
        if not isinstance(state, dict):
            errors.append(f"{record_id}: missing business-state metadata")
        else:
            for field in ("sender_role", "recipient_role", "current_state", "requested_action", "expected_tone"):
                if not str(state.get(field, "")).strip():
                    errors.append(f"{record_id}: missing business_state.{field}")
            if tuple(state.get("prohibited_inferences", ())) != BASE_PROHIBITIONS:
                errors.append(f"{record_id}: prohibited inference rules are incomplete")
        for finding in unsupported_inferences(row):
            errors.append(f"{record_id}: unsupported {finding['concept']} language: {finding['phrase']}")
        errors.extend(f"{record_id}: sender-recipient reversal: {item}" for item in sender_recipient_reversal(row))
        review = row.get("human_review", {})
        for field in ("factual_review", "technical_review", "nigerian_cultural_review", "domain_review", "final_approval"):
            if not isinstance(review.get(field), dict) or not review[field].get("status"):
                errors.append(f"{record_id}: missing human_review.{field}")
    near = _near_duplicates(rows)
    if near:
        warnings.append(f"near-duplicate prompt pairs at threshold 0.90: {len(near)}")
    return {
        "dataset_version": DATASET_VERSION,
        "valid": not errors,
        "record_count": len(rows),
        "category_counts": dict(sorted(counts.items())),
        "duplicate_ids": duplicate_ids,
        "duplicate_prompts": duplicate_prompts,
        "near_duplicate_prompts": near,
        "errors": errors,
        "warnings": warnings,
    }


def statistics(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    rows = list(records)
    labels = Counter(label for row in rows for label in row["failure_taxonomy_labels"])
    return {
        "dataset_version": DATASET_VERSION,
        "record_count": len(rows),
        "category_counts": dict(sorted(Counter(row["category"] for row in rows).items())),
        "risk_level_counts": dict(sorted(Counter(row["risk_level"] for row in rows).items())),
        "review_status_counts": dict(sorted(Counter(row["review_status"] for row in rows).items())),
        "training_eligible_count": sum(bool(row["training_eligible"]) for row in rows),
        "failure_taxonomy_counts": dict(sorted(labels.items())),
    }


def manifest(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    rows = list(records)
    stats = statistics(rows)
    return {
        "schema_version": "1.0",
        "dataset_version": DATASET_VERSION,
        "release_status": "draft_not_training_ready",
        "created_at": CREATED_AT,
        "record_count": len(rows),
        "record_ids_sha256": sha256_value([row["id"] for row in rows]),
        "record_hashes_sha256": sha256_value([row["example_sha256"] for row in rows]),
        "records_sha256": sha256_value(rows),
        "category_counts": stats["category_counts"],
        "source": "synthetic",
        "license": "CC0-1.0",
        "human_approval_required": True,
        "training_release_allowed": False,
    }


def readiness_diagnostics(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    rows = list(records)
    blockers = Counter()
    per_record = []
    for row in rows:
        reasons = []
        if row["review_status"] != "approved":
            reasons.append("not_human_approved")
        if not row["human_review"]["technical_review"]["status"] == "complete":
            reasons.append("technical_review_incomplete")
        if row["human_review"]["final_approval"]["status"] != "approved":
            reasons.append("final_approval_incomplete")
        if not row["training_eligible"]:
            reasons.append("training_eligible_false")
        blockers.update(reasons)
        per_record.append({"record_id": row["id"], "ready": False, "blockers": reasons})
    return {
        "dataset_version": DATASET_VERSION,
        "training_release_allowed": False,
        "ready_count": 0,
        "blocked_count": len(rows),
        "blocker_counts": dict(sorted(blockers.items())),
        "reason": "Draft records require independent human review; release creation is refused.",
        "records": per_record,
    }


def jsonl_text(records: Iterable[dict[str, Any]]) -> str:
    return "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in records)


def write_once_or_verify(path: Path, text: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_text(encoding="utf-8") != text:
            raise FileExistsError(f"Refusing to overwrite differing file: {path}")
        return "verified_existing"
    atomic_create(path, text)
    return "created"


def load_previous_records(paths: Iterable[Path]) -> list[dict[str, Any]]:
    rows = []
    for path in paths:
        if path.is_file():
            rows.extend(read_jsonl(path))
    return rows


def cross_version_prompt_duplicates(
    records: Iterable[dict[str, Any]], previous: Iterable[dict[str, Any]]
) -> list[dict[str, str]]:
    prior = {}
    for row in previous:
        messages = row.get("messages", [])
        if len(messages) >= 2:
            prior.setdefault(normalize_prompt(str(messages[1].get("content", ""))), str(row.get("id", "")))
    matches = []
    for row in records:
        prompt = normalize_prompt(row["messages"][1]["content"])
        if prompt in prior:
            matches.append({"record_id": row["id"], "matched_record_id": prior[prompt]})
    return sorted(matches, key=lambda item: item["record_id"])
