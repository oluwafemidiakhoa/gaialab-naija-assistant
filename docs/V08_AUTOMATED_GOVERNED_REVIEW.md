# v0.8 automated governed review

`scripts/run_governed_v08_review.py` coordinates the repetitive parts of the
`v0.8-draft` review workflow. It does not replace a reviewer. Write mode records
explicit decisions made by the named humans; it never invents decisions from an
AI recommendation.

The default category order is payment receipt confirmation, invoice receipt
confirmation requests, duplicate-charge refund requests, unpaid-invoice
reminders, supplier-delivery follow-ups, Nigerian English business writing,
and safety refusal/redirection. Nigerian English is not culturally uniform;
the output remains subject to review by relevant Nigerian speakers and
small-business owners.

## Safe preview

Run the complete plan first:

```powershell
.\.venv311\Scripts\python.exe scripts\run_governed_v08_review.py `
  --version v0.8-draft `
  --all-remaining-categories `
  --limit-per-category 20 `
  --dry-run
```

Dry-run performs deterministic offline analysis and governed previews. It may
create automated recommendation evidence, append-only note files, and summary
reports, but it writes no human decision event and changes no official review
status. Each stage reports the exact allowed IDs and the blocking reasons for
every blocked ID.

To stop after technical review in either preview or write mode, add:

```powershell
  --stop-before-approval
```

## Explicit write

Only run write mode after each named reviewer has personally reviewed the
records selected for their stage:

```powershell
.\.venv311\Scripts\python.exe scripts\run_governed_v08_review.py `
  --version v0.8-draft `
  --all-remaining-categories `
  --limit-per-category 20 `
  --reviewer-id olu-reviewer-001 `
  --technical-reviewer-id olu-technical-001 `
  --release-manager-id olu-release-001 `
  --write `
  --confirm "I HAVE REVIEWED THESE RECORDS"
```

The orchestrator sets `GAIALAB_AUTHENTICATED_REVIEWER_ID` only in the child
process for the active stage. The child still performs the existing identity,
role, transition, record-hash, recommendation-audit, quality, provenance,
licensing, duplicate, safety, risk, and domain-review checks. Technical review
and approval are separate audit events with separate reviewer identities.

Write mode fails closed when the confirmation phrase is absent, when the audit
ledger changes between preview and execution, or when the subprocess preview
hash differs from the orchestrator preview hash. It writes only allowed
records and refreshes governed reports after every successful stage. Completed
categories and completed transitions are skipped, so rerunning does not create
duplicate human events.

## Append-only evidence and reports

One note per category and stage is created under `review_notes/v0.8/`. Notes
contain the reviewer identity, timestamp, acceptance and blocking criteria,
and selected, allowed, and blocked counts. Existing notes and reports are never
overwritten; a numbered sibling is created on rerun.

The default JSON and Markdown summaries are written under
`evaluation/review_orchestration/v0.8-draft/`. They include per-category stage
counts, allowed and blocked IDs, duplicate/critical/stale-assessment blockers,
final official status counts, current training eligibility, human audit counts,
failures, and planned/executed commands.

The command performs no training, release creation, publication, upload,
commit, push, or tag operation. A record can become training-eligible only
after the existing governance service validates a separate explicit approval.

## Verification

Run the repository suite before relying on the workflow:

```powershell
.\.venv311\Scripts\python.exe -m pytest -q
```

Then compare the human ledger hash and event count before and after dry-run.
The summary fields `human_events_before`, `human_events_after`, and
`human_audit_unchanged` provide the corresponding run evidence.
