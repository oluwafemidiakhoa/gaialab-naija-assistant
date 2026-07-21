# Demonstration data

`sample_training_data.jsonl` contains exactly 20 small, original demonstration
examples written for this repository. They are examples of the required schema and
pipeline only; they are not a production training corpus and have not been used to
train or evaluate a released model.

Each record has `instruction`, `input`, `output`, `language`, `category`, `source`,
and `license` fields. The examples cover Nigerian English, Nigerian Pidgin, customer
service, small-business terminology, and translation. Every example is marked as an
original synthetic demonstration and dedicated under CC0-1.0.

Do not add scraped private conversations, personal information, or material without
documented permission and a compatible licence. Run the validator before accepting
new data:

```bash
python -m src.validate_dataset data/sample_training_data.jsonl
```
