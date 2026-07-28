# AI-assisted dataset review

The GaiaLab review automation workflow prepares and prioritizes dataset work
while preserving the existing human-governed registry. It is local-first,
CPU-compatible, deterministic where practical, and usable without an API key.

AI output is advisory. It cannot approve, reject, publish, release, or make a
record training-eligible.

## Governance boundaries

The automation may:

- calculate deterministic quality and duplicate signals;
- build prioritized review queues;
- identify safety, factuality, ambiguity, language, and Nigerian-context issues;
- propose a non-mutating revision;
- recommend one of the five candidate or escalation categories;
- generate write-once reports and audit events; and
- recalculate downstream quality, progress, eligibility, and scorecard reports.

Only an identified human reviewer may:

- acknowledge an automated analysis;
- complete technical or domain review;
- approve, request revision, reject, or escalate;
- accept, edit, or discard a suggested revision; and
- initiate a release or publication through the separate release workflow.

The allowed AI recommendations are:

- `approve_candidate`
- `revise_candidate`
- `reject_candidate`
- `escalate_for_domain_review`
- `escalate_for_safety_review`

These values are not official review statuses. Approval requires the existing
technical-review gate, domain review for banking, healthcare, and government
services, an authorized reviewer role, and a separate confirmation checkbox.
Rejection, escalation, and revision actions require a human decision note.

Escalation is stored as the human audit action `escalate` while the official
status becomes `needs_revision`. This preserves the existing status schema.

## Architecture

```text
immutable registry record
  -> deterministic quality and risk checks
  -> local duplicate analysis
  -> optional provider analysis with validated JSON
  -> non-mutating suggested revision
  -> candidate recommendation
  -> immutable automated audit event
  -> explicit human action
  -> existing append-only review transition or child revision
  -> separate immutable human audit event
  -> write-once quality, eligibility, progress, and scorecard refresh
```

The implementation is divided into:

- `models.py`: validated advisory, suggestion, duplicate, and audit schemas;
- `config.py`: validated thresholds, provider policy, and queue ordering;
- `duplicates.py`: CPU-only exact, normalized, field, pair, and near matches;
- `queue.py`: deterministic filtering, prioritization, grouping, and pagination;
- `providers.py`: mock and caller-supplied structured provider contracts;
- `analyzer.py`: deterministic analysis and safe provider fallback;
- `audit.py`: separate append-only automated and human audit logs;
- `revisions.py`: explicit human decisions and child-revision actions;
- `refresh.py`: downstream report recalculation without release publication; and
- `service.py`: loading, bulk analysis, write-once reports, and daily packs.

The versioned review prompt is
`evaluation/review_prompts/gaialab-review-v1.txt`. Prompts are not embedded in
Streamlit pages.

## Installation and offline use

Use Python 3.11 and install the repository dependencies:

```bash
python -m venv .venv311
```

Windows PowerShell:

```powershell
.\.venv311\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Linux or macOS:

```bash
source .venv311/bin/activate
python -m pip install -r requirements.txt
```

No additional dependency or API key is required. The default `local` provider
uses deterministic repository checks only.

## Configuration

Defaults live in `config/review_automation.yaml`. The file controls:

- risk weights;
- minimum, approval-candidate, rejection-candidate, and confidence thresholds;
- near-duplicate similarity;
- domain and enhanced-safety categories;
- provider timeout and retries;
- external-provider opt-in; and
- the governed deterministic queue order.

Use another configuration file by placing the global option before the
subcommand:

```bash
python scripts/review_automation.py \
  --config config/review_automation.yaml \
  analyze --version v0.6
```

Supported non-secret environment overrides are:

```text
GAIALAB_REVIEW_CONFIG
GAIALAB_REVIEW_PROVIDER
GAIALAB_REVIEW_EXTERNAL_ENABLED
GAIALAB_REVIEW_TIMEOUT_SECONDS
GAIALAB_REVIEW_MAX_RETRIES
```

Do not put API keys in YAML, command-line arguments, logs, or repository files.

## Command-line workflow

### Build a queue

```bash
python scripts/review_automation.py build-queue --version v0.6
```

The queue excludes approved, rejected, and superseded records unless
`--include-finalized` is supplied. Ordering is:

1. effective risk severity;
2. critical findings;
3. high findings;
4. lowest quality score;
5. highest duplicate likelihood; and
6. record ID.

Filters include repeated `--category`, `--risk-level`, and `--review-status`
options, quality bounds, domain-review requirement, training eligibility,
pagination, and finalized-record inclusion.

Use `--dry-run` to print the snapshot without writing files:

```bash
python scripts/review_automation.py build-queue \
  --version v0.6 --category healthcare --page-size 20 --dry-run
