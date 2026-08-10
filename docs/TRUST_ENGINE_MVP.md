# GaiaLab Naija Trust Rail MVP

The Trust Rail is a model-agnostic AI evidence and assurance layer for consequential Nigerian AI interactions.

It does **not** approve governed records, mutate human-review decisions, or publish releases. It evaluates candidate AI output, extracts a narrow set of consequential claims, reconciles them against explicit authoritative state, and returns an advisory disposition plus verifiable receipts.

## Initial fintech/customer-support wedge

The first deterministic policy pack targets:

- unsupported refund or reversal claims
- unsupported completion timelines
- unsupported account actions or status
- unsupported fees or monetary amounts
- contradictions against authoritative transaction state
- unsupported absolute certainty
- conflicting machine-extracted transaction/account claims

## Dispositions

- `ALLOW` — no configured trust finding was detected
- `VERIFY` — evidence should be checked before relying on the response
- `REWRITE` — the response should be rewritten before delivery
- `ESCALATE` — route to an authorized reviewer or support workflow
- `BLOCK` — do not deliver the candidate response as written

These are runtime advisory dispositions, not governance approvals.

## Run the API

```bash
uvicorn src.trust_api:app --reload
```

Health check:

```bash
curl http://127.0.0.1:8000/health
```

Verify a candidate response:

```bash
curl -X POST http://127.0.0.1:8000/v1/verify \
  -H "Content-Type: application/json" \
  -d '{
    "user_message": "What happened to my transfer?",
    "assistant_response": "Your transfer was successful.",
    "authoritative_state": {"transaction_status": "pending"},
    "model_name": "provider/model-name"
  }'
```

`assistant_claims` is optional. When omitted, the service runs deterministic typed extraction for supported high-impact claim classes. Caller-supplied structured claims remain supported for integrations that already produce them.

## Automatic typed claim extraction

`src/claim_extraction.py` extracts a deliberately narrow and auditable claim set from candidate responses, including:

- transaction status
- refund/reversal status
- account status
- NGN fee/amount claims
- refund ETA expressed in hours/days
- simple consequential ETA tokens such as `today`/`tomorrow`

The extractor records matched text and confidence, flags conflicting claims, handles common negation cases, and is **advisory only**. It is not evidence and cannot approve a response.

## Structured reconciliation

`src/claim_reconciliation.py` compares extracted or caller-supplied claims to `authoritative_state` and optional `evidence`.

Outcomes are:

- `SUPPORTED`
- `UNSUPPORTED`
- `CONTRADICTED`

A contradicted high-impact claim drives a `BLOCK`; unsupported high-impact structured claims require at least a rewrite/verification action according to the policy pack.

## Signed Trust Receipts

The API can sign each `verification_receipt` using Ed25519. The private signing key is never stored in the repository.

Generate a keypair:

```bash
python scripts/generate_trust_signing_key.py
```

Set the raw private key returned by the script as a secret:

```bash
export GAIALAB_TRUST_SIGNING_KEY_B64="..."
```

When signing is configured, `/v1/verify` returns a `receipt_envelope` containing:

- the deterministic `verification_receipt`
- Ed25519 signature
- public verification key
- `key_id`
- signature algorithm/version

Verify any envelope without the private key:

```text
POST /v1/receipts/verify
```

The verifier rejects tampered receipts, mismatched key IDs, malformed keys, and invalid signatures.

## Append-only receipt persistence

Optional local persistence uses SQLite and write-once semantics.

```bash
export GAIALAB_TRUST_RECEIPT_DB="data/trust_receipts.sqlite3"
```

For an existing `verification_id`:

- identical content is treated as idempotent
- different content raises a conflict instead of overwriting history

Endpoints:

```text
GET /v1/receipts/{verification_id}
GET /v1/receipts/{verification_id}/verify
```

This is the first local persistence implementation. Enterprise deployments should move the same append-only contract to a managed transactional store with tenant isolation, access control, retention policy, and audit export.

## Privacy boundary

The existing Trust Receipt does not embed raw authoritative-state or evidence values. The signed verification receipt links deterministic IDs for the text-policy result, claim extraction, and reconciliation result.

Public verification must not become a mechanism for leaking private customer, transaction, or account data.

## Synthetic fintech benchmark

The repository contains an initial synthetic engineering benchmark for trust-policy behavior. It is useful for regression coverage but is **not** culturally validated data, not training-eligible data, and not evidence of production model quality.

## Current limitations

- deterministic extraction is deliberately narrow and English-first
- Nigerian English/Pidgin claim extraction needs governed expansion
- free-form semantic claims outside the configured types are not automatically reconciled
- timelines such as calendar dates and complex SLAs need richer typed normalization
- signing proves receipt integrity/authenticity for the configured key; it does not prove that upstream authoritative data was truthful
- SQLite is a local MVP store, not an enterprise multi-tenant audit backend
- API authentication, rate limiting, tenant boundaries, key rotation registry, and authorization are not included yet

## Next build sequence

1. Add key rotation and a public signing-key registry so historical receipts remain verifiable.
2. Add tenant/API-key boundaries and append-only enterprise audit storage.
3. Expand deterministic Nigerian English/Pidgin extraction with governed reviewer benchmarks.
4. Add provider adapters for OpenAI, Anthropic, Gemini, Qwen, N-ATLAS, and private models.
5. Add a Trust Dashboard for receipt lookup, model comparison, failure classes, and audit exports.
6. Add optional model-assisted claim extraction behind the deterministic boundary, evaluated against held-out governed benchmarks before use.
7. Preserve the separation between automated trust findings and governed human approval/release workflows.
