# Dataset lifecycle

Records enter with source and record-level licence metadata. Structural and
duplicate validation precedes deterministic quality assessment. A human
technical reviewer is mandatory; banking, healthcare, and government-services
examples also require a domain reviewer. Approval records the approved revision
and content hash.

Approved bytes are immutable. Corrections create a child draft with an incremented
revision and parent hash. Only an approved child can supersede its parent.
Publishing creates write-once CSV, JSONL, statistics, duplicate report, and
manifest files. Eligibility is evaluated again before every training candidate.
