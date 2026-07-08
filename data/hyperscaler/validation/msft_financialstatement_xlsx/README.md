# MSFT FinancialStatement XLSX Validation

Validation of stored MSFT financial data against locally archived Microsoft `FinancialStatement*.xlsx` files.

Generated: 2026-07-04T20:20:32.015828Z

## Period Mapping

Microsoft fiscal quarters are mapped to calendar quarter labels by report date. Example: `FY23Q3` is fiscal period `2023-Q3`, report period `2023-03-31`, and dataset quarter `2023Q1`.

## Status Counts

- match: 663
- not_comparable: 78

## Core Metrics

- cash_and_equivalents: {'match': 13}
- current_investments: {'match': 13}
- investments: {'not_comparable': 13}
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

- None

## Files

- `validation_rows.csv` and `validation_rows.json`: metric-level comparisons.
- `summary.json`: aggregate counts and largest mismatches.
