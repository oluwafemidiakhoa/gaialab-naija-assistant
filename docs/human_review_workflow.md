# Human review workflow

Automated assessments are advisory and can only move a record to
`automated_reviewed`. A named human reviewer must complete technical review for
every record. Banking, healthcare, and government-services records additionally
require domain review before approval.

The append-only review log records the content hash, revision, role, notes, score,
timestamp, and a hash of each event. Invalid transitions fail. Approved content is
immutable: editing creates a new draft revision linked by `parent_record_sha256`;
the relationship is marked as superseding only after the child is approved.

Reviewer identifiers and notes are internal and must not be placed in public
certificates. Bulk queue export is supported by the review UI; bulk approval is
intentionally unavailable.
