import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PREPARED_DIR = PROJECT_ROOT / "data" / "v0.2" / "prepared"

COMBINED_PATH = PREPARED_DIR / "gaialab_naija_v0.2_combined.jsonl"
TRAIN_PATH = PREPARED_DIR / "gaialab_naija_v0.2_train.jsonl"
VALIDATION_PATH = PREPARED_DIR / "gaialab_naija_v0.2_validation.jsonl"


def load_jsonl(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as file:
        return [
            json.loads(line)
            for line in file
            if line.strip()
        ]


def test_prepared_files_exist():
    assert COMBINED_PATH.exists()
    assert TRAIN_PATH.exists()
    assert VALIDATION_PATH.exists()


def test_prepared_record_counts():
    combined = load_jsonl(COMBINED_PATH)
    train = load_jsonl(TRAIN_PATH)
    validation = load_jsonl(VALIDATION_PATH)

    assert len(combined) == 200
    assert len(train) == 180
    assert len(validation) == 20


def test_train_and_validation_do_not_overlap():
    train = load_jsonl(TRAIN_PATH)
    validation = load_jsonl(VALIDATION_PATH)

    train_ids = {record["id"] for record in train}
    validation_ids = {record["id"] for record in validation}

    assert train_ids.isdisjoint(validation_ids)


def test_split_reconstructs_combined_dataset():
    combined = load_jsonl(COMBINED_PATH)
    train = load_jsonl(TRAIN_PATH)
    validation = load_jsonl(VALIDATION_PATH)

    combined_ids = {record["id"] for record in combined}
    split_ids = {
        record["id"]
        for record in train + validation
    }

    assert combined_ids == split_ids


def test_all_prepared_ids_are_unique():
    combined = load_jsonl(COMBINED_PATH)
    ids = [record["id"] for record in combined]

    assert len(ids) == len(set(ids))


def test_expected_id_range_is_present():
    combined = load_jsonl(COMBINED_PATH)
    actual_ids = {record["id"] for record in combined}

    expected_ids = {
        f"en_pcm_{number:03d}"
        for number in range(1, 201)
    }

    assert actual_ids == expected_ids