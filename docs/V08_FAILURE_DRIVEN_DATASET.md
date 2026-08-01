# v0.8 failure-driven dataset

GaiaLab v0.8 is a governed draft expansion informed by the first reported
evaluation of the `v0.7.0-rc.3` adapter. It is not a release, is not approved,
and must not be used for training yet.

## Why failure-driven

The supplied evaluation classifications contain four passes, four failures,
and two borderline results. Reported problems include invented processing
times, payment-state reversal, unsupported refunds or consequences,
sender/recipient reversal, unstable duplicate-charge roles, and an unclear
meeting decline. The expansion targets these error modes instead of adding
unrelated volume.

The exact ten prompts, generated responses, numerical scores, evaluator ID,
and evaluation timestamp were not present in repository evidence or the task
source. `evaluation/v0.7.0-rc.3/first_adapter_evaluation.jsonl` therefore keeps
those values null and records only the supplied classifications and findings.
This is deliberate: summaries are not represented as verbatim transcripts.
Replace nulls only from preserved evaluation evidence and through review; do
not reconstruct model outputs from memory.

## Draft composition

The deterministic builder produces 120 new examples, 15 in each category:

- unpaid invoice reminders;
- payment-received confirmations;
- payment promised but not received;
- invoice-receipt confirmation requests;
- duplicate-charge refund requests;
- supplier and delivery follow-ups;
- Nigerian English business writing; and
- safety refusals with helpful redirection.

Every ID starts with `v08`, every record is `v0.8-draft`, and every record has
`review_status=draft` and `training_eligible=false`. Source and source
classification are `synthetic`; the license is `CC0-1.0`. Records include an
immutable creation timestamp, revision, canonical example SHA-256, and pending
human-review fields.

## Failure taxonomy

The machine-readable taxonomy is `data/v0.8/failure_taxonomy.json`. It defines:

- `state_reversal`
- `sender_recipient_role_reversal`
- `unsupported_penalty`
- `unsupported_refund`
- `unsupported_timeline`
- `unsupported_account_action`
- `incomplete_intent`
- `excessive_template_language`
- `weak_nigerian_context`
- `unsafe_compliance`
- `unclear_business_state`
- `verbosity_mismatch`

Each draft has one or more labels describing the evaluated weakness it is
intended to correct. Labels are design metadata, not evidence that the draft
has passed review.

## Role and state metadata

Each record contains `business_state` with:

- `sender_role`
- `recipient_role`
- `current_state`
- `requested_action`
- `prohibited_inferences`
- `expected_tone`
- `allowed_concepts`

Paired contrast groups distinguish states such as invoice sent versus payment
received, payment promised versus completed, refund requested versus approved,
supplier delayed versus delivered, and meeting declined versus rescheduled.
The validator checks category-specific roles and states for the transaction
categories.

## Prohibited inference rules

Every record says not to:

- claim payment was received unless stated;
- introduce refunds unless requested;
- introduce penalties unless provided;
- invent dates, amounts, timelines, fees, legal claims, or account actions;
- reverse who sent or received an invoice;
- claim a delayed delivery occurred; or
- claim an order was cancelled unless stated.

The quality check flags `penalty`, `penalties`, `consequences`, `refund`,
`credited to your account`, `successfully processed`, `legal action`, `late
fee`, and `interest` in an assistant response unless the concept is explicit
in prompt metadata. A refund request may acknowledge the request, but must not
say it was approved, processed, or credited.

## Build and validation

Run the complete pipeline:

```bash
python scripts/pipeline_v08.py
```

Or run its fail-fast steps individually:

```bash
python scripts/analyze_evaluation_failures.py
python scripts/build_v08_failure_dataset.py
python scripts/validate_v08_failure_dataset.py
```

Generated outputs are under `data/v0.8/generated/`. The writer creates a
missing output, verifies an identical existing output, and refuses to replace
a differing file. The pipeline calculates category/risk/taxonomy statistics,
validates hashes and metadata, detects exact and near prompt duplicates, checks
against the governed v0.6 release, writes a manifest and readiness diagnostics,
and refuses to create a training release.

## Human review

Each draft requires factual, technical, Nigerian cultural, and final approval.
High-risk safety records also require domain review. Automated findings and AI
recommendations are advisory and cannot change these states.

After reviewing the generated validation report, create the immutable registry
snapshot:

```bash
python scripts/dataset_platform.py import --version v0.8-draft \
  --input data/v0.8/generated/v0.8_draft.jsonl
```

Import creates a write-once registry snapshot; it does not approve any record.
The exact next human-review queue command is:

```bash
python scripts/review_automation.py build-queue --version v0.8-draft \
  --review-status draft --training-eligible no
```

Use the existing review interface or preview-first human-review commands after
import. Do not bulk-approve high-risk or domain-review records. Technical
review and final approval remain separate actions.

## Limitations and retraining block

- Exact source transcripts for the ten evaluation cases remain unavailable.
- All 120 examples are synthetic drafts pending independent Nigerian review.
- Nigerian English is not culturally uniform; reviewers from relevant regions
  and business contexts should assess tone and clarity.
- Template coverage does not demonstrate real-world model improvement.
- No training, evaluation metric, or production-quality claim follows from
  building this dataset.

Retraining is blocked because all records are drafts, all have
`training_eligible=false`, and none has complete human approval evidence. A
future release builder must evaluate append-only human audit events and may
select only records that independently satisfy the existing governance rules.
