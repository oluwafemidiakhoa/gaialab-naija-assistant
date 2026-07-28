import json

from src.dataset_management import example_sha256
from src.release_scorecard import generate_scorecard, public_scorecard
from src.training_eligibility import assess_eligibility


def test_scorecard_calculations_and_privacy(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}\n")
    rows = []
    for status in ("approved", "draft"):
        row = {
            "id": f"v06-{status}", "dataset_version": "v0.6", "revision": 1,
            "category": "business_writing", "risk_level": "low",
            "source": "synthetic", "license": "CC0-1.0",
            "review_status": status, "technical_review_completed": status == "approved",
            "messages": [
                {"role": "system", "content": "Help."},
                {"role": "user", "content": f"Prompt {status}"},
                {"role": "assistant", "content": "Reply."},
            ],
        }
        row["example_sha256"] = example_sha256(row)
        rows.append(row)
    decisions = [assess_eligibility(r, "v0.6") for r in rows]
    card = generate_scorecard(
        "v0.6", rows, manifest, decisions=decisions,
        assessments=[{"overall_score": 70, "findings": []}, {"overall_score": 90, "findings": []}],
        generated_at=lambda: "2026-01-01T00:00:00+00:00",
    )
    assert card["record_count"] == 2
    assert card["approved_count"] == 1
    assert card["average_quality_score"] == 80
    assert len(card["scorecard_sha256"]) == 64
    card["reviewer_identifier"] = "private"
    assert "reviewer_identifier" not in public_scorecard(card)
    json.dumps(public_scorecard(card))
