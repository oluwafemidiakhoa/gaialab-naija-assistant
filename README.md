# GaiaLab Naija Assistant

GaiaLab Naija Assistant is a free, open-source experiment for helping Nigerian
small-business owners write professional customer responses, understand common
business terms, and translate simple messages between Nigerian English and Nigerian
Pidgin. Version 0.1 is a reproducible scaffold: **no model has been trained and no
performance results are claimed**.

> **Experimental disclaimer:** generated responses may be inaccurate. Review
> important business, legal, tax, and financial information before acting on it.

## Who it is for

The project is intended for traders, online sellers, service providers, artisans,
and other Nigerian micro and small-business operators, as well as researchers and
contributors building accessible local-language AI tools. It is not legal,
financial, tax, or regulatory advice.

## Architecture

```text
licensed JSONL data
        |
        v
validate + deduplicate + split  (src/validate_dataset.py)
        |
        v
chat-format Hugging Face Dataset (src/prepare_dataset.py)
        |
        v
optional QLoRA fine-tuning       (src/train_qlora.py)
        |
        +--> human-review benchmark (evaluation/)
        +--> local Gradio app        (app/app.py)
```

The initial training default is `Qwen/Qwen2.5-0.5B-Instruct`, a small open-weight
instruction model suitable for adapter fine-tuning on a modest CUDA GPU. The model
ID is configurable. Before training or redistribution, independently review the
selected model card, licence, limitations, and acceptable-use terms.

## Local installation

Python 3.11 is required. A virtual environment is recommended.

```bash
git clone https://github.com/oluwafemidiakhoa/gaialab-naija-assistant.git
cd gaialab-naija-assistant
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pytest
```

Validate and prepare the bundled demonstrations:

```bash
python -m src.validate_dataset data/sample_training_data.jsonl --output-dir prepared_data
python -m src.prepare_dataset --output-dir prepared_data/hf
```

Run the app with any compatible local path or Hugging Face causal instruction model:

```bash
export GAIALAB_MODEL_ID=Qwen/Qwen2.5-0.5B-Instruct
python app/app.py
```

Open `http://127.0.0.1:7860`. Model downloads are free but require disk space and
internet access. With no `GAIALAB_MODEL_ID`, the UI loads and displays a clear
configuration error when generation is requested.

## Dataset format

Each UTF-8 JSONL line is one object with exactly these required string fields:

| Field | Meaning |
| --- | --- |
| `instruction` | Task the assistant should perform |
| `input` | Optional context; an empty string is allowed |
| `output` | Desired assistant response |
| `language` | Response language or variety |
| `category` | Such as `customer_service`, `terminology`, or `translation` |
| `source` | Traceable origin or documented collection method |
| `license` | Licence or permission governing the record |

The repository contains exactly 20 CC0 original synthetic demonstrations. They show
the schema and do not constitute enough data for a useful production fine-tune. The
validator rejects missing metadata and empty instructions/outputs, removes exact
duplicates, reports language/category totals, warns about very short outputs, and
creates reproducible train/validation splits. See [data/README.md](data/README.md).

## Fine-tuning in Google Colab

1. Open `notebooks/gaialab_naija_qlora_colab.ipynb` in Colab.
2. Select **Runtime → Change runtime type → GPU**.
3. Run the setup and validation cells, then inspect the split and model configuration.
4. Only after replacing/expanding the demonstrations with consented, licensed data,
   explicitly run the training cell.
5. Download the LoRA adapter before the runtime expires.

The notebook does not train on open. Free GPU availability and limits vary. If 4-bit
operations are unsupported by the assigned runtime, stop rather than silently using
an unexpectedly expensive configuration.

## Fine-tuning on Kaggle

1. Create a Kaggle notebook, enable a GPU under **Settings → Accelerator**, and add
   this repository by cloning it or uploading a reviewed snapshot.
2. Set the working directory to the repository and install `requirements.txt`.
3. Run the validation and preparation commands above.
4. After confirming data provenance, start an explicit run:

```bash
python -m src.train_qlora \
  --model-id Qwen/Qwen2.5-0.5B-Instruct \
  --dataset-dir prepared_data/hf \
  --output-dir /kaggle/working/gaialab-naija-adapter
```

Save the adapter as a Kaggle output. Do not put secrets directly in notebook cells.

## Evaluation

The benchmark contains original prompts and qualitative review checks. It generates
an **unscored** review file; it does not invent an automated quality metric:

```bash
GAIALAB_MODEL_ID=/path/to/model-or-merged-adapter \
python -m evaluation.evaluate_model --output evaluation/results.jsonl
```

Reviewers should fill the `human_review` fields, record model and adapter revisions,
and document failures as well as successes. Generated result files are ignored by
default when placed under `outputs/`; review sensitive content before sharing.

## Publishing to Hugging Face

1. Create a Hugging Face model repository and authenticate with `hf auth login` or a
   secret `HF_TOKEN` in the notebook environment.
2. Write a model card stating the base model, adapter method, exact dataset versions,
   licences, intended uses, limitations, evaluation procedure, and that the system is
   experimental.
3. Review the adapter output, then publish it explicitly:

```python
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer

BASE_MODEL_ID = "Qwen/Qwen2.5-0.5B-Instruct"
base = AutoModelForCausalLM.from_pretrained(BASE_MODEL_ID)
adapter = PeftModel.from_pretrained(base, "outputs/gaialab-naija")
adapter.push_to_hub("YOUR_ACCOUNT/gaialab-naija-adapter", private=True)
AutoTokenizer.from_pretrained(BASE_MODEL_ID).push_to_hub(
    "YOUR_ACCOUNT/gaialab-naija-adapter", private=True
)
```

Start private for review, include the base model rather than duplicating its weights,
and only make the repository public when all data/model licences permit it. Never
commit an access token.

## Ethical data collection

- Obtain informed, specific permission from contributors and explain downstream use.
- Record provenance and a compatible licence for every example.
- Minimise data: remove names, phone numbers, addresses, account details, transaction
  references, and other personal or confidential information.
- Do not scrape private chats or assume public visibility grants training permission.
- Provide a practical withdrawal/correction process and version datasets so removals
  propagate to future models.
- Include speakers from different regions and business types; document gaps rather
  than treating one usage as the only Nigerian English or Pidgin.
- Use human review for harmful stereotypes, unsafe business advice, hallucinations,
  and translation meaning loss.

## Limitations

- No training has been performed and the bundled 20 examples are demonstrations only.
- The base model may not reliably represent Nigerian business contexts or language.
- Nigerian Pidgin and Nigerian English vary by speaker, region, audience, and setting.
- Translation may lose tone or meaning; customer-facing messages need human review.
- The app has no retrieval, source citations, authentication, or production hardening.
- Small models can hallucinate, follow malicious prompt text, or produce unsafe advice.

## Roadmap

- Co-design a consent and data-governance process with Nigerian business owners.
- Build a larger, versioned, openly licensed dataset with regional review.
- Establish transparent human evaluation and publish failure analyses.
- Train and document the first LoRA adapter only after data review.
- Add model-card automation, accessibility testing, and low-resource deployment paths.
- Explore opt-in terminology retrieval with traceable Nigerian public sources.

## Contributing

Open an issue before large changes. Keep pull requests focused, add tests, and run
`python -m pytest`. Dataset contributions must include provenance, permission/licence,
and confirmation that personal data was removed. Do not submit copied conversations
or model outputs as human-authored ground truth without clearly labelling and licensing
them. By contributing code, you agree that it is provided under the MIT licence; data
may use a separately documented compatible licence.