```

### Analyze records

```bash
python scripts/review_automation.py analyze --version v0.6
```

Bulk filters are `--category`, `--record-id`, and `--limit`. Existing
recommendations for the same record hash are skipped unless `--force` is
supplied. `--provider local` is the offline default. Analysis never changes an
official status.

Safe preview:

```bash
python scripts/review_automation.py analyze \
  --version v0.6 --record-id v06-banking-001 --dry-run
```

### Create a daily pack

```bash
python scripts/review_automation.py daily-pack --version v0.6 --limit 20
```

Each entry includes key findings, candidate recommendation, domain-review
flags, suggested revision, estimated complexity, unresolved critical issues,
and the complete traceable advisory analysis.

### Refresh downstream reports

After a human decision:

```bash
python scripts/review_automation.py refresh --version v0.6
```

Refresh recalculates quality assessments, the quality summary, eligibility
decisions, review progress, and a scorecard when the release manifest exists.
It explicitly reports that no release was created or published.

## Write-once outputs

Generated outputs use new run directories rather than replacing previous runs:

```text
evaluation/automated_reviews/<version>/
evaluation/review_queues/<version>/
evaluation/daily_packs/<version>/
evaluation/review_audit/<version>/
evaluation/review_refresh/<version>/
```

Analysis runs and daily packs contain `automated_audit.jsonl`. The central audit
directory keeps `automated_events.jsonl` and `human_events.jsonl` separate.
Generated directories are ignored by Git because human audit data can contain
private reviewer identifiers and notes.

Every recommendation records:

- dataset version, record ID, revision, and input record SHA-256;
- prompt, analyzer, provider, and model versions;
- generation timestamp;
- findings, rationale, confidence, and recommendation; and
- deterministic recommendation SHA-256.

Audit event hashes are recomputed during model validation. A human action in the
AI-assisted workflow is rejected unless its recommendation already exists in
the automated audit log for the current record hash.

## Streamlit workflow

Start the integrated application:

```bash
python -m streamlit run app/Home.py
```

Open **AI-Assisted Review** in the sidebar. The page provides:

- dataset status, eligibility, quality, and risk summaries;
- queue filters and prioritization;
- original immutable prompt and response;
- findings, duplicate explanations, recommendation, rationale, and confidence;
- suggested revision and impact explanations;
- combined audit history;
- explicit role-aware human controls; and
- completion and domain-review backlog reporting.

### Unified Review and Review Next

Open **Unified Review** to navigate and decide on one page. Configure dataset
version, category, risk, status, recommendation, domain-review requirement,
training eligibility, pilot limit, reviewer ID, and reviewer role. Finalized
records remain excluded unless explicitly included.

**Review Next** loads the highest-priority unprocessed item in the active
deterministic queue. After a successful action, the system persists the
governed review or linked revision, appends the separate human audit, refreshes
downstream reports, and advances. **Skip** advances without changing status.

Pilot mode defaults to five records and reports completed, remaining, approved,
revision-requested, rejected, escalated, skipped, newly eligible, and domain
backlog counts. It never reviews the rest of the queue automatically.

Approval and rejection require confirmation. Rejection, escalation, and
revision actions require a note. Escalation also requires a target:
`technical`, `domain`, `safety`, or `provenance`. Approval displays exact
technical, domain, provenance, licence, and unresolved-safety blockers.
Accepting or editing a suggestion creates a linked draft revision; the audited
recommendation preserves the original suggestion and the registry event
preserves the final human-edited content.

If a selected record has no stored recommendation, **Generate local advisory
analysis** stores a local recommendation and automated audit event without
changing review status.

A typical low-risk path is:

```text
draft
  -> human acknowledges analysis
  -> technical reviewer completes technical review
  -> authorized human confirms approval
