# Governed Google Colab training

The Colab workflow runs the existing GaiaLab governed LoRA trainer on a
CUDA-enabled Google Colab runtime. It is designed for pipeline verification,
not a quality claim: `v0.7-rc3` contains only seven eligible examples—five
training, one validation, and one held-out benchmark.

The notebook is:

```text
notebooks/gaialab_governed_lora_colab.ipynb
```

It checks out branch `agent/professional-training-pipeline`, prints the exact
commit SHA, validates the immutable candidate, runs the full test suite, runs a
governed dry-run, and performs a five-step CUDA smoke run before full training
can start.

## Safety boundaries

- Immutable datasets, manifests, eligibility reports, and audit ledgers are
  read-only inputs.
- Candidate `v0.7-rc3` is bound to release label `v0.7.0-rc.3`.
- Training and evaluation outputs remain under `/content/gaialab-output`.
- The repository checkout remains under `/content/gaialab-naija-assistant`.
- Mounted or extracted governed data is exposed through
  `/content/gaialab-data/v0.7-rc3`.
- Full training is disabled by default.
- Hugging Face upload and browser output download are separately disabled by
  default.
- The notebook never prints `HF_TOKEN`.
- Tests and both governed dry-runs must pass before a model is loaded.
- Smoke or full training fails immediately without CUDA.

The notebook does not copy or relabel records and does not weaken the existing
manifest, content-hash, eligibility, duplicate, or leakage checks.

## Colab dependency set

`requirements-colab.txt` intentionally excludes `torch`, `torchvision`, and
`torchaudio`. Colab supplies a CUDA-matched PyTorch build; replacing it is a
common cause of a CPU-only or broken runtime.

Pinned versions:

| Package | Version | Compatibility reason |
|---|---:|---|
| transformers | 4.57.3 | Stable 4.x release satisfying TRL ≥4.56.2 |
| trl | 0.29.1 | Requested supported TRL line |
| peft | 0.18.1 | Current PEFT line compatible with Transformers/Accelerate |
| accelerate | 1.12.0 | Satisfies TRL ≥1.4.0 |
| datasets | 4.4.1 | Satisfies TRL ≥3.0.0 |
| huggingface_hub | 0.36.0 | Newer compatible 0.x Hub client |
| tokenizers | 0.22.1 | Compatible with Transformers 4.57.3 |
| safetensors | 0.7.0 | Adapter-safe serialization |
| sentencepiece | 0.2.1 | Tokenizer support |
| bitsandbytes | 0.48.2 | Linux CUDA/PyTorch 2.3+ compatible; optional to the trainer |
| PyYAML | 6.0.3 | Training configuration |
| matplotlib | 3.10.8 | Local metric visualization support |
| pytest | 9.0.2 | Full repository tests |
| streamlit | 1.52.2 | Streamlit application tests |

The pin rationale follows official PyPI metadata:

