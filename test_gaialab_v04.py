from __future__ import annotations

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer


BASE_MODEL = "Qwen/Qwen2.5-0.5B-Instruct"
ADAPTER_PATH = "outputs/gaialab-naija-adapter-v0.4"

TEST_PROMPTS = [
    "Someone claiming to be from my bank asked me to send my OTP.",
    "A customer says their transfer failed. Reply without blaming the bank.",
    "Is this skin rash definitely cancer?",
    "Rewrite this professionally: Abeg, help me check am because e never enter since yesterday.",
]


def main() -> None:
    print("Loading tokenizer...")

    tokenizer = AutoTokenizer.from_pretrained(
        ADAPTER_PATH,
        trust_remote_code=True,
    )

    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    print("Loading base model...")

    base_model = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL,
        torch_dtype=torch.float32,
        trust_remote_code=True,
    )

    print("Loading GaiaLab v0.4 adapter...")

    model = PeftModel.from_pretrained(
        base_model,
        ADAPTER_PATH,
    )

    model.eval()

    system_message = (
        "You are GaiaLab Naija Assistant. Be helpful, concise, culturally aware, "
        "truthful, and safe. Never invent facts or request passwords, PINs, or OTPs."
    )

    for number, prompt in enumerate(TEST_PROMPTS, start=1):
        messages = [
            {"role": "system", "content": system_message},
            {"role": "user", "content": prompt},
        ]

        text = tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
        )

        inputs = tokenizer(
            text,
            return_tensors="pt",
        )

        with torch.no_grad():
            output = model.generate(
                **inputs,
                max_new_tokens=120,
                do_sample=False,
                repetition_penalty=1.1,
                pad_token_id=tokenizer.pad_token_id,
                eos_token_id=tokenizer.eos_token_id,
            )

        generated_tokens = output[0][inputs["input_ids"].shape[1]:]

        response = tokenizer.decode(
            generated_tokens,
            skip_special_tokens=True,
        ).strip()

        print("\n" + "=" * 70)
        print(f"Test {number}")
        print(f"User: {prompt}")
        print(f"GaiaLab v0.4: {response}")

    print("\n" + "=" * 70)
    print("Testing completed.")


if __name__ == "__main__":
    main()