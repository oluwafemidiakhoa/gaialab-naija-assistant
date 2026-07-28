# Dataset release scorecards

Scorecards are public, write-once summaries of integrity, provenance, licensing,
review completion, eligibility, quality, duplication, and benchmark coverage.
Quality values are advisory and remain null when no assessment run is supplied.
Reviewer identities, internal notes, and provenance evidence are excluded.

```bash
python scripts/generate_release_scorecard.py --version v0.6
```

If a scorecard already exists, generate into a new timestamped `--output-dir`;
published scorecards are never replaced.
