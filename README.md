# GaiaLab Naija Assistant

GaiaLab Naija Assistant is a free, open-source experiment for helping Nigerian
small-business owners write professional customer responses, understand common
business terms, and translate simple messages between Nigerian English and Nigerian
Pidgin. Version 0.1 is a reproducible scaffold: **no model has been trained and no
performance results are claimed**.

Phase 2 introduces **GaiaBench Africa**, an open, human-scored evaluation benchmark
for African business AI models. GaiaBench runs local Hugging Face models only; it
does not train a model or use a paid API.

Phase 3 introduces the **GaiaLab Adapter v0.1 training and release pipeline**. The
pipeline supports reproducible LoRA training, checkpoint resume, human-scored model
comparison, and controlled Hugging Face publishing. No adapter weights or training
results are committed or claimed by this repository.

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
explicit LoRA adapter training   (train_adapter.py)
        |
        +--> base/adapter comparison (compare_models.py + GaiaBench)
        +--> reviewed Hub release   (publish_to_huggingface.py)
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

Validate GaiaLab Naija Dataset v0.1 and the default adapter configuration:

```bash
python -m src.validate_dataset data/gaialab_naija_v0.1.jsonl --output-dir prepared_data
python train_adapter.py --validate-only
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
| `category` | One of the task categories documented in `data/README.md` |
| `source` | Traceable origin or documented collection method |
| `license` | Licence or permission governing the record |

The repository contains exactly 100 original CC0 draft examples in GaiaLab Naija
Dataset v0.1. They cover customer service, terminology, two translation directions,
and business writing. Every row is explicitly pending Nigerian human review; this
small draft does not constitute enough reviewed data for a production fine-tune. The
validator rejects missing metadata and empty instructions/outputs, removes exact
duplicates, reports language/category totals, warns about very short outputs, and
creates reproducible train/validation splits. See [data/README.md](data/README.md).

## GaiaLab Adapter v0.1 training

The versioned defaults are in `training/default_config.yaml`. They use
`Qwen/Qwen2.5-0.5B-Instruct` and the unchanged GaiaLab Naija Dataset v0.1. The
training entry point validates and splits the dataset deterministically, masks prompt
tokens from the loss, evaluates and saves a checkpoint after every epoch, uses early
stopping, reloads the checkpoint with the lowest validation loss, and saves the final
LoRA artefact under `best_adapter/`.

Training is always an explicit GPU operation:

```bash
python train_adapter.py \
  --config training/default_config.yaml \
  --output-dir outputs/gaialab-adapter-v0.1
```

Resume the latest complete checkpoint automatically:

```bash
python train_adapter.py \
  --config training/default_config.yaml \
  --output-dir outputs/gaialab-adapter-v0.1 \
  --resume-from-checkpoint
```

Pass a checkpoint path after `--resume-from-checkpoint` to select one explicitly.
Training writes `training.log`, `metrics.csv`, TensorBoard events, Trainer state,
automatic checkpoints, a resolved configuration, and a factual run summary under the
ignored output directory. View TensorBoard logs with:

```bash
tensorboard --logdir outputs/gaialab-adapter-v0.1/tensorboard
```

No performance claim should be made from training loss alone.

### Google Colab

1. Open `notebooks/gaialab_naija_qlora_colab.ipynb` in Colab.
2. Select **Runtime → Change runtime type → GPU**.
3. Run the setup and validation cells, then inspect `training/default_config.yaml`.
4. Only after confirming the dataset provenance and configuration, explicitly run the
   `train_adapter.py` training cell.
5. Download the LoRA adapter before the runtime expires.

The notebook does not train on open. Free GPU availability, memory, and session limits
vary. Preserve checkpoints outside the temporary runtime if you need to resume later.

### Kaggle

1. Create a Kaggle notebook, enable a GPU under **Settings → Accelerator**, and add
   this repository by cloning it or uploading a reviewed snapshot.
2. Set the working directory to the repository and install `requirements.txt`.
3. Run `python train_adapter.py --validate-only` and inspect the configuration.
4. After confirming data provenance, start an explicit run:

```bash
python train_adapter.py \
  --config training/default_config.yaml \
  --output-dir /kaggle/working/gaialab-adapter-v0.1
