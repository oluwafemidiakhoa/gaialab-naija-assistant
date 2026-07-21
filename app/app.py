"""Local Gradio interface for GaiaLab Naija Assistant."""

from __future__ import annotations

import os
from functools import lru_cache

import gradio as gr
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

DISCLAIMER = (
    "Experimental first version: responses may be inaccurate. Review important "
    "business, legal, tax, and financial information before acting on it."
)
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


@lru_cache(maxsize=1)
def load_model(model_id: str):
    """Load one configured local or Hugging Face model per app process."""
    tokenizer = AutoTokenizer.from_pretrained(model_id, use_fast=True)
    model = AutoModelForCausalLM.from_pretrained(
        model_id,
        device_map="auto" if torch.cuda.is_available() else None,
        torch_dtype="auto",
    )
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token_id = tokenizer.eos_token_id
    return tokenizer, model


def respond(message: str, mode: str, max_new_tokens: int) -> str:
    model_id = os.getenv("GAIALAB_MODEL_ID", "").strip()
    if not model_id:
        return (
            "Configuration error: no model is configured. Set GAIALAB_MODEL_ID "
            "to a local model path or Hugging Face model ID, then restart the app."
        )
    if not message.strip():
        return "Please enter a message or business question."

    try:
        tokenizer, model = load_model(model_id)
        messages = [
            {"role": "system", "content": SYSTEM_PROMPTS[mode]},
            {"role": "user", "content": message.strip()},
        ]
        prompt = tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
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
        return response or "The configured model returned an empty response."
    except KeyError:
        return f"Unsupported language mode: {mode}."
    except Exception as exc:  # Gradio should show a friendly error, not a traceback.
        return f"Model error: {type(exc).__name__}: {exc}"


def build_demo() -> gr.Blocks:
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
