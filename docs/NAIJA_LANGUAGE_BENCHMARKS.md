# Nigerian English and Pidgin trust benchmarks

GaiaLab Naija includes a small synthetic regression suite for consequential fintech claims expressed in Nigerian English and Nigerian Pidgin.

## Governance status

The fixtures in:

- `evaluation/fixtures/naija_pidgin_claim_extraction_v0.1.jsonl`
- `evaluation/fixtures/naija_pidgin_trust_v0.1.jsonl`

are **synthetic drafts**. They are **not culturally validated**, are **not a governed dataset release**, and are **not training eligible**.

They exist only to stop deterministic Trust Rail extraction logic from silently regressing on a narrow set of known phrases.

Promotion into governed evaluation or training data requires the repository's normal Nigerian human-review and dataset-governance process. Automated benchmark success must never be interpreted as cultural approval.

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
python -m pytest -q tests/test_naija_claim_extraction.py tests/test_naija_pidgin_trust.py
```

GitHub Actions also runs these checks in the `Naija Language Benchmarks` workflow when extraction code, fixtures, or focused tests change.
