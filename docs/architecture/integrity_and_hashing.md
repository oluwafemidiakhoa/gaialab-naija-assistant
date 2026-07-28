# Integrity and hashing

Example hashes use canonical JSON over identity, category, risk, messages,
source, and licence. Assessment, eligibility, review, training-run, artifact,
release, and scorecard objects use sorted compact JSON and SHA-256. File hashes
stream bytes rather than loading large artifacts in memory.

Immutable outputs are created atomically and refused when their destination
exists. Manifests bind named release files to hashes; public verification
recomputes both envelope and record hashes. Hashes prove byte integrity and
registry linkage, not factual correctness, authorship, consent, or quality.
