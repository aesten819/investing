# ORCL Financial Tables XLSX Validation

Validation of stored ORCL financial data against locally archived Oracle official `financial_tables_xlsx` files.

Generated: 2026-07-05T12:43:13.680121Z

## Period Mapping

Oracle fiscal quarters are mapped to calendar quarter labels by report date. Example: fiscal `2026-Q3` maps to report period `2026-02-28` and dataset quarter `2026Q1`.

## Status Counts

- match: 574
- missing_xlsx: 14
- not_comparable: 132

## Core Metrics

- cash_and_equivalents: {'match': 12}
- current_investments: {'match': 12}
- net_cash_flow_from_operations: {'missing_xlsx': 1, 'match': 11}
- capital_expenditure: {'missing_xlsx': 1, 'match': 11}
- free_cash_flow: {'missing_xlsx': 1, 'match': 11}
- current_debt: {'match': 12}
- non_current_debt: {'match': 12}
- total_debt: {'match': 12}
- revenue: {'match': 12}
- operating_income: {'match': 12}
- net_income: {'match': 24}

## Largest Mismatches

- None

## Files

- `validation_rows.csv` and `validation_rows.json`: metric-level comparisons.
- `summary.json`: aggregate counts and largest mismatches.
