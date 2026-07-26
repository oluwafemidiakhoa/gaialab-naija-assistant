
from __future__ import annotations

import argparse
import csv
import json
import torch
from pathlib import Path
from transformers import AutoModelForCausalLM, AutoTokenizer
from peft import PeftModel

SYSTEM_PROMPT = (
    "You are GaiaLab Naija Assistant. "
    "Follow the user's facts exactly. "
    "Do not invent details that were not requested."
)

def load_benchmark(path: Path):
    records = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                records.append(json.loads(line))
    return records

def load_model(base_model: str, adapter_path: str):
    tokenizer = AutoTokenizer.from_pretrained(adapter_path)
    base = AutoModelForCausalLM.from_pretrained(
        base_model,
        device_map="auto",
        torch_dtype="auto",
    )
    model = PeftModel.from_pretrained(base, adapter_path)
    model.eval()
    return model, tokenizer

def generate(model, tokenizer, prompt: str):
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]
    text = tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=True,
    )
    inputs = tokenizer(text, return_tensors="pt").to(model.device)
    with torch.no_grad():
        out = model.generate(
            **inputs,
            max_new_tokens=160,
            do_sample=False,
            repetition_penalty=1.1,
            pad_token_id=tokenizer.eos_token_id,
        )
    return tokenizer.decode(
        out[0][inputs["input_ids"].shape[1]:],
        skip_special_tokens=True,
    ).strip()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--benchmark", default="evaluation/v0.4/benchmark_v0.4.jsonl")
    ap.add_argument("--adapter", required=True,
                    help="Path to trained adapter folder")
    ap.add_argument("--base-model",
                    default="Qwen/Qwen2.5-0.5B-Instruct")
    ap.add_argument("--model-version", default="v0.3")
    ap.add_argument("--output",
                    default="evaluation/v0.4/v0.3_baseline_review.csv")
    args = ap.parse_args()

    records = load_benchmark(Path(args.benchmark))
    model, tokenizer = load_model(args.base_model, args.adapter)

    fields = [
        "id","category","prompt","expected_behavior","risk_level",
        "model_version","model_response",
        "instruction_following","factual_consistency",
        "tone","clarity","safety",
        "hallucination","pass","reviewer_notes"
    ]

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()

        for i, rec in enumerate(records, start=1):
            print(f"[{i}/{len(records)}] {rec['id']}")
            response = generate(model, tokenizer, rec["prompt"])
            writer.writerow({
                "id": rec["id"],
                "category": rec["category"],
                "prompt": rec["prompt"],
                "expected_behavior": rec["expected_behavior"],
                "risk_level": rec["risk_level"],
                "model_version": args.model_version,
                "model_response": response,
                "instruction_following": "",
                "factual_consistency": "",
                "tone": "",
                "clarity": "",
                "safety": "",
                "hallucination": "",
                "pass": "",
                "reviewer_notes": "",
            })

    print(f"\nSaved review sheet to: {out_path}")

if __name__ == "__main__":
    main()
