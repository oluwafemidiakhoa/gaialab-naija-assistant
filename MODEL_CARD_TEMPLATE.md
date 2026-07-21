---
base_model: Qwen/Qwen2.5-0.5B-Instruct
library_name: peft
pipeline_tag: text-generation
license: "{{adapter_license_slug}}"
datasets:
  - "{{dataset_repository_or_name}}"
tags:
  - lora
  - nigeria
  - nigerian-english
  - nigerian-pidgin
---

# GaiaLab Adapter v0.1

> Replace every `{{placeholder}}` and remove this note before publishing. Verify the
> base-model licence and all linked artefacts independently.

GaiaLab Adapter v0.1 is an experimental LoRA adapter for
`Qwen/Qwen2.5-0.5B-Instruct`. It is intended to support writing and translation tasks
for Nigerian small-business contexts. It is not a standalone model and requires the
compatible base model.

## Training data

- Dataset: GaiaLab Naija Dataset v0.1
- Dataset revision or commit: `{{dataset_revision}}`
- Records used: `{{training_record_count}}` training and
  `{{validation_record_count}}` validation records
- Dataset licence: CC0-1.0
- Provenance: GaiaLab original drafts pending independent Nigerian human review
- Data processing: deterministic validation, deduplication, train/validation split,
  and assistant-response masking

The dataset must not be described as culturally validated unless documented review
evidence is available. Record any exclusions or corrections here:

`{{data_review_notes}}`

## Training procedure

- Base model: `Qwen/Qwen2.5-0.5B-Instruct`
- Base-model revision: `{{base_model_revision}}`
- Method: LoRA causal-language-model fine-tuning
- Configuration: `{{training_config}}`
- Software and hardware: `{{software_and_hardware}}`
- Random seed: `{{seed}}`
- Best checkpoint selection: lowest validation loss, with early stopping

Do not add a performance claim unless it is supported by reproducible logs and a
documented human evaluation.

## Intended use

The adapter is intended for experimental research and assisted drafting of:

- professional customer-service messages;
- plain-language explanations of common business terms;
- simple Nigerian English and Nigerian Pidgin translation; and
- routine small-business writing.

All customer-facing output should be reviewed by a person familiar with the context
and language variety. This adapter is not intended to provide legal, medical, tax,
financial, regulatory, or emergency advice.

## Evaluation procedure

Evaluate the base model and adapter on GaiaBench Africa v0.1 using the repository's
`compare_models.py` script. Human reviewers should use the GaiaBench reviewer guide
and 1–5 scorecard for instruction following, meaning preservation, naturalness,
professional tone, safety, hallucination, and business usefulness.

- GaiaBench revision: `{{benchmark_revision}}`
- Reviewers and relevant language experience: `{{reviewer_information}}`
- Evaluation report: `{{evaluation_report}}`
- Human-reviewed results: `{{human_results}}`

Automated generation alone is not an evaluation score.

## Limitations

- The training dataset is small and does not represent all Nigerian businesses,
  regions, speakers, registers, or Nigerian Pidgin varieties.
- The base model and adapter can hallucinate details, mishandle instructions, or
  produce unsafe and overconfident advice.
- Translation can lose tone, implied meaning, quantities, conditions, or uncertainty.
- Business terminology changes across industries and jurisdictions.
- GaiaBench v0.1 is small and pending independent Nigerian human review.

## Ethical considerations

- Do not use generated text to impersonate a person or fabricate business records.
- Protect customer and worker privacy; do not submit confidential conversations or
  identifying information without a lawful, consented basis.
- Use human review for safety, language naturalness, stereotypes, and consequential
  decisions.
- Document the base model, adapter, dataset, and evaluation revisions so results can
  be reproduced and corrected.
- Provide a route for affected communities and contributors to report harmful output
  or request corrections.

## Known failures

Document observed failures, including unsuccessful examples and their review status:

`{{known_failures}}`

## Licence and attribution

- Adapter licence: `{{adapter_license}}`
- Base-model licence: `{{verified_base_model_license}}`
- Dataset licence: CC0-1.0
- Code licence: MIT

Users must comply with the verified base-model licence and any applicable laws and
policies. Do not publish this template with unresolved licence placeholders.
