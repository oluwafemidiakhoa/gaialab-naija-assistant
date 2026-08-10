"""Run synthetic Nigerian English/Pidgin claim extraction benchmarks."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.claim_extraction import extract_claims


DEFAULT_FIXTURE = ROOT / "evaluation" / "fixtures" / "naija_pidgin_claim_extraction_v0.1.jsonl"


def load_cases(path: Path) -> list[dict[str, Any]]:
    cases = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            cases.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSONL at line {line_number}: {exc}") from exc
    return cases


def _normalized_conflicts(items: list[dict[str, Any]]) -> dict[str, list[Any]]:
    return {
        item["field"]: sorted(item["values"], key=str)
        for item in items
    }


def evaluate_case(case: dict[str, Any]) -> dict[str, Any]:
    result = extract_claims(case["assistant_response"])
    expected_conflicts = {
        field: sorted(values, key=str)
        for field, values in (case.get("expected_conflicts") or {}).items()
    }
    observed_conflicts = _normalized_conflicts(result["conflicts"])
    passed = (
        result["claims"] == case["expected_claims"]
        and observed_conflicts == expected_conflicts
        and result["required_disposition"] == case["expected_required_disposition"]
    )
    return {
        "id": case["id"],
        "language": case["language"],
        "passed": passed,
        "expected_claims": case["expected_claims"],
        "observed_claims": result["claims"],
        "expected_conflicts": expected_conflicts,
        "observed_conflicts": observed_conflicts,
        "expected_required_disposition": case["expected_required_disposition"],
        "observed_required_disposition": result["required_disposition"],
    }


def run(path: Path) -> dict[str, Any]:
    cases = load_cases(path)
    if any(case.get("synthetic") is not True for case in cases):
        raise ValueError("benchmark currently accepts synthetic cases only")
    results = [evaluate_case(case) for case in cases]
    passed = sum(item["passed"] for item in results)
    return {
        "benchmark": path.name,
        "synthetic": True,
        "culturally_validated": all(case.get("culturally_validated") is True for case in cases),
        "total": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "exact_match_rate": passed / len(results) if results else 0.0,
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = run(args.fixture)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        validation = "validated" if report["culturally_validated"] else "not culturally validated"
        print(
            f"{report['benchmark']}: {report['passed']}/{report['total']} passed "
            f"({report['exact_match_rate']:.1%}); synthetic; {validation}"
        )
        for item in report["results"]:
            marker = "PASS" if item["passed"] else "FAIL"
            print(f"[{marker}] {item['id']} ({item['language']})")
    return 0 if report["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
