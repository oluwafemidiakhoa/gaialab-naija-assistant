# GaiaLab Naija Trust Engine MVP

The Trust Engine is the first implementation of GaiaLab Naija as a model-agnostic AI evidence and assurance layer.

It does **not** approve governed records, mutate human-review decisions, or publish releases. It evaluates one AI interaction and returns an advisory disposition plus privacy-preserving receipts.

## Initial fintech/customer-support wedge

The first deterministic policy pack targets high-cost failure modes already represented in the GaiaLab roadmap:

- unsupported refund or reversal claims
- unsupported completion timelines
- unsupported account actions or status
- unsupported fees or monetary amounts
- contradictions against authoritative transaction state
- unsupported absolute certainty

## Dispositions

- `ALLOW` — no configured trust finding was detected
- `VERIFY` — evidence should be checked before relying on the response
- `REWRITE` — the response should be rewritten before delivery
- `ESCALATE` — route to an authorized reviewer or support workflow
- `BLOCK` — do not deliver the candidate response as written

These are runtime advisory dispositions, not governance approvals.

## Trust API

Run the API locally:

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
  -H "content-type: application/json" \
  -d '{
    "user_message": "What happened to my transfer?",
    "assistant_response": "Your transfer was successful.",
    "model_name": "provider/model-name",
    "language": "en-NG",
    "authoritative_state": {"transaction_status": "pending"},
    "assistant_claims": {"transaction_status": "completed"}
  }'
```

The API returns the strictest disposition produced by two independent deterministic layers:

1. the text-level Trust Engine policy checks
2. explicit machine-readable claim-to-evidence reconciliation

A contradiction in authoritative state is never softened by a less strict text-level result.

## Claim reconciliation

Clients may supply explicit `assistant_claims` and `authoritative_state` objects. Gaia compares each claim to authoritative state first and caller-supplied evidence second.

Each claim is labeled:

- `SUPPORTED`
- `UNSUPPORTED`
- `CONTRADICTED`

Status aliases such as `successful` and `completed` are normalized. NGN monetary formats such as `NGN 250,000.00`, `₦250,000`, and numeric `250000` are normalized before comparison.

Unsupported high-impact claims such as transaction status, refunds, account status, amounts, fees, or timelines require at least `REWRITE`. Any explicit contradiction requires `BLOCK`.

## Receipts

The response includes:

- the original Trust Receipt from the deterministic text-policy engine
- a reconciliation identifier for structured claim checking
- a verification receipt linking the two results

Receipt identifiers are SHA-256 hashes over canonical verification metadata. They are content-stable for identical verification inputs and results. Raw evidence values are not copied into the original Trust Receipt.

## Synthetic fintech benchmark

A small deliberately synthetic benchmark lives at:

```text
evaluation/fixtures/naija_fintech_trust_v0.1.jsonl
```

Run it with:

```bash
python evaluation/trust_benchmark.py
```

The initial fixture contains eight targeted examples covering transaction-state contradiction, unsupported refund/timeline promises, supported pending state, unsupported fees, NGN amount normalization, and account status.

These fixtures are **synthetic engineering tests**, not a culturally validated dataset release, not training-eligible data, and not evidence of production model quality. Governed benchmark expansion should use separately reviewed and eligible records under the repository's existing governance workflow.

## Current limitations

This remains a deterministic MVP, not a complete factuality or regulatory compliance system.

- Text policies are English-first and need Nigerian English/Pidgin expansion.
- Structured claim reconciliation currently depends on claims supplied by the caller; automatic semantic claim extraction is not included yet.
- Timeline reconciliation currently performs exact normalized matching rather than temporal reasoning over timestamps and SLAs.
- No receipt signing, persistence, API authentication, tenant isolation, rate limiting, or enterprise audit store is included yet.
- No external model provider is required; the engine evaluates candidate outputs from any provider.

## Next build sequence

1. Add deterministic/LLM-assisted claim extraction behind a clearly labeled advisory boundary.
2. Expand the fintech benchmark using governed Nigerian reviewer workflows and hold-out evaluation.
3. Add signed receipt persistence and public verification.
4. Add tenant/API-key boundaries and an append-only audit store.
5. Add a Trust Dashboard showing dispositions, failure classes, model/version comparisons, and receipt lookup.
6. Add provider adapters so OpenAI, Anthropic, Gemini, Qwen, N-ATLAS, and private models can pass through the same verification boundary.
7. Keep automated trust findings separate from existing governed human approval and release workflows.
