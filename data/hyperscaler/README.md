# Hyperscaler Financial Dataset

Quarterly income statement, balance sheet, and cash flow dataset for MSFT, AMZN, GOOGL, META, ORCL.

Requested range: latest 13 quarters per company.

Available range in the current dataset:

- MSFT: 13 quarters
- AMZN: 13 quarters
- GOOGL: 13 quarters
- META: 13 quarters
- ORCL: 12 quarters

## Update Policy

- Future refreshes should use each company's official IR/SEC documents only.
- `scripts/fetch_hyperscaler_data.py` is a legacy bootstrap importer and is disabled unless explicitly run with `--allow-financialdatasets`.
- Existing `source/financials/<TICKER>.json` files are retained as legacy audit/backfill history, not as the preferred source for future updates.

## Layout

- `panel/quarterly_hyperscaler_financials.csv`: one row per company and calendar quarter.
- `panel/quarterly_hyperscaler_financials.json`: same panel data as JSON.
- `companies/<TICKER>.csv`: company-specific time series.
- `metrics/<metric>.csv`: metric-specific pivot table with calendar quarters in rows and tickers in columns.
- `source/financials/<TICKER>.json`: legacy raw aggregated `/financials` response retained for audit/backfill history.
- `source/income_statements/<TICKER>.*`: income statement records used to build the panel.
- `source/balance_sheets/<TICKER>.*`: balance sheet records used to build the panel.
- `source/cash_flow_statements/<TICKER>.*`: cash flow records used to build the panel.
- `metadata.json`: run metadata, field lists, and actual quarter counts.

## Adjustments

- AMZN historical `capital_expenditure` values missing from the legacy bootstrap source are filled from SEC companyfacts tag `PaymentsToAcquireProductiveAssets`.
- AMZN Q4 `capital_expenditure` values are patched from locally archived SEC inline XBRL HTML when the legacy source value differs from the annual SEC value less Q1-Q3.
- AMZN `current_debt`, `non_current_debt`, and `total_debt` use pure financial debt from SEC inline XBRL when available: short-term borrowings, current/noncurrent long-term debt, and finance lease liabilities. Operating lease liabilities and Amazon financing obligations are excluded.
- GOOGL `capital_expenditure` values are sign-normalized from locally archived GOOG SEC inline XBRL HTML when available, using the SEC cash outflow convention.
- GOOGL `current_debt`, `non_current_debt`, and `total_debt` use pure financial debt from locally archived GOOG SEC inline XBRL HTML when available: short-term borrowings, current/noncurrent long-term debt, and finance lease liabilities. Operating lease liabilities are excluded.
- META `capital_expenditure` values are sign-normalized from locally archived SEC inline XBRL HTML when available, using the SEC cash outflow convention.
- META `current_debt`, `non_current_debt`, and `total_debt` use pure financial debt from locally archived SEC inline XBRL HTML when available: short-term borrowings, current/noncurrent long-term debt, and finance lease liabilities. Operating lease liabilities are excluded.
- MSFT comparable income statement, balance sheet, and cash flow fields are patched from locally archived Microsoft `FinancialStatement*.xlsx` files when available. Microsoft fiscal quarters are mapped to calendar quarters by `report_period` (for example, FY23Q3 maps to 2023Q1).
- MSFT `capital_expenditure` values are sign-normalized from the FinancialStatement XLSX cash flow line `Additions to property and equipment`.
- MSFT `current_debt`, `non_current_debt`, and `total_debt` use pure financial debt from FinancialStatement XLSX: current portion of long-term debt plus long-term debt. Operating lease liabilities are excluded.
- ORCL comparable income statement, balance sheet, and cash flow fields are patched from locally archived Oracle official financial table XLSX files when available. Oracle fiscal quarters are mapped to calendar quarters by `report_period` (for example, fiscal 2026-Q3 maps to 2026Q1).
- ORCL `capital_expenditure` values are sign-normalized from the Oracle financial table XLSX cash flow line `Capital expenditures`.
- ORCL `current_debt`, `non_current_debt`, and `total_debt` use pure financial debt from Oracle financial table XLSX: notes payable and other borrowings, current plus non-current. Operating lease liabilities are excluded.
- SEC companyfacts are used to identify tickers whose interim cash flow statements are fiscal YTD values; those Q2/Q3 flow fields are differenced to quarterly values.
- `free_cash_flow` is recalculated as `net_cash_flow_from_operations - abs(capital_expenditure)` when a source value is missing or inconsistent.
- Original legacy/source FCF values are kept in `free_cash_flow_reported`.
- Legacy Financial Datasets responses remain in `source/financials/<TICKER>.json` for audit/backfill history only.
- Adjusted source rows include audit fields such as `cash_flow_normalization`, `capex_source`, `capex_sec_accession_number`, `capex_sec_filed`, `capex_sec_frame`, `capex_sec_filing_url`, `debt_source`, `debt_definition`, `debt_sec_accession_number`, `debt_sec_filed`, `debt_sec_filing_url`, and `fcf_source` in `source/*/<TICKER>.*`.
