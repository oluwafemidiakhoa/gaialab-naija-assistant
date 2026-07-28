# GaiaLab Naija Assistant

GaiaLab Naija Assistant is an open-source AI research project focused on practical language models for Nigerian communication, small-business support, customer service, professional writing, and locally relevant assistance.

## Current Release

**GaiaLab Naija Assistant v0.3**

- Base model: `Qwen/Qwen2.5-0.5B-Instruct`
- Training method: LoRA
- Total reviewed records: 212
- Training records: 170
- Validation records: 42
- Epochs: 3
- LoRA rank: 16
- LoRA alpha: 32
- Final validation loss: 1.305
- Status: Experimental research release

## Project Goals

- Nigerian small-business communication
- Customer-service responses
- Professional emails and WhatsApp business messages
- Nigerian English and Nigerian Pidgin
- Delivery and payment updates
- Agriculture-related assistance
- AI literacy and scam-awareness guidance

## Repository Structure

```text
app/          Application files
config/       General project configuration
data/         Training and evaluation datasets
evaluation/   Human review and benchmark tools
notebooks/    Research and experimentation notebooks
outputs/      Training and evaluation outputs
scripts/      Data preparation and utility scripts
src/          Core source code
tests/        Automated tests
training/     Training configurations
```

## Dataset Management

The local dataset platform provides immutable version snapshots, append-only
human review, per-example SHA-256 hashes, semantic-duplicate reports, automatic
statistics, CSV/JSONL releases, and cross-model benchmark summaries.

See [docs/dataset_management_platform.md](docs/dataset_management_platform.md)
for the reproducible workflow. Launch the reviewer with:

```bash
streamlit run app/dataset_review.py
```

Public, privacy-preserving release verification is documented in
[docs/public_release_verification.md](docs/public_release_verification.md).

## Governance platform

The production governance layer adds deterministic advisory quality assessment,
role-aware append-only human review, training eligibility, release scorecards,
write-once model/run/artifact registration, cross-version benchmark reports,
offline Hugging Face export, and public dataset/model verification. Start the
integrated local dashboard with:

```bash
streamlit run app/Home.py
```

The v0.6 release contains 200 synthetic draft records. They are **not**
training-eligible or culturally validated until the required Nigerian human
review is documented. See [the system overview](docs/architecture/system_overview.md)
and [release process](docs/architecture/release_process.md).

## AI-assisted dataset review

The local-first review assistant adds deterministic quality and duplicate
analysis, prioritized queues, non-mutating revision suggestions, separate
automated and human audit events, daily work packs, and downstream eligibility
refreshes. Recommendations are advisory only: approval, rejection, revision,
escalation, and publication always require separate governed human actions.

```bash
python scripts/review_automation.py build-queue --version v0.6
python scripts/review_automation.py analyze --version v0.6
python scripts/review_automation.py daily-pack --version v0.6 --limit 20
python scripts/review_automation.py refresh --version v0.6
python -m streamlit run app/Home.py
```

The default analyzer is deterministic and offline; no API key is required.
See [the complete AI-assisted review workflow](docs/AI_ASSISTED_REVIEW.md).

## v0.3 Training Pipeline

1. Dataset collection
2. Human review
3. Approval extraction
4. Dataset normalization
5. Training-data validation
6. LoRA adapter training
7. Validation-loss evaluation
8. Manual response testing
9. Model release and documentation

## Training Configuration

```yaml
model: Qwen/Qwen2.5-0.5B-Instruct
dataset: data/v0.3/prepared/gaialab_naija_v0.3_training_ready.jsonl
learning_rate: 0.0002
epochs: 3
batch_size: 2
gradient_accumulation: 8
lora_rank: 16
lora_alpha: 32
target_modules:
  - q_proj
  - k_proj
  - v_proj
  - o_proj
evaluation_frequency: 1
seed: 42
```

## v0.3 Results

| Metric | Result |
|---|---:|
| Total reviewed records | 212 |
| Training records | 170 |
| Validation records | 42 |
| Epoch 1 validation loss | 1.450 |
| Epoch 2 validation loss | 1.335 |
| Epoch 3 validation loss | 1.305 |
| Final training loss | 1.789 |
| Training runtime | 112.6 seconds |

Validation loss improved across all three epochs:

```text
1.450 → 1.335 → 1.305
```

## Initial Evaluation

**Prompt**

```text
Write a polite message telling a customer that their order will arrive tomorrow instead of today.
```

**Model response**

```text
Dear [Customer Name], we regret to inform you that your order has been delayed until tomorrow due to unforeseen circumstances. We apologize for any inconvenience this may cause and look forward to receiving your confirmation once it arrives.
```

| Category | Score |
|---|---:|
| Professional tone | 5/5 |
| Grammar | 5/5 |
| Fluency | 5/5 |
| Instruction following | 4/5 |
| Factual consistency | 3/5 |

The response was professional, but it added details not explicitly provided. Future versions will focus on stronger instruction fidelity and reduced hallucination.

## Installation

```bash
git clone https://github.com/oluwafemidiakhoa/gaialab-naija-assistant.git
cd gaialab-naija-assistant
python -m venv .venv
```

Windows activation:

```bash
.venv\Scripts\activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

## Validate the Dataset

```bash
python train_adapter.py \
  --config training/v0.3_config.yaml \
  --output-dir models/v0.3 \
  --validate-only
```

## Train the Adapter

A CUDA-enabled GPU is required.

```bash
python train_adapter.py \
  --config training/v0.3_config.yaml \
  --output-dir models/v0.3
```

Google Colab or Kaggle is recommended.

## Use the v0.3 Adapter

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
```

## Limitations

- The adapter was trained on a relatively small dataset.
- It may add details that were not provided by the user.
- Nigerian Pidgin coverage remains limited.
- It should not be used as the sole source for legal, medical, financial, or safety-critical decisions.
- Human review is recommended before professional use.

## v0.4 Roadmap

- Larger reviewed dataset
- Fixed evaluation benchmark
- Improved instruction adherence
- Reduced hallucination
- Better Nigerian English and Pidgin coverage
- Automated model-version comparison

## Responsible Use

This project is intended for research, education, and responsible experimentation. Verify important information and keep humans involved in high-impact decisions.

## License

This project is released under the MIT License. The Qwen base model remains subject to its own license and usage terms.

## Author

**Oluwafemi Idiakhoa**  
Founder, GaiaLab AI  
AI Researcher and Engineer

## Links

- GitHub: https://github.com/oluwafemidiakhoa/gaialab-naija-assistant
- Hugging Face: https://huggingface.co/mgbam/gaialab-naija-adapter-v0.3
- GaiaLab AI: https://www.gailabai.com
