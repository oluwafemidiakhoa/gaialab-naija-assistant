# GaiaLab Naija Trust Dashboard

The Trust Dashboard is a read-only operator observability surface for the GaiaLab Naija Trust Rail. It summarizes persisted verification receipts, audit-export retention state, and tamper-evident operator-action-chain health without changing runtime policy or governed state.

## Governance boundary

The dashboard does **not**:

- approve or reject governed datasets
- change training eligibility or publication state
- activate tenant policies or signing keys
- place or release legal holds
- execute destructive retention
- authorize a model response for delivery
- modify verification receipts or audit packages

A dashboard view is operational evidence, not a human governance decision.

## Access control

Dashboard access uses a separate operator/admin key with the explicit `dashboard:read` scope. The default admin scope remains `audit:lifecycle`; dashboard access is therefore opt-in.

For local SQLite development:

```bash
python scripts/manage_trust_identity.py create-operator \
  --db "$GAIALAB_OPERATOR_DB" \
  --name "Trust Dashboard Operator"

python scripts/manage_trust_identity.py issue-admin-key \
  --db "$GAIALAB_OPERATOR_DB" \
  --operator-id OPERATOR_ID \
  --label dashboard \
  --scope dashboard:read
```

For Neon provisioning, use the migration/owner credential in the normal provisioning context:

```bash
python scripts/manage_neon_trust.py \
  --actor-id OPERATOR_ID \
  issue-admin-key \
  --operator-id OPERATOR_ID \
  --label dashboard \
  --scope dashboard:read
```

The plaintext admin key is returned only at issuance and must be handled as a secret.

## Run the dashboard

Configure the same read-side Trust Rail storage used by the deployment. For SQLite this normally includes:

```bash
export GAIALAB_OPERATOR_DB="data/trust_operators.sqlite3"
export GAIALAB_TRUST_RECEIPT_DB="data/trust_receipts.sqlite3"
export GAIALAB_AUDIT_LIFECYCLE_DB="data/trust_audit_lifecycle.sqlite3"
export GAIALAB_OPERATOR_ACTION_DB="data/trust_operator_actions.sqlite3"
```

For Neon, configure the tenant and operator runtime URLs through the existing deployment mechanism. The dashboard reads cross-tenant operational evidence only through the operator database identity.

Start the UI:

```bash
streamlit run src/trust_dashboard.py
```

Enter the `gaia_admin_...` key and a tenant ID in the sidebar.

## What the dashboard shows

For the selected tenant, the dashboard reports:

- persisted verification receipt count
- average and high-risk receipt counts
- disposition distribution (`ALLOW`, `VERIFY`, `REWRITE`, `ESCALATE`, `BLOCK`)
- model activity and average risk by model
- provider-family activity inferred from persisted `model_name`
- language metadata distribution
- finding-code frequency
- searchable receipt metadata
- audit-export retention deadlines
- current legal-hold state
- whether an expired export is retention-eligible
- operator action-chain validity and recent hashed-target actions

## Provider analytics boundary

Provider-family analytics are derived from the `model_name` already bound into signed/persisted verification receipts. For example, a model name such as `openai/gpt-*` is grouped under OpenAI.

This is **not** direct provider telemetry. The dashboard does not query vendor billing, token usage, latency, API logs, provider credentials, or raw generation payloads. Unknown naming conventions fall into the `custom` provider bucket.

## Receipt privacy and isolation

Receipt queries always require a tenant ID and return only that tenant's persisted records. The dashboard displays receipt metadata needed for assurance analysis; it does not expose API keys or provider credentials.

Raw assistant response text is not required for the current dashboard analytics because the verification receipt already contains disposition, risk, model identity, language, policy binding, and finding codes.

## Retention visibility

Retention status is reconstructed read-only from the audit export and its ordered lifecycle events. An expired export under an active legal hold remains **ineligible for deletion**.

The dashboard cannot create, approve, cancel, or execute a deletion plan. Destructive retention remains governed by the separate signed eligibility snapshot, two-distinct-operator approval, and execution-time recheck flow described in `docs/RETENTION_DELETION.md`.

## Operator-chain health

The dashboard calls the existing operator-action-chain verifier and shows the resulting integrity state. This detects modified actions, broken previous-hash links, and deleted-tail/stored-head mismatch within the database trust boundary.

The chain remains tamper-evident rather than independently non-repudiable. A sufficiently privileged database owner who can rewrite both rows and the stored head remains a higher-trust boundary. Externally signed checkpoints are the next planned hardening layer.

## Tests

Focused contracts are in `tests/test_trust_dashboard.py` and verify:

- `dashboard:read` is required explicitly
- a lifecycle-only admin key cannot open the dashboard
- tenant receipt isolation
- risk/provider/disposition aggregation
- legal-hold state overrides retention expiry for deletion eligibility

The focused GitHub Actions workflow is `.github/workflows/trust-dashboard-ci.yml`.
