---
base_model: Qwen/Qwen2.5-0.5B-Instruct
library_name: peft
pipeline_tag: text-generation
language:
  - en
license: mit
tags:
  - peft
  - lora
  - qwen
  - nigeria
  - nigerian-english
  - customer-service
  - small-business
  - conversational-ai
  - instruction-tuning
datasets:
  - custom
---

# GaiaLab Naija Assistant v0.3

GaiaLab Naija Assistant v0.3 is an experimental LoRA adapter trained on top of `Qwen/Qwen2.5-0.5B-Instruct`.

The project focuses on practical communication for Nigerian users, small businesses, customer service, professional writing, and locally relevant assistance.

## Model Details

- Base model: `Qwen/Qwen2.5-0.5B-Instruct`
- Adapter type: LoRA
- Version: v0.3
- Developer: Oluwafemi Idiakhoa
- Organization: GaiaLab AI
- Language: English
- Status: Experimental research release

## Intended Uses

- Customer-service messages
- Small-business communication
- Professional email writing
- WhatsApp business responses
- Delivery updates and payment reminders
- Nigerian English
- Nigerian Pidgin experimentation
- Agriculture-related communication
- AI literacy

## Training Data

The v0.3 dataset contains 212 reviewed records.

- Training records: 170
- Validation records: 42
- Format: instruction, input, output, language, category, source, license
- Source: GaiaLab Naija curated research dataset
- Review: automated checks followed by human review and approval

The dataset is not currently published as a standalone public dataset.

## Training Procedure

- Epochs: 3
- Learning rate: 0.0002
- Batch size: 2
- Gradient accumulation: 8
- Effective batch size: 16
- LoRA rank: 16
- LoRA alpha: 32
- Seed: 42

Target modules:

- `q_proj`
- `k_proj`
- `v_proj`
- `o_proj`

## Training Results

| Metric | Result |
|---|---:|
| Total records | 212 |
| Training records | 170 |
| Validation records | 42 |
| Epoch 1 evaluation loss | 1.450 |
| Epoch 2 evaluation loss | 1.335 |
| Epoch 3 evaluation loss | 1.305 |
| Final training loss | 1.789 |
| Training runtime | 112.6 seconds |

Evaluation loss decreased across each epoch:

`1.450 → 1.335 → 1.305`

## Example

### Prompt

```text
Write a polite message telling a customer that their order will arrive tomorrow instead of today.
```

### Response

```text
Dear [Customer Name], we regret to inform you that your order has been delayed until tomorrow due to unforeseen circumstances. We apologize for any inconvenience this may cause and look forward to receiving your confirmation once it arrives.
```

## Initial Evaluation

| Category | Score |
|---|---:|
| Professional tone | 5/5 |
| Grammar | 5/5 |
| Fluency | 5/5 |
| Instruction following | 4/5 |
| Factual consistency | 3/5 |

The response was professional and fluent but added a reason for the delay and requested confirmation, neither of which was explicitly included in the prompt.

## How to Use

```bash
pip install transformers peft accelerate torch
```

```python
import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer

base_model_name = "Qwen/Qwen2.5-0.5B-Instruct"
adapter_name = "mgbam/gaialab-naija-adapter-v0.3"

tokenizer = AutoTokenizer.from_pretrained(adapter_name)
base_model = AutoModelForCausalLM.from_pretrained(
    base_model_name,
    dtype=torch.float16,
    device_map="auto",
)
model = PeftModel.from_pretrained(base_model, adapter_name)
model.eval()

messages = [
    {
        "role": "system",
        "content": (
            "You are GaiaLab Naija Assistant. Follow the user's facts "
            "exactly and do not invent details."
        ),
    },
    {
        "role": "user",
        "content": (
            "Write a polite message telling a customer that their order "
            "will arrive tomorrow instead of today."
        ),
    },
]

prompt = tokenizer.apply_chat_template(
    messages,
    tokenize=False,
    add_generation_prompt=True,
)
inputs = tokenizer(prompt, return_tensors="pt").to(model.device)

with torch.no_grad():
    outputs = model.generate(
        **inputs,
        max_new_tokens=120,
        do_sample=False,
        repetition_penalty=1.1,
        pad_token_id=tokenizer.eos_token_id,
    )

response = tokenizer.decode(
    outputs[0][inputs["input_ids"].shape[1]:],
    skip_special_tokens=True,
)
print(response.strip())
```

## Limitations

- The adapter was trained on a small dataset.
- It may introduce details that were not included in the prompt.
- Nigerian Pidgin coverage remains limited.
- It has not yet been evaluated on a large external benchmark.
- It may reproduce biases or inaccuracies from the base model.
- It should not be relied upon for medical, legal, financial, or safety-critical decisions.

## Responsible Use

Users should review generated responses before sending them to customers or using them professionally.

The model should not be used to:

- Generate deceptive or fraudulent messages
- Impersonate individuals or institutions
- Provide unverified medical, legal, or financial advice
- Automate high-impact decisions without human oversight
- Produce harmful, discriminatory, or abusive content

## Future Work

The planned v0.4 release will focus on:

- A larger reviewed dataset
- Better instruction adherence
- Reduced hallucination
- A fixed evaluation benchmark
- Expanded Nigerian English and Pidgin coverage
- Automated comparison between model versions

## Citation

```bibtex
@software{idiakhoa2026gaialabnaija,
  author = {Oluwafemi Idiakhoa},
  title = {GaiaLab Naija Assistant v0.3},
  year = {2026},
  organization = {GaiaLab AI},
  url = {https://github.com/oluwafemidiakhoa/gaialab-naija-assistant}
}
```

## License

The adapter is released under the MIT License. The base model is governed by the license and terms of `Qwen/Qwen2.5-0.5B-Instruct`.