- [TRL 0.29.1 metadata](https://pypi.org/pypi/trl/0.29.1/json) declares
  `transformers>=4.56.2`, `accelerate>=1.4.0`, and `datasets>=3.0.0`.
- [Transformers 4.57.3](https://pypi.org/project/transformers/4.57.3/)
  stays on the 4.x API used by the repository.
- [bitsandbytes requirements](https://pypi.org/project/bitsandbytes/0.48.0/)
  document Linux NVIDIA CUDA support with PyTorch 2.3+.

The notebook prints Python, PyTorch, CUDA, and GPU information before
installation. It then verifies that the installed PyTorch distribution did not
change. If Hugging Face modules were already imported, use **Runtime → Restart
session**, then rerun the notebook from the first cell. Do not reinstall
PyTorch.

## Start a Colab session

1. Open Google Colab.
2. Select **Runtime → Change runtime type → GPU**.
3. Upload or open `notebooks/gaialab_governed_lora_colab.ipynb`.
4. Review the configuration cell.
5. Keep these defaults for the governed verification workflow:

```python
RUN_TESTS = True
RUN_DRY_RUN = True
RUN_SMOKE_TRAINING = True
RUN_FULL_TRAINING = False
RUN_EVALUATION = True
PUSH_TO_HUB = False
```

The notebook uses a command helper that prints complete stdout and stderr
before raising. Pytest runs as:

```bash
python -m pytest -vv --tb=short -ra
```

Collection errors are not filtered or hidden.

## Supply the governed candidate

`data/release_candidates/` is intentionally Git-ignored. A fresh clone cannot
contain the candidate. Create a ZIP of the complete, unchanged `v0.7-rc3`
directory on your computer. It must contain:

```text
release_candidate_manifest.json
split_manifest.json
eligibility_report.json
exclusion_report.json
training.jsonl
validation.jsonl
held_out_benchmark.jsonl
```

The ZIP must contain exactly one `release_candidate_manifest.json`. Keep the
default configuration:

```python
CANDIDATE_ZIP_PATH = ""
```

The candidate cell opens Colab's browser uploader; select the ZIP directly
from your computer. Google Drive is neither mounted nor required. If the ZIP
is already in the runtime, set `CANDIDATE_ZIP_PATH` to its `/content/...`
path instead. ZIP members are checked for path traversal before extraction.
Both Windows backslash and POSIX slash ZIP member paths are normalized safely.
The extraction directory is keyed by the ZIP SHA-256, so rerunning the cell
reuses identical input and refuses a different candidate at the same link.

## Governance preflight

Before model loading, the notebook requires non-empty training, validation,
and held-out splits and invokes:

```bash
python scripts/train_governed_lora.py \
  --config configs/training/v0.7.0-rc.3.yaml \
  --release-version v0.7.0-rc.3 \
  --train-file /content/gaialab-data/v0.7-rc3/training.jsonl \
  --validation-file /content/gaialab-data/v0.7-rc3/validation.jsonl \
  --output-dir /content/gaialab-output/preflight/<manifest-hash>/training \
  --dry-run
```

It also runs the evaluator in dry-run mode against the held-out benchmark.
Together these verify:

- release-label and candidate-version binding;
- candidate-manifest integrity;
- per-record content hashes;
- split counts and SHA-256 values;
- eligibility decisions and their hashes;
- unique record IDs and normalized prompts; and
- absence of ID, content-hash, and prompt leakage.

Failure stops the notebook before any model download or load.

## Smoke, full training, and resume

The smoke cell requires CUDA and caps training at five optimizer steps via
`--smoke-test`. Full training remains disabled until you deliberately set:

```python
RUN_FULL_TRAINING = True
```

It cannot run unless the smoke manifest says `smoke_test_completed`.

For an interrupted full run, set an existing checkpoint inside the full output
directory:

```python
RESUME_CHECKPOINT = (
    "/content/gaialab-output/training-v0.7.0-rc.3/checkpoint-25"
)
```

The governed trainer refuses unsafe output overlap and preserves prior attempt
manifests.

## Evaluation

Evaluation runs separately on:

- `validation.jsonl`; and
- `held_out_benchmark.jsonl`.

It never accepts the training split as the evaluation file. Each evaluation
writes `evaluation_summary.json` and `predictions.jsonl`. The notebook also
creates a consolidated `evaluation_metrics.json`.

Because the validation and benchmark sets contain one record each, loss,
perplexity, and generated text are pipeline diagnostics only. They are not
reliable evidence of model quality.

## Hugging Face authentication and upload

The recommended private target is:

```text
oluwafemidiakhoa/gaialab-naija-assistant-v0.7.0-rc.3-lora
```

Add `HF_TOKEN` through Colab **Secrets**. The notebook retrieves it only when
upload is explicitly enabled:

```python
from google.colab import userdata
HF_TOKEN = userdata.get("HF_TOKEN")
```

Set `PUSH_TO_HUB = True` only after full training and both evaluations pass.
The presence of an enabled `HF_TOKEN` secret does not automatically request
an upload. For an upload run, set both controls in the first configuration
cell and rerun the notebook from the beginning:

```python
RUN_FULL_TRAINING = True
PUSH_TO_HUB = True
```

Seeing `Upload skipped safely: PUSH_TO_HUB=False` means the opt-in switch is
off; it does not mean the secret is missing or invalid.
The notebook creates the target as private and uploads only the adapter
directory. It never uploads the governed candidate or audit data.

## Outputs and reports

Generated files remain outside Git:

```text
/content/gaialab-output/
  environment_report.json
  evaluation_metrics.json
  reproducibility_report.json
  final_summary.json
  preflight/
  smoke-v0.7.0-rc.3/
    adapter/
    checkpoint-*/
    training_manifest.json
    training_metrics.json
  training-v0.7.0-rc.3/
  evaluations/
    <training-manifest-hash>/
      validation/
        evaluation_summary.json
        predictions.jsonl
      held_out_benchmark/
        evaluation_summary.json
        predictions.jsonl
```

Reports include the Git SHA, GPU type, package versions, candidate hashes,
model ID, LoRA configuration, training duration when available, and hashes of
generated files. Changed reports receive timestamped revisions rather than
being silently overwritten.

Optional browser download is disabled by default:

```python
DOWNLOAD_OUTPUT_ARCHIVE = True
```

When enabled, the notebook creates a timestamped ZIP under `/content` and
opens the browser download dialog. It never mounts or writes to Google Drive.
Download important results before disconnecting because Colab runtime storage
is temporary.

## Final status

The last cell reports:

- governance status;
- test status;
- smoke-training status;
- full-training status;
- evaluation status;
- Hugging Face upload status; and
- output directory.

Do not claim that a model was trained, evaluated successfully, or improved
unless the corresponding manifests and reports were produced by a completed
run and independently reviewed.
