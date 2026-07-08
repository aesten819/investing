# Hyperscaler Data Update Policy

Future financial data refreshes must use official company source documents only:

- Company investor relations pages and original downloadable financial tables, earnings releases, 10-Q, and 10-K files.
- SEC filing HTML/XBRL only when it is the official filing source for the company document.
- Locally archived originals under `data/hyperscaler/ir_documents/originals/<TICKER>/`.

Do not use `financialdatasets.ai` for new data refreshes.

`scripts/fetch_hyperscaler_data.py` is retained only as a legacy bootstrap importer. It is disabled by default and requires `--allow-financialdatasets` for historical/backfill recovery work.

Existing `data/hyperscaler/source/financials/<TICKER>.json` files are legacy audit/backfill records. They should not be treated as the preferred source for future updates.