```

Save the adapter as a Kaggle output. Do not put secrets directly in notebook cells.

## Evaluation

GaiaBench Africa v0.1 contains 30 original evaluation prompts, split evenly across
customer service, business terminology, English-to-Nigerian-Pidgin translation,
Nigerian-Pidgin-to-English translation, and business writing. It includes no
expected answers and no prompts copied from the bundled training demonstrations.

Each benchmark record contains an ID, instruction, input, expected characteristics,
target language, category, difficulty, review status, source, and licence. The
expected characteristics guide human review without asserting that one reference
answer is the only correct response.

Run any compatible local path or Hugging Face causal instruction model:

```bash
python -m evaluation.run_benchmark \
  --model-id /path/to/local-model-or-hugging-face-id \
  --output evaluation/results.jsonl
```

Alternatively, set `GAIABENCH_MODEL_ID` and omit `--model-id`. The runner validates
the benchmark, generates one response per prompt, and writes blank human-review
fields. It never assigns or aggregates scores. Existing output files are protected
unless `--overwrite` is supplied.

Reviewers must use [the reviewer guide](evaluation/reviewer_guide.md) and enter 1–5
scores with [the scorecard](evaluation/scorecard.md) for instruction following,
meaning preservation, naturalness, professional tone, safety, hallucination, and
business usefulness. Record model revisions and document failures as well as
successes. `evaluation/results*.jsonl` is ignored by default; inspect generated text
for sensitive content before sharing it.

The benchmark and rubric are original drafts pending independent Nigerian human
review. They are not culturally validated, and no benchmark results are claimed.

## Compare the base model and adapter

After a real adapter run completes, generate side-by-side GaiaBench responses:

```bash
python compare_models.py \
  --adapter-path outputs/gaialab-adapter-v0.1/best_adapter \
  --output-dir outputs/comparison
```

This creates `comparison.json`, `comparison.csv`, and `comparison.md` with benchmark
metadata, base and adapter responses, average-score placeholders, and blank human
review fields. It never assigns scores or declares a winner. Human reviewers must use
the GaiaBench guide and scorecard before any evaluation report is published.

## Publishing to Hugging Face

1. Copy `MODEL_CARD_TEMPLATE.md`, replace every placeholder, document known failures,
   and verify the base-model licence.
2. Complete human review of the comparison report.
3. Authenticate with `hf auth login` or store `HF_TOKEN` in the notebook or platform
   secret store. Never pass a token as a command-line argument or commit it.
4. Publish privately first:

```bash
python publish_to_huggingface.py \
  --repo-id YOUR_ACCOUNT/gaialab-adapter-v0.1 \
  --adapter-dir outputs/gaialab-adapter-v0.1/best_adapter \
  --model-card /path/to/completed-model-card.md \
  --evaluation-report outputs/comparison/comparison.md
```

The publisher uploads only the LoRA adapter package and tokenizer from `best_adapter/`,
the completed model card, and the selected evaluation report. Repositories are private
by default; use `--public` only after all artefacts, licences, and human reviews are
ready. The script never prints or accepts an API token argument.

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

- No training has been performed, and the 100 draft examples have not yet completed
  Nigerian human review.
- GaiaBench v0.1 is small, focuses on Nigerian English and Nigerian Pidgin, and is not
  representative of all African business settings or languages.
- Benchmark prompts and review criteria are pending independent Nigerian human review.
- The base model may not reliably represent Nigerian business contexts or language.
- Nigerian Pidgin and Nigerian English vary by speaker, region, audience, and setting.
- Translation may lose tone or meaning; customer-facing messages need human review.
- The app has no retrieval, source citations, authentication, or production hardening.
- Small models can hallucinate, follow malicious prompt text, or produce unsafe advice.

## Roadmap

- Co-design a consent and data-governance process with Nigerian business owners.
- Build a larger, versioned, openly licensed dataset with regional review.
- Establish transparent human evaluation and publish failure analyses.
- Expand GaiaBench with consented prompts and reviewers from more African languages,
  regions, and business sectors.
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
