# Nigerian English and Pidgin trust benchmarks

GaiaLab Naija includes a small synthetic regression suite for consequential fintech claims expressed in Nigerian English and Nigerian Pidgin.

## Governance status

The fixtures in:

- `evaluation/fixtures/naija_pidgin_claim_extraction_v0.1.jsonl`
- `evaluation/fixtures/naija_pidgin_trust_v0.1.jsonl`

are **synthetic drafts**. They are **not culturally validated**, are **not a governed dataset release**, and are **not training eligible**.

They exist only to stop deterministic Trust Rail extraction logic from silently regressing on a narrow set of known phrases.

Automated benchmark success must never be interpreted as cultural approval.

## Governed review staging

Synthetic trust fixtures may be copied into the normal dataset-review system only as draft candidates:

```bash
python scripts/stage_naija_language_review.py \
  --output /tmp/naija-language-review.jsonl
python scripts/dataset_platform.py import \
  --version naija-language-review-v0.1 \
  --input /tmp/naija-language-review.jsonl
```

The staging command is deliberately one-way and conservative:

- every staged record remains `draft`
- every staged record remains `culturally_validated: false`
- the source is marked with the `gaialab-naija-language-review:` provenance prefix
- no review, approval, publication, or training-eligibility state is granted
- the output file is write-once and is refused if it already exists

Staging is not promotion. It only creates records that Nigerian human reviewers can inspect through the repository's append-only review workflow.

## Cultural-validation gate

Records staged through the Nigerian-language review path require an explicit cultural-validation event before they can become training eligible.

Cultural validation:

- may be recorded only by a `domain_reviewer` or `release_manager`
- records reviewer identity, timestamp, notes, revision, and exact record SHA-256
- is append-only in the same review ledger as the standard review workflow
- is separate from technical, domain, and release approval
- does not by itself approve a record
- becomes stale automatically when the content changes because eligibility requires the validation event to match the current record hash

A new revision resets cultural-validation metadata to pending, even when the parent revision had already been culturally validated.

Training eligibility for Nigerian-language review records therefore requires all ordinary gates plus a current affirmative cultural-validation decision. An otherwise approved Nigerian Pidgin or Nigerian English record is excluded with `cultural_validation_incomplete` until that gate is satisfied.

## Covered claim families

The current narrow suite covers examples of:

- transaction pending/completed/failed/reversed states
- refund pending/completed state
- account restriction and unblock state
- naira fee and transfer-amount statements using `N` notation
- refund timelines in hours
- negated completion followed by an affirmative pending state
- mutually conflicting transaction-state claims

This is not intended to represent all Nigerian Pidgin syntax, regional variation, code-switching, spelling, or banking terminology.

## Safety behavior

Claim extraction remains advisory. An extracted phrase becomes consequential only after reconciliation against caller-supplied authoritative state or evidence.

The benchmark therefore checks two separate properties:

1. **Extraction exact match** — does the deterministic parser produce the expected narrow claim or conflict?
2. **Trust behavior** — when no caller-supplied `assistant_claims` are provided, does the Trust API extract the claim and reconcile it correctly against authoritative state?

Contradicted consequential claims must block. Unsupported high-impact claims must require rewrite. Conflicting extracted states require rewrite rather than selecting one state arbitrarily.

## Negation rule

Extraction v0.2.0 binds negation to the status token rather than treating any negation anywhere in the full matched phrase as negating the claim.

For example, a synthetic phrase equivalent to "the transfer did not complete; it is still pending" must retain the affirmative `pending` claim while suppressing the negated completion claim.

## Running locally

```bash
python evaluation/claim_extraction_benchmark.py
python -m pytest -q \
  tests/test_naija_claim_extraction.py \
  tests/test_naija_pidgin_trust.py \
  tests/test_language_governance.py \
  tests/test_review_workflow.py \
  tests/test_training_eligibility.py
```

GitHub Actions runs these checks in the `Naija Language Benchmarks` workflow when extraction, governance, fixtures, focused tests, or the staging command change.
