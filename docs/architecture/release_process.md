# Release process

1. Validate source data and licences.
2. Run deterministic quality assessment.
3. Complete technical and required domain review.
4. Approve records explicitly and resolve critical findings.
5. Publish an immutable dataset release and verify its manifest.
6. Generate a write-once public scorecard.
7. Build and inspect an eligibility release candidate.
8. Register an explicit training run and its outputs.
9. Evaluate every model on the same held-out benchmark and human rubric.
10. Approve and publish only with completed model-card and evaluation evidence.
11. Verify public dataset and model certificates before distribution.

No command in the governance pipeline uploads data, trains a model implicitly, or
promotes a release without a human action.
