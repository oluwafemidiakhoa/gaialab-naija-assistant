# Model provider adapters

GaiaLab Naija Trust Rail keeps model-provider transport separate from verification policy.

## Boundary

`src/provider_adapters.py` defines one normalized candidate contract for:

- OpenAI
- Anthropic
- Gemini
- Qwen
- N-ATLAS
- private/internal models
- local models
- custom adapters

The deterministic core does **not** import vendor SDKs, make network calls, or read provider API keys. Applications inject provider generation behavior into `ProviderAdapter` instances.

`src/provider_sdk_wrappers.py` adds optional thin factories around already-configured SDK clients or local inference callables. These wrappers translate vendor request/response shapes into the same provider-neutral `ProviderAdapter`; they do not become a second policy engine.

## SDK wrapper factories

The optional wrapper module currently provides:

- `openai_responses_adapter(...)` for an already-configured OpenAI Responses client
- `anthropic_messages_adapter(...)` for an already-configured Anthropic Messages client
- `gemini_interactions_adapter(...)` for an already-configured Google GenAI Interactions client
- `qwen_dashscope_adapter(...)` for an already-configured DashScope `Generation` object
- `natlas_local_adapter(...)` for local/Hugging Face-style N-ATLAS inference

The wrappers intentionally accept configured clients/callables rather than API keys. GaiaLab therefore does not copy provider credentials into Trust Rail objects, receipts, candidate metadata, or wrapper configuration.

Provider-specific generation settings are allowlisted. Arbitrary `provider_options` are not forwarded to an SDK call, which prevents request data from becoming an escape hatch for secret or transport configuration.

## Pre-delivery gate

`verify_provider_candidate(...)` performs:

```text
provider SDK / local inference
    -> provider wrapper
    -> normalized candidate text + safe metadata
    -> GaiaLab Trust verification
    -> delivery decision
```

Only `ALLOW` is marked eligible for automated delivery.

`VERIFY`, `REWRITE`, `ESCALATE`, and `BLOCK` remain held for the caller's verification, rewrite, or human escalation flow.

A successful provider call therefore never implies delivery approval.

## Privacy and evidence binding

The normalized candidate metadata deliberately excludes secret-like fields. Keys containing terms such as `api_key`, `token`, `password`, `private_key`, `authorization`, or `cookie` are dropped before the candidate record is returned.

Wrapper metadata is deliberately narrow: response/request IDs, model/status fields, token-usage counters, and wrapper/transport identifiers where available. Raw SDK response objects are not included in the candidate envelope.

The candidate SHA-256 binds:

- provider kind
- model name
- model version
- candidate text

It does not include provider credentials or transport objects.

## Example

```python
from openai import OpenAI

from src.provider_adapters import verify_provider_candidate
from src.provider_sdk_wrappers import openai_responses_adapter
from src.trust_api import verify_payload

client = OpenAI()  # application/runtime owns credential configuration
adapter = openai_responses_adapter(
    client=client,
    model_name="your-model",
)

result = verify_provider_candidate(
    adapter=adapter,
    provider_request={"input": "What is the transfer status?"},
    trust_context={
        "authoritative_state": {"transaction_status": "pending"},
        "language": "Nigerian English",
    },
    verify_fn=verify_payload,
)

if result["delivery"]["automated_delivery_allowed"]:
    deliver_to_user()
else:
    hold_for_policy_flow(result["delivery"]["disposition"])
```

## N-ATLAS

N-ATLAS is handled as a local/self-hosted inference boundary rather than a hard-coded hosted API. `natlas_local_adapter(...)` accepts an inference callable, including pipeline-style callables, and normalizes its generated text into the same Trust Rail candidate contract.

This preserves model portability and avoids inventing a vendor-hosted contract where the deployment is controlled by the operator.

## Tests and CI

`tests/test_provider_sdk_wrappers.py` uses fake configured clients/callables. No external model calls or credentials are required.

The focused `Provider Adapter Contracts` workflow verifies:

- vendor request translation
- provider-option allowlisting
- provider response text extraction
- narrow non-secret metadata extraction
- empty-output fail-closed behavior
- local N-ATLAS normalization
- contradicted provider output remaining blocked by the Trust Rail pre-delivery gate

Provider SDK churn may require wrapper updates, but must not change the deterministic Trust Rail disposition semantics.
