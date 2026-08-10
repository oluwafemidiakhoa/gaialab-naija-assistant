# GaiaLab Naija Trust Engine MVP

The Trust Engine is the first implementation of GaiaLab Naija as a model-agnostic AI evidence and assurance layer.

It does **not** approve governed records, mutate human-review decisions, or publish releases. It evaluates one AI interaction and returns an advisory disposition plus a privacy-preserving Trust Receipt.

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

## JSON contract

Input:

```json
{
  "user_message": "My transfer did not arrive. When will I get it back?",
  "assistant_response": "Your refund will be returned to your account within 24 hours.",
  "model_name": "provider/model-name",
  "model_version": "optional-version",
  "language": "en-NG",
  "business_state": {},
  "evidence": {}
}
```

Run locally:

```bash
python scripts/verify_interaction.py interaction.json
```

The result contains:

- disposition
- deterministic risk score
- structured findings
- safe rewrite suggestion for higher-risk outcomes
- Trust Receipt with content hashes, policy version, evidence-key names, model metadata, finding codes, and disposition

The receipt intentionally does not embed evidence values or business-state values. Its identifier is content-stable for the same verification inputs and policy result, while `created_at` records when a particular evaluation was executed.

## Current limitations

This is intentionally a small deterministic MVP, not a complete factuality system.

- Regex policies are English-first and need Nigerian English/Pidgin expansion.
- Presence of evidence is not yet equivalent to proving that the evidence semantically supports every claim.
- Amount matching does not yet reconcile exact ledger values against response values.
- Timeline matching does not yet compare the promised time to an authoritative timestamp/SLA.
- No external model provider is required; the engine evaluates candidate outputs from any provider.
- No receipt persistence, signing, API authentication, tenant isolation, or enterprise audit store is included yet.

## Next build sequence

1. Add typed claim extraction and exact evidence-to-claim reconciliation.
2. Add Nigerian fintech policy fixtures and failure benchmarks derived from governed, eligible records only.
3. Expose `POST /v1/verify` behind a small API service.
4. Add signed receipt persistence and verification.
5. Add a Streamlit Trust Dashboard showing dispositions, failure classes, model/version comparisons, and receipt lookup.
6. Add provider adapters so OpenAI, Anthropic, Gemini, Qwen, N-ATLAS, and private models can all pass through the same verification boundary.
7. Keep automated trust findings separate from existing governed human approval and release workflows.
