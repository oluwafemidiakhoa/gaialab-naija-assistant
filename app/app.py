"""Local Gradio interface for GaiaLab Naija Assistant."""

from __future__ import annotations

import logging
import os
from functools import lru_cache

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

DISCLAIMER = (
    "Experimental first version: responses may be inaccurate. Review important "
    "business, legal, tax, and financial information before acting on it."
)
LOGGER = logging.getLogger(__name__)
SYSTEM_PROMPTS = {
    "Nigerian English": (
        "You are GaiaLab Naija Assistant. Reply in clear, professional Nigerian "
        "English for a small-business owner. Be practical and do not invent facts."
    ),
    "Nigerian Pidgin": (
        "You be GaiaLab Naija Assistant. Reply with clear, respectful Nigerian "
        "Pidgin wey small-business owner go understand. No make up facts."
    ),
}


class ModelConfigurationError(RuntimeError):
    """Raised when local model configuration is absent or incompatible."""


class ModelGenerationError(RuntimeError):
    """Raised when the configured model cannot generate a response."""


def get_configured_model_id() -> str:
    model_id = os.getenv("GAIALAB_MODEL_ID", "").strip()
    if not model_id:
        raise ModelConfigurationError(
            "No model is configured. Set GAIALAB_MODEL_ID to a local model path "
            "or Hugging Face model ID, then restart the app."
        )
    return model_id


@lru_cache(maxsize=1)
def load_model(model_id: str):
    """Load one configured local or Hugging Face model per app process."""
    tokenizer = AutoTokenizer.from_pretrained(model_id, use_fast=True)
    # Preserve the latest user turn and generation prompt when context is truncated.
    tokenizer.truncation_side = "left"
    model = AutoModelForCausalLM.from_pretrained(
        model_id,
        device_map="auto" if torch.cuda.is_available() else None,
        # Transformers 5 uses `dtype`; `torch_dtype` is deprecated compatibility API.
        dtype="auto",
    )
    if tokenizer.pad_token_id is None:
        if tokenizer.eos_token_id is None:
            raise ModelConfigurationError(
                "The configured tokenizer has neither a pad token nor an EOS token."
            )
        tokenizer.pad_token_id = tokenizer.eos_token_id
    if not tokenizer.chat_template:
        raise ModelConfigurationError(
            "The configured tokenizer has no chat template. Choose a compatible "
            "instruction model."
        )
    model.eval()
    return tokenizer, model


def generate_response(message: str, mode: str, max_new_tokens: int = 192) -> str:
    """Generate one response or raise a typed, caller-safe error."""
    if not message.strip():
        raise ValueError("Please enter a message or business question.")
    if mode not in SYSTEM_PROMPTS:
        raise ValueError(f"Unsupported language mode: {mode}.")
    max_new_tokens = max(1, min(int(max_new_tokens), 512))
    model_id = get_configured_model_id()

    try:
        tokenizer, model = load_model(model_id)
        messages = [
            {"role": "system", "content": SYSTEM_PROMPTS[mode]},
            {"role": "user", "content": message.strip()},
        ]
        prompt = tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        context_window = int(getattr(model.config, "max_position_embeddings", 4096))
        max_input_tokens = max(1, context_window - max_new_tokens)
        inputs = tokenizer(
            prompt,
            return_tensors="pt",
            truncation=True,
            max_length=max_input_tokens,
        ).to(model.device)
        with torch.inference_mode():
            output = model.generate(
                **inputs,
                max_new_tokens=int(max_new_tokens),
                do_sample=True,
                temperature=0.7,
                top_p=0.9,
                repetition_penalty=1.05,
                pad_token_id=tokenizer.pad_token_id,
            )
        generated = output[0, inputs["input_ids"].shape[1] :]
        response = tokenizer.decode(generated, skip_special_tokens=True).strip()
        if not response:
            raise ModelGenerationError("The configured model returned an empty response.")
        return response
    except (ModelConfigurationError, ModelGenerationError):
        raise
    except Exception as exc:
        raise ModelGenerationError(
            "Generation failed. Check the model ID, local files, available memory, "
            "and internet connection."
        ) from exc


def respond(message: str, mode: str, max_new_tokens: int) -> str:
    """Gradio-safe wrapper that does not expose internal paths or credentials."""
    try:
        return generate_response(message, mode, max_new_tokens)
    except (ModelConfigurationError, ModelGenerationError, ValueError) as exc:
        LOGGER.warning("Assistant request failed: %s", exc)
        return f"Error: {exc}"


def build_demo():
    import gradio as gr

    with gr.Blocks(title="GaiaLab Naija Assistant") as demo:
        gr.Markdown("# GaiaLab Naija Assistant")
        gr.Markdown(
            "Free, local-first writing, terminology, and translation help for "
            "Nigerian small-business owners."
        )
        gr.Markdown(f"> **Disclaimer:** {DISCLAIMER}")
        with gr.Row():
            mode = gr.Radio(
                list(SYSTEM_PROMPTS), value="Nigerian English", label="Response mode"
            )
            max_tokens = gr.Slider(32, 512, value=192, step=16, label="Max new tokens")
        message = gr.Textbox(
            lines=6,
            label="Your request",
            placeholder=(
                "Example: Write a polite reply telling my customer their order "
                "will arrive tomorrow."
            ),
        )
        submit = gr.Button("Generate response", variant="primary")
        answer = gr.Textbox(lines=10, label="Assistant response")
        submit.click(respond, [message, mode, max_tokens], answer)
        message.submit(respond, [message, mode, max_tokens], answer)
    return demo


if __name__ == "__main__":
    build_demo().launch(server_name="127.0.0.1")
