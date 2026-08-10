"""Run the synthetic GaiaLab Naija fintech trust benchmark."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.trust_api import verify_payload


def load_cases(path: Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                cases.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL at line {line_number}: {exc}") from exc
    return cases


def evaluate_case(case: dict[str, Any]) -> dict[str, Any]:
    result = verify_payload(case)
    claim_checks = result["claim_reconciliation"]["checks"]
    observed_claim_status = claim_checks[0]["status"] if claim_checks else None
    passed = (
        result["disposition"] == case["expected_disposition"]
        and observed_claim_status == case.get("expected_claim_status")
    )
    return {
        "id": case["id"],
        "passed": passed,
        "expected_disposition": case["expected_disposition"],
        "observed_disposition": result["disposition"],
        "expected_claim_status": case.get("expected_claim_status"),
        "observed_claim_status": observed_claim_status,
        "risk_score": result["risk_score"],
        "verification_id": result["verification_receipt"]["verification_id"],
    }


def run(path: Path) -> dict[str, Any]:
    cases = load_cases(path)
    results = [evaluate_case(case) for case in cases]
    passed = sum(item["passed"] for item in results)
    return {
        "benchmark": path.name,
        "synthetic": True,
        "total": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "exact_match_rate": (passed / len(results)) if results else 0.0,
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fixture",
        type=Path,
        default=ROOT / "evaluation" / "fixtures" / "naija_fintech_trust_v0.1.jsonl",
    )
    parser.add_argument("--json", action="store_true", help="Print the full JSON report.")
    args = parser.parse_args()

    report = run(args.fixture)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(
            f"{report['benchmark']}: {report['passed']}/{report['total']} passed "
            f"({report['exact_match_rate']:.1%})"
        )
        for item in report["results"]:
            marker = "PASS" if item["passed"] else "FAIL"
            print(
                f"[{marker}] {item['id']}: disposition "
                f"{item['observed_disposition']} (expected {item['expected_disposition']}), "
                f"claim {item['observed_claim_status']} (expected {item['expected_claim_status']})"
            )
    return 0 if report["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
