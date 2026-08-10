"""Streamlit Trust Dashboard for GaiaLab Naija operator observability.

Run with:
    streamlit run src/trust_dashboard.py

The dashboard is read-only and requires an admin API key with dashboard:read.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from src.trust_dashboard_data import (
    DASHBOARD_VERSION,
    authenticate_dashboard_operator,
    operator_chain_snapshot,
    tenant_snapshot,
)


st.set_page_config(page_title="GaiaLab Naija Trust Dashboard", page_icon="🛡️", layout="wide")
st.title("GaiaLab Naija Trust Dashboard")
st.caption(
    "Read-only runtime assurance. Dashboard views do not approve governed data, mutate policy, "
    "change retention state, or authorize model delivery."
)

with st.sidebar:
    st.header("Operator access")
    admin_key = st.text_input("Admin API key", type="password", placeholder="gaia_admin_...")
    tenant_id = st.text_input("Tenant ID", placeholder="tenant_...")
    limit = st.slider("Rows to inspect", min_value=50, max_value=2000, value=500, step=50)
    st.caption(f"Dashboard contract: {DASHBOARD_VERSION}")

if not admin_key:
    st.info("Enter an admin API key with the dashboard:read scope.")
    st.stop()

try:
    identity = authenticate_dashboard_operator(admin_key)
except Exception as exc:
    st.error(f"Dashboard access denied: {exc}")
    st.stop()

st.success(f"Authenticated operator: {identity.get('operator_name') or identity.get('operator_id')}")

chain = operator_chain_snapshot(action_limit=min(limit, 500))
chain_col1, chain_col2, chain_col3 = st.columns(3)
chain_col1.metric("Operator chain", "VALID" if chain.get("valid") else ("NOT CONFIGURED" if not chain.get("configured") else "INVALID"))
chain_col2.metric("Actions checked", chain.get("count", len(chain.get("actions") or [])))
chain_col3.metric("Chain reason", chain.get("reason", "unknown"))

if not tenant_id:
    st.info("Enter a tenant ID to inspect tenant-scoped Trust Rail evidence.")
    st.stop()

try:
    snapshot = tenant_snapshot(tenant_id, limit=limit)
except Exception as exc:
    st.error(f"Unable to load tenant snapshot: {exc}")
    st.stop()

st.subheader(f"Tenant: {tenant_id}")
metric_cols = st.columns(6)
metric_cols[0].metric("Receipts", snapshot["receipt_count"])
metric_cols[1].metric("Avg risk", snapshot["average_risk_score"])
metric_cols[2].metric("High risk ≥70", snapshot["high_risk_count"])
metric_cols[3].metric("Audit exports", snapshot["audit_export_count"])
metric_cols[4].metric("Legal holds", snapshot["legal_hold_count"])
metric_cols[5].metric("Retention eligible", snapshot["retention_eligible_count"])

left, right = st.columns(2)
with left:
    st.markdown("### Dispositions")
    if snapshot["dispositions"]:
        st.bar_chart(pd.Series(snapshot["dispositions"], name="count"))
    else:
        st.caption("No receipts found.")
with right:
    st.markdown("### Provider activity")
    if snapshot["providers"]:
        st.bar_chart(pd.Series(snapshot["providers"], name="count"))
    else:
        st.caption("No provider activity found.")

left, right = st.columns(2)
with left:
    st.markdown("### Model average risk")
    if snapshot["model_average_risk"]:
        st.bar_chart(pd.Series(snapshot["model_average_risk"], name="average risk"))
    else:
        st.caption("No model risk data found.")
with right:
    st.markdown("### Languages")
    if snapshot["languages"]:
        st.bar_chart(pd.Series(snapshot["languages"], name="count"))
    else:
        st.caption("No language metadata found.")

st.markdown("### Finding codes")
if snapshot["finding_codes"]:
    finding_df = pd.DataFrame(
        [{"finding_code": key, "count": value} for key, value in snapshot["finding_codes"].items()]
    ).sort_values("count", ascending=False)
    st.dataframe(finding_df, use_container_width=True, hide_index=True)
else:
    st.caption("No findings in the selected receipt window.")

st.markdown("### Receipt search")
receipts = snapshot["receipts"]
if receipts:
    receipt_df = pd.DataFrame(receipts)
    search = st.text_input("Filter verification ID or model", placeholder="verification ID or model name")
    disposition_filter = st.multiselect(
        "Disposition",
        sorted(receipt_df["disposition"].dropna().unique().tolist()),
    )
    filtered = receipt_df
    if search:
        needle = search.lower()
        filtered = filtered[
            filtered["verification_id"].astype(str).str.lower().str.contains(needle)
            | filtered["model_name"].astype(str).str.lower().str.contains(needle)
        ]
    if disposition_filter:
        filtered = filtered[filtered["disposition"].isin(disposition_filter)]
    visible_columns = [
        "created_at", "verification_id", "model_name", "model_version", "language",
        "disposition", "risk_score", "signed", "tenant_policy_id", "finding_codes",
    ]
    st.dataframe(filtered[visible_columns], use_container_width=True, hide_index=True)
else:
    st.caption("No receipts found for this tenant.")

st.markdown("### Audit export retention")
exports = snapshot["audit_exports"]
if exports:
    export_df = pd.DataFrame(exports)
    st.dataframe(
        export_df[
            [
                "created_at", "package_id", "retention_until", "legal_hold_active",
                "retention_expired", "eligible_for_deletion", "manifest_sha256",
            ]
        ],
        use_container_width=True,
        hide_index=True,
    )
else:
    st.caption("No audit exports found for this tenant.")

st.markdown("### Recent operator actions")
actions = chain.get("actions") or []
if actions:
    action_df = pd.DataFrame(actions)
    st.dataframe(
        action_df[
            ["created_at", "operator_id", "action_type", "target_type", "target_id_sha256", "action_hash"]
        ],
        use_container_width=True,
        hide_index=True,
    )
else:
    st.caption("No operator actions available.")

st.caption(
    "Trust Dashboard is observability only. Destructive retention still requires the separate signed-plan, "
    "two-operator approval, and execution workflow."
)
