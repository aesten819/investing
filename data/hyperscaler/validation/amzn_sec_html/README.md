# AMZN SEC HTML Validation

Validation of stored AMZN financial data against locally archived SEC inline XBRL HTML filings.

Generated: 2026-07-04T19:26:06.151588Z

## Status Counts

- match: 448
- mismatch: 27
- missing_source: 20
- skipped: 12

## Largest Mismatches

- 2024Q3 total_liabilities: source=332,475,000,000, sec=325,475,000,000, diff=7,000,000,000
- 2024Q2 total_liabilities: source=325,071,000,000, sec=318,371,000,000, diff=6,700,000,000
- 2024Q1 total_liabilities: source=320,708,000,000, sec=314,308,000,000, diff=6,400,000,000
- 2025Q1 total_liabilities: source=342,289,000,000, sec=337,389,000,000, diff=4,900,000,000
- 2026Q1 total_liabilities: source=479,116,000,000, sec=474,716,000,000, diff=4,400,000,000
- 2025Q2 total_liabilities: source=352,695,000,000, sec=348,395,000,000, diff=4,300,000,000
- 2025Q3 total_liabilities: source=362,390,000,000, sec=358,290,000,000, diff=4,100,000,000
- 2023Q1 total_liabilities: source=312,652,000,000, sec=309,852,000,000, diff=2,800,000,000
- 2023Q2 total_liabilities: source=311,705,000,000, sec=309,005,000,000, diff=2,700,000,000
- 2023Q3 total_liabilities: source=306,610,000,000, sec=303,910,000,000, diff=2,700,000,000

## Files

- `validation_rows.csv` and `validation_rows.json`: metric-level comparisons.
- `summary.json`: aggregate counts and largest mismatches.

## Method

- Balance sheet metrics use no-dimension instant XBRL facts at each report period.
- Income statement and cash flow metrics use exact quarterly duration facts when available.
- When SEC filings only provide year-to-date cash flow or annual 10-K facts, quarter values are derived by subtracting the prior YTD period.
- Money and share values allow a 1 million tolerance because Amazon reports most SEC facts rounded to millions.
