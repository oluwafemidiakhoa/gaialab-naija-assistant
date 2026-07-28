# Continuous integration

CI uses Python 3.11 and CPU-compatible dependencies. It runs the complete test
suite, validates the v0.1 and v0.6 JSONL releases, verifies the v0.6 manifest and
public-certificate privacy, renders Streamlit pages, performs an eligibility dry
run, and builds a temporary offline Hugging Face export. It then fails if the
immutable release or registry trees changed.

The separate release-verification workflow can be started manually and also runs
when verification or immutable release paths change. Neither workflow trains a
model, publishes a dataset, uploads an adapter, or requires secrets.
