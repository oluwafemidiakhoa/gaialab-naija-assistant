from __future__ import annotations
import argparse, csv, json
from pathlib import Path

REQUIRED={"id","category","prompt","expected_behavior","risk_level","status"}

def load(path: Path):
    rows=[]; seen=set()
    for n,line in enumerate(path.read_text(encoding="utf-8").splitlines(),1):
        if not line.strip(): continue
        row=json.loads(line)
        missing=REQUIRED-row.keys()
        if missing: raise ValueError(f"Line {n} missing {sorted(missing)}")
        if row["id"] in seen: raise ValueError(f"Duplicate id {row['id']}")
        seen.add(row["id"]); rows.append(row)
    return rows

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--benchmark",default="evaluation/v0.4/benchmark_v0.4.jsonl")
    p.add_argument("--output",default="evaluation/v0.4/v0.3_baseline_review.csv")
    a=p.parse_args()
    rows=load(Path(a.benchmark))
    fields=["id","category","prompt","expected_behavior","risk_level","model_version","model_response","instruction_following","factual_consistency","tone","clarity","safety","hallucination","pass","reviewer_notes"]
    out=Path(a.output); out.parent.mkdir(parents=True,exist_ok=True)
    with out.open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader()
        for r in rows:
            w.writerow({**{k:r[k] for k in ["id","category","prompt","expected_behavior","risk_level"]},**{k:"" for k in fields[5:]}})
    print(f"Prompts: {len(rows)}")
    print(f"Review sheet: {out}")

if __name__=="__main__":
    main()
