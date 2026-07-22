---
base_model: Qwen/Qwen2.5-0.5B-Instruct
library_name: peft
pipeline_tag: text-generation
license: apache-2.0
language:
  - en
  - pcm
tags:
  - lora
  - peft
  - nigeria
  - nigerian-pidgin
  - business-assistant
---

# GaiaLab Naija Adapter v0.1

GaiaLab Naija Adapter v0.1 is an experimental LoRA adapter trained on
`Qwen/Qwen2.5-0.5B-Instruct`.

It explores Nigerian small-business communication, business writing,
Nigerian English, and Nigerian Pidgin.

## Intended use

The adapter is designed for research and experimentation involving:

- Nigerian small-business customer communication
- Professional business-writing assistance
- English-to-Nigerian-Pidgin translation
- Nigerian-Pidgin-to-English translation
- Explanation of common business terminology

## Training data

- 100 curated examples
- 80 training records
- 20 validation records
- 5 task categories

The dataset includes:

- Customer-service responses
- Nigerian business terminology
- English-to-Nigerian-Pidgin translation
- Nigerian-Pidgin-to-English translation
- Business writing

## Training configuration

- Base model: `Qwen/Qwen2.5-0.5B-Instruct`
- Fine-tuning method: LoRA
- Epochs: 3
- Training records: 80
- Validation records: 20

## Training results

- Final training loss: `2.342`
- Final evaluation loss: `2.106`

These results confirm that the adapter-training pipeline completed
successfully. They do not prove that the adapter is more accurate than
the base model across all tasks.

## Preliminary evaluation

Initial testing showed mixed results:

- Business-writing responses were generally clear and professional.
- Customer-service responses were polite but sometimes omitted requested details.
- Nigerian Pidgin translation quality was inconsistent.
- Some terminology responses contained factual errors.
- The model occasionally added information that was not present in the prompt.

This release should therefore be treated as a research prototype.

## Limitations

The model may:

- Produce inaccurate information
- Change or omit details during translation
- Generate unnatural Nigerian Pidgin
- Misunderstand cultural or business context
- Add unsupported facts or explanations
- Hallucinate business, legal, tax, financial, or regulatory guidance

Human review is required before real-world use.

## Loading the adapter

```python
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
from peft import PeftModel

base_model_id = "Qwen/Qwen2.5-0.5B-Instruct"
adapter_id = "mgbam/gaialab-naija-adapter-v0.1"

tokenizer = AutoTokenizer.from_pretrained(base_model_id)

base_model = AutoModelForCausalLM.from_pretrained(
    base_model_id,
    dtype=torch.float16,
    device_map="auto"
)

model = PeftModel.from_pretrained(
    base_model,
    adapter_id
)

model.eval()

Load the tokenizer from the base model because it contains the correct
Qwen chat template.

Model repository

Hugging Face:

mgbam/gaialab-naija-adapter-v0.1

Source code

GitHub:

oluwafemidiakhoa/gaialab-naija-assistant

Disclaimer

This is an experimental research release. Generated responses should be
reviewed before use in business, legal, financial, tax, medical, or
regulatory contexts.