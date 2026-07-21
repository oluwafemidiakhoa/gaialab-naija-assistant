# AGENTS.md

These rules apply to all future Codex work in this repository.

## Project principles

- Keep the project free and open source. Do not introduce paid API dependencies.
- Target Python 3.11 and preserve a local-first workflow.
- Never claim that a model was trained, evaluated, or achieved a metric unless a
  reproducible artefact in the repository supports the claim.
- Never add copyrighted, scraped, private, or ambiguously licensed training data.
  Every dataset row must include specific `source` and `license` values.
- Treat GaiaLab Naija Dataset v0.1 as a 100-record draft pending Nigerian human
  review, not as a production-quality or culturally validated dataset.
- Keep Nigerian English and Nigerian Pidgin distinct without presenting either as
  culturally uniform. Invite review from speakers and small-business owners.

## Engineering rules

- Use the required JSONL schema documented in `data/README.md`.
- Run `python -m src.validate_dataset` before using any new dataset.
- Add or update tests for behavioural changes, then run the complete test suite.
- Keep model IDs, output paths, and app configuration configurable.
- Do not commit tokens, model weights, generated checkpoints, personal data, or
  evaluation outputs containing sensitive prompts.
- Training must require an explicit command; imports and notebooks must not start a
  training job automatically.
- Keep generated checkpoints, adapters, logs, metrics, comparisons, and TensorBoard
  events under ignored output directories. Never commit model artefacts.
- Do not publish an adapter with unresolved model-card placeholders or an unreviewed
  evaluation report. Keep Hugging Face credentials out of files and CLI arguments.
- Keep evaluation prompts separate from training data. Do not add expected answers
  to GaiaBench or assign model scores automatically; scores must come from humans.
- Describe GaiaBench language and review materials as drafts pending independent
  human review unless documented review evidence supports a stronger statement.
- Prefer small, reviewable changes and explain model/data licensing implications in
  pull requests.

## Completion checklist

1. Validate affected datasets.
2. Run `python -m pytest`.
3. Confirm documentation matches commands and defaults.
4. Confirm no secrets, weights, generated outputs, or unlicensed data are staged.
