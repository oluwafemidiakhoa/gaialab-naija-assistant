# GaiaLab Naija Assistant v0.3 Dataset Plan

## Goal

Improve instruction following, meaning preservation, Nigerian Pidgin naturalness, hallucination control, and business usefulness.

## Target Size

500-1,000 human-reviewed examples.

## Priority Categories

### 1. Instruction Fidelity

Examples must teach the model to:

- preserve dates and quantities exactly;
- retain uncertainty such as "may," "not confirmed," and "subject to inspection";
- avoid inventing refunds, discounts, replacements, delivery dates, or guarantees;
- distinguish customer, supplier, sender, and business perspectives;
- follow negative constraints such as "do not promise free delivery."

### 2. Nigerian Pidgin

Include:

- English to Nigerian Pidgin;
- Nigerian Pidgin to professional Nigerian English;
- short business messages;
- customer-service replies;
- safety notices;
- delivery and payment messages.

Every Pidgin example should be reviewed by a fluent Nigerian speaker.

### 3. Meaning Preservation

Examples should test:

- quantities;
- dates and times;
- payment status;
- delivery conditions;
- uncertainty;
- allergies and safety warnings;
- responsibility and ownership.

### 4. Concise Business Responses

Teach the model to produce short responses without omitting required facts.

### 5. Hallucination Resistance

Include prompts where the correct response must avoid inventing:

- dates;
- prices;
- policies;
- refund timelines;
- inspection results;
- causes;
- guarantees.

## Data Quality Rules

- No duplicate prompts.
- No repetitive template endings.
- No invented details in target responses.
- Every response must satisfy all explicit constraints.
- Every translation must preserve meaning.
- Safety-sensitive examples require extra review.

## Evaluation

Evaluate against:

- Base Qwen
- GaiaLab v0.1
- GaiaLab v0.2
- GaiaLab v0.3

Use GaiaBench Africa and independent human review.