```

A configured domain-review path is:

```text
draft
  -> human acknowledges analysis
  -> technical reviewer completes technical review
  -> domain reviewer completes domain review
  -> authorized human confirms approval
```

Accepting or editing a suggestion calls the existing revision mechanism. The
new content becomes a linked draft revision and the prior immutable snapshot is
not changed. Discarding a suggestion writes only the human audit action.

The environment can redirect local application data:

```text
GAIALAB_DATASET_REGISTRY
GAIALAB_DATASET_RELEASES
GAIALAB_AUTOMATED_REVIEWS
GAIALAB_REVIEW_AUDIT
GAIALAB_REVIEW_REFRESH
```

## Optional provider integration

The repository intentionally contains no paid API client. An application may
explicitly construct `CallableJSONProvider` with a caller-owned function after
enabling external analysis in configuration. The adapter:

- sends only prompt version/template, record ID, category, risk, user text, and
  assistant text;
- applies configured timeout and retry limits;
- requires the complete structured JSON schema;
- redacts provider response details from failures; and
- falls back to deterministic local analysis on failure or malformed output.

Externally generated recommendations are clearly labelled. They remain advisory
and pass through the same human gates.

## Release state and publication readiness

Dataset release state progresses only with explicit evidence:

```text
local_draft / under_review
  -> release_candidate
  -> verified
  -> approved_for_publication
  -> published
```

A folder, version string, or local name such as `v0.7-rc1` does not establish
publication. Verification, publication approval, and publication require
explicit registry events.

Read-only checks:

```bash
python scripts/review_automation.py publication-readiness --version v0.6
python scripts/review_automation.py release-status --version v0.7
```

Publication readiness reports review completion, approved and rejected counts,
revisions, technical/domain backlogs, provenance coverage, critical findings,
eligibility, release-candidate existence, verification, publication approval,
publication status, and blocking reasons. It performs no upload or Git action.

Currently, v0.6 is local and under review; it has not been uploaded or
published. v0.7 has not been built and must remain `not_created`. The safe path
is human review, resolution and eligibility refresh, separately authorized
candidate creation, verification, explicit publication approval, and only then
separately authorized publication.

## Security and privacy

- Never commit credentials, provider responses containing secrets, reviewer
  identities, or decision notes.
- Keep external analysis disabled unless an operator explicitly opts in.
- Review provider privacy and data-retention terms before sending any record.
- Do not add private, scraped, copyrighted, or ambiguously licensed data.
- Preserve `source`, `license`, record hashes, and immutable releases.
- Do not treat a quality score, candidate recommendation, or queue position as
  approval.
- Do not manually edit registry event logs or audit JSONL.
- Back up registry and evaluation state before operational review sessions.
- Use the public verification interface—not internal audit files—for public
  integrity checks.

The callable timeout cannot terminate arbitrary third-party Python code already
running in another thread. Provider adapters should use clients with their own
network timeouts and cancellation behavior.

## Contributor verification

Run:

```bash
ruff check src/review_automation scripts/review_automation.py \
  app/ai_assisted_review.py app/pages/1_AI_Assisted_Review.py \
  tests/test_review_automation_*.py

python -m compileall -q src/review_automation scripts/review_automation.py

python -m src.validate_dataset data/gaialab_naija_v0.1.jsonl \
  --output-dir prepared_data/validation-check

python -m pytest -v
```

Before staging changes, confirm no generated audit output, secrets, model
weights, checkpoints, or sensitive evaluation data are included.

## Current limitations

- Deterministic rules indicate review needs but do not establish factual truth.
- Near-duplicate matching uses lightweight local lexical similarity rather than
  semantic embeddings.
- Nigerian English and Nigerian Pidgin findings still require review by
  relevant Nigerian speakers and domain participants.
- There is no bundled external provider or network client.
- Registry and companion audit files are append-only but are not a distributed
  database transaction; the existing review event remains the authoritative
  human decision record if a later companion-audit write encounters an I/O
  failure.
- This workflow does not train a model or publish a release.

See also:

- [AI-assisted review architecture](AI_ASSISTED_REVIEW_ARCHITECTURE.md)
- [Dataset management platform](dataset_management_platform.md)
- [Release process](architecture/release_process.md)
- [Public release verification](public_release_verification.md)
