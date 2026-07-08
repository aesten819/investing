# GOOGL SEC HTML Validation

Validation of stored GOOGL financial data against locally archived GOOG SEC inline XBRL HTML filings.

Generated: 2026-07-04T19:42:42.253836Z

## Status Counts

- match: 413
- mismatch: 60
- missing_source: 10
- not_comparable: 4
- skipped: 20

## Core Metrics

- cash_and_equivalents: {'match': 13}
- current_investments: {'mismatch': 9, 'match': 4}
- net_cash_flow_from_operations: {'match': 13}
- capital_expenditure: {'match': 13}
- free_cash_flow: {'match': 13}
- current_debt: {'match': 13}
- non_current_debt: {'match': 13}
- total_debt: {'match': 13}
- revenue: {'match': 13}
- operating_income: {'match': 13}
- net_income: {'match': 13}

## Largest Mismatches

- 2026Q1 non_current_assets (mismatch): source=490,166,000,000, sec=296,529,000,000, diff=193,637,000,000
- 2025Q4 non_current_assets (mismatch): source=389,243,000,000, sec=261,818,000,000, diff=127,425,000,000
- 2025Q1 non_current_assets (mismatch): source=318,792,000,000, sec=198,784,000,000, diff=120,008,000,000
- 2026Q1 investments (mismatch): source=195,723,000,000, sec=88,777,000,000, diff=106,946,000,000
- 2024Q4 non_current_assets (mismatch): source=286,545,000,000, sec=184,624,000,000, diff=101,921,000,000
- 2024Q3 non_current_assets (mismatch): source=274,978,000,000, sec=174,831,000,000, diff=100,147,000,000
- 2025Q3 non_current_assets (mismatch): source=144,878,000,000, sec=238,311,000,000, diff=-93,433,000,000
- 2024Q2 non_current_assets (mismatch): source=255,151,000,000, sec=164,761,000,000, diff=90,390,000,000
- 2024Q1 non_current_assets (mismatch): source=245,279,000,000, sec=156,950,000,000, diff=88,329,000,000
- 2023Q4 non_current_assets (mismatch): source=230,862,000,000, sec=148,436,000,000, diff=82,426,000,000
- 2025Q2 non_current_assets (mismatch): source=138,373,000,000, sec=217,486,000,000, diff=-79,113,000,000
- 2025Q3 investments (mismatch): source=148,865,000,000, sec=75,406,000,000, diff=73,459,000,000

## Files

- `validation_rows.csv` and `validation_rows.json`: metric-level comparisons.
- `summary.json`: aggregate counts and largest mismatches.

## Method

- `GOOGL` stored data is checked against local `GOOG` SEC filing HTML files.
- Balance sheet metrics use no-dimension instant XBRL facts at each report period.
- Income statement and cash flow metrics use exact quarterly duration facts when available.
- When SEC filings only provide year-to-date cash flow or annual 10-K facts, quarter values are derived by subtracting the prior YTD period.
- `capital_expenditure` is normalized as a negative cash outflow for SEC comparison; `sign_mismatch` means the absolute amount matches but source sign differs.
- Money and share values allow a 1 million tolerance because SEC facts are usually rounded to millions.
