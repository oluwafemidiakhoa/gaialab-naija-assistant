# Benchmark methodology

GaiaLab benchmarks use immutable, hashed cases with expected and prohibited
behaviours and an explicit rubric. Human scores cover task completion, relevance,
clarity, safety, Nigerian context, Pidgin, business writing, refusal correctness,
hallucination risk, credential protection, and high-risk escalation.

Before a run, benchmark IDs and exact/normalized prompts are checked against
training data; near duplicates are reported for human review. Results from models
are described as comparable only when both benchmark version and scoring method
match. Reports retain failure examples and model/dataset verification status.
