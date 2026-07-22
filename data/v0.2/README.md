# GaiaLab Naija English-to-Pidgin Draft v0.2

`english_to_pidgin_100.jsonl` contains 100 original English-to-Nigerian-Pidgin
translation drafts for Nigerian business and everyday communication. These records
have not been culturally validated. They are pending independent review by Nigerian
Pidgin speakers and small-business owners.

Each JSONL record contains `id`, `category`, `instruction`, `input`, `output`,
`language`, `source`, and `license`. The last three fields extend the requested
translation schema to preserve the repository's language and provenance contract.
All records are original GaiaLab drafts released under `CC0-1.0`; they contain no
scraped conversations or licensed third-party text.

The file contains exactly 10 records in each category:

- `delivery_and_logistics`
- `payments_and_refunds`
- `orders_and_inventory`
- `customer_complaints`
- `appointments_and_scheduling`
- `banking_and_mobile_payments`
- `market_and_retail_conversations`
- `small_business_communication`
- `agriculture_and_food_sales`
- `general_everyday_communication`

The records were authored in five consecutive batches of 20 (`en_pcm_001` through
`en_pcm_100`). Names, contact details, order references, and addresses are synthetic
examples and do not represent customer data.

Validate the file without retaining generated split files:

```bash
python -m src.validate_dataset \
  data/v0.2/english_to_pidgin_100.jsonl \
  --output-dir /tmp/gaialab-v02-validation
```

Automated tests check the schema, ID sequence, category distribution, uniqueness,
and exact preservation of numeric expressions. Naturalness, business tone, tense,
negation, and meaning still require independent human review before approval or
training use.
