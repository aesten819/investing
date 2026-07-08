# META SEC HTML Validation

Validation of stored META financial data against locally archived Meta SEC inline XBRL HTML filings.

Generated: 2026-07-04T20:04:16.243679Z

## Status Counts

- match: 464
- mismatch: 86
- missing_source: 23
- not_comparable: 13
- skipped: 25

## Core Metrics

- cash_and_equivalents: {'match': 13}
- current_investments: {'mismatch': 7, 'match': 6}
- investments: {'mismatch': 10, 'match': 3}
- net_cash_flow_from_operations: {'match': 13}
- capital_expenditure: {'match': 13}
- free_cash_flow: {'match': 13}
- current_debt: {'match': 13}
- non_current_debt: {'match': 13}
- total_debt: {'match': 13}
- revenue: {'match': 13}
- operating_income: {'match': 13}
- net_income: {'match': 26}

## Largest Mismatches

- 2026Q1 non_current_assets (mismatch): source=77,870,000,000, sec=285,485,000,000, diff=-207,615,000,000
- 2025Q3 non_current_assets (mismatch): source=55,230,000,000, sec=230,726,000,000, diff=-175,496,000,000
- 2025Q2 non_current_assets (mismatch): source=55,788,000,000, sec=221,131,000,000, diff=-165,343,000,000
- 2025Q1 non_current_assets (mismatch): source=51,550,000,000, sec=189,986,000,000, diff=-138,436,000,000
- 2024Q3 non_current_assets (mismatch): source=49,319,000,000, sec=165,341,000,000, diff=-116,022,000,000
- 2024Q2 non_current_assets (mismatch): source=45,681,000,000, sec=153,807,000,000, diff=-108,126,000,000
- 2024Q1 non_current_assets (mismatch): source=43,274,000,000, sec=147,514,000,000, diff=-104,240,000,000
- 2023Q3 non_current_assets (mismatch): source=40,041,000,000, sec=137,896,000,000, diff=-97,855,000,000
- 2023Q2 non_current_assets (mismatch): source=43,030,000,000, sec=137,128,000,000, diff=-94,098,000,000
- 2023Q1 non_current_assets (mismatch): source=41,703,000,000, sec=132,008,000,000, diff=-90,305,000,000
- 2026Q1 investment_acquisitions_and_disposals (mismatch): source=13,802,000,000, sec=-13,802,000,000, diff=27,604,000,000
- 2025Q4 property_plant_and_equipment (mismatch): source=196,804,000,000, sec=176,400,000,000, diff=20,404,000,000

## Files

- `validation_rows.csv` and `validation_rows.json`: metric-level comparisons.
- `summary.json`: aggregate counts and largest mismatches.

## Method

- Stored `META` data is checked against local SEC filing HTML files in `data/hyperscaler/ir_documents/originals/META/sec_filing_html`.
- Balance sheet metrics use no-dimension instant XBRL facts at each report period.
- Income statement and cash flow metrics use exact quarterly duration facts when available.
- When SEC filings only provide year-to-date cash flow or annual 10-K facts, quarter values are derived by subtracting the prior YTD period.
- `capital_expenditure` is normalized as a negative cash outflow for SEC comparison; `sign_mismatch` means the absolute amount matches but source sign differs.
- Money and share values allow a 1 million tolerance because SEC facts are usually rounded to millions.
