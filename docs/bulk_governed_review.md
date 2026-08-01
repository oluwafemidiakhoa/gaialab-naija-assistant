# Bulk governed human review

Bulk governed review is a local, preview-first convenience for a qualified
human who has personally reviewed a carefully filtered set of low-risk,
synthetic records. It does not delegate judgment to the advisory analyzer and
does not create an automatic approval path.

The workflow uses the same append-only registry transitions, reviewer-role
checks, immutable record hashes, and separate human audit stream as individual
review. Technical review and approval are always separate operations.

## Authentication boundary

The platform is local-first. Operating-system access to the review workstation
is the authentication boundary. A real bulk write additionally requires
`GAIALAB_AUTHENTICATED_REVIEWER_ID` to match `--reviewer-id`. Do not share a
workstation session or set this variable for another reviewer.

PowerShell:

```powershell
$env:GAIALAB_AUTHENTICATED_REVIEWER_ID = "olu-technical-001"
```

Bash:

```bash
export GAIALAB_AUTHENTICATED_REVIEWER_ID="olu-technical-001"
```

The reviewer role is still checked independently against every requested state
transition. Reviewer identifiers and notes remain private governance metadata
and are not exposed by public verification certificates.

## Prepare the decision note

The reviewer must create the note after inspecting the selected records. The
platform deliberately does not generate or prefill a statement claiming that
review occurred.

```text
review_notes/business_writing_pilot.txt
```

The note must be non-empty. The complete note is copied into every per-record
human audit event.

## Preview

Dry-run is the default. Supplying `--dry-run` makes the intent explicit:

```bash
python scripts/review_automation.py bulk-human-review \
  --version v0.6 \
  --category business_writing \
  --reviewer-id olu-technical-001 \
  --reviewer-role technical_reviewer \
  --action technical-review \
  --note-file review_notes/business_writing_pilot.txt \
  --limit 20 \
  --dry-run
```

The preview is printed before any possible write and includes:

- selected record IDs, categories, risks, current statuses, and content hashes;
- advisory recommendations and recommendation hashes;
- quality scores and all unresolved findings;
- technical- and domain-review requirements;
- current training-eligibility blockers;
- allowed and blocked records; and
- exact blocking reasons for every blocked record.

Selection is deterministic: records matching the exact category are ordered by
record ID and then limited. A repeated preview over unchanged state has the same
preview hash and batch operation ID.

## Current quality-assessment linkage

Standalone quality scoring stores assessments under
`evaluation/quality/<version>/`, while `review_automation.py refresh` stores its
recalculated assessments under `evaluation/review_refresh/<version>/`. Bulk
review considers both write-once stores and selects the run with the newest
`assessed_at` timestamp. A custom refresh location can be supplied with
`--refresh-root` or `GAIALAB_REVIEW_REFRESH` in the Streamlit panel.

Location alone never makes an assessment valid. Technical review and approval
still require the selected assessment's `record_id` and `record_sha256` to
match the current immutable record. Missing or stale evidence produces
`current_quality_assessment_missing`; unresolved duplicate, safety,
provenance, licensing, and other governed findings remain independently
blocking.

Refresh reporting also replays `human_events.jsonl` in timestamp order, using
append order when timestamps are equal. Each event must have a valid event
hash, dataset version, record SHA-256, revision, transition chain, and reviewer
role. The latest valid `new_status` becomes the reported status; replay never
modifies the immutable snapshot or appends a human decision.

## Execute

Inspect the complete preview first. A real write requires both `--write` and the
exact confirmation phrase:

```bash
python scripts/review_automation.py bulk-human-review \
  --version v0.6 \
  --category business_writing \
  --reviewer-id olu-technical-001 \
  --reviewer-role technical_reviewer \
  --action technical-review \
  --note-file review_notes/business_writing_pilot.txt \
  --limit 20 \
  --write \
  --confirm "I HAVE REVIEWED THESE RECORDS"
```

Before the first append, execution regenerates the preview and rejects stale
record content, status, recommendation, finding, or blocker state. Blocked
records are never written. Every allowed record receives its own registry
transition and immutable human audit event.

Supported CLI actions are:

- `acknowledge-analysis`
- `technical-review`
- `request-revision`
- `reject`
- `escalate`
- `approve`

Escalation additionally requires `--escalation-target` with `technical`,
`domain`, `safety`, or `provenance`.

## Approval safeguards

Bulk approval is blocked unless every allowed record:

- is synthetic and low risk;
- is already technically reviewed;
- does not belong to a domain-review category;
- has a current, stored, audited recommendation;
- has no unresolved critical, high, safety, provenance, licensing, or duplicate
  blocker;
- has an allowed licence and matching immutable content hash;
- passes the configured minimum quality threshold; and
- is approved by an authorized human using the exact batch confirmation.

An `approve_candidate` recommendation never satisfies a human gate. Running
`technical-review` changes only the technical-review state. A separate preview,
confirmation, and `approve` operation are required afterward.

## Audit evidence

Every successful record action has a distinct event containing the reviewer ID,
role, action, decision note, previous and new statuses, record revision, record
SHA-256, related recommendation hash, timestamp, event SHA-256, and common batch
operation ID. Events are appended to:

```text
evaluation/review_audit/<version>/human_events.jsonl
```

Original imported snapshots and released files are not modified. This command
does not upload, publish, train, commit, push, or tag.

## Streamlit

Run:

```bash
python -m streamlit run app/Home.py
```

Open **Bulk Governed Review**, enter the same filter, reviewer identity, role,
action, note, and limit, then select **Preview governed batch**. Write mode
remains disabled until the authenticated reviewer ID matches, the exact
confirmation phrase is entered, and at least one record is allowed.
