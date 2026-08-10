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

The module does **not** import vendor SDKs, make network calls, or read provider API keys. Applications inject:

1. a provider generation callable,
2. a text extractor for that provider's returned object, and
3. optional non-secret metadata extraction.

This prevents provider API churn from becoming part of the Trust Rail policy boundary.

## Pre-delivery gate

`verify_provider_candidate(...)` performs:

```text
provider transport
    -> candidate text
    -> normalized provider/model metadata
    -> GaiaLab Trust verification
    -> delivery decision
```

Only `ALLOW` is marked eligible for automated delivery.

`VERIFY`, `REWRITE`, `ESCALATE`, and `BLOCK` remain held for the caller's verification, rewrite, or human escalation flow.

A provider is therefore never trusted merely because the model call succeeded.

## Privacy

The normalized candidate metadata deliberately excludes secret-like fields. Keys containing terms such as `api_key`, `token`, `password`, `private_key`, `authorization`, or `cookie` are dropped before the candidate record is returned.

The candidate SHA-256 binds:

- provider kind
- model name
- model version
- candidate text

It does not include provider credentials or transport objects.

## Example

```python
from src.provider_adapters import ProviderAdapter, verify_provider_candidate
from src.trust_api import verify_payload

adapter = ProviderAdapter(
    provider="private",
    model_name="support-model",
    generate=my_model_call,
    extract_text=lambda response: response.text,
)

result = verify_provider_candidate(
    adapter=adapter,
    provider_request={"messages": messages},
    trust_context={
        "authoritative_state": {"transaction_status": "pending"},
        "language": "Nigerian Pidgin",
    },
    verify_fn=verify_payload,
)

if result["delivery"]["automated_delivery_allowed"]:
    deliver_to_user()
else:
    hold_for_policy_flow(result["delivery"]["disposition"])
```

## Vendor-specific transports

Vendor SDK wrappers should live outside the deterministic policy core. They may convert provider-specific request/response objects into the injected callable contract, but they must not bypass `verify_provider_candidate` for consequential automated delivery.

This design also makes Qwen, N-ATLAS, self-hosted Hugging Face models, and future/private models first-class without requiring GaiaLab to make one vendor's SDK the canonical abstraction.
