# GaiaLab Naija Dataset v0.1

`gaialab_naija_v0.1.jsonl` contains exactly 100 original draft examples written for
this repository. The file is an early, openly licensed development dataset, not a
production corpus. No model has been trained or evaluated on it in this repository.

Every record has the string fields `instruction`, `input`, `output`, `language`,
`category`, `source`, and `license`. All records use source `GaiaLab original draft
— pending Nigerian human review` and licence `CC0-1.0`. The source label is an
important limitation: the wording aims to be natural, but Nigerian speakers and
small-business owners have not yet completed a documented review.

The category distribution is fixed for v0.1:

| Category | Records |
| --- | ---: |
| `customer_service` | 25 |
| `terminology` | 20 |
| `translation_en_to_pidgin` | 20 |
| `translation_pidgin_to_en` | 15 |
| `business_writing` | 20 |
| **Total** | **100** |

Do not add scraped private conversations, personal information, or material without
documented permission and a compatible licence. Run the validator before accepting
new data:

```bash
python -m src.validate_dataset data/gaialab_naija_v0.1.jsonl
```

Validation creates deterministic 80/20 train and validation splits in
`prepared_data/` by default. Generated splits are ignored by Git and must retain the
same provenance and licence if redistributed.
