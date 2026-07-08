#!/usr/bin/env python3
"""Patch MSFT derived financial data from archived Microsoft FinancialStatement XLSX files."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from fetch_hyperscaler_data import (
    BALANCE_SHEET_FIELDS,
    CASH_FLOW_FIELDS,
    INCOME_STATEMENT_FIELDS,
    SOURCE_AUDIT_FIELDS,
    SOURCE_IDENTITY_FIELDS,
    build_panel,
    export_dataset,
    write_csv,
    write_json,
)
from validate_msft_financials_against_xlsx import (
    BALANCE_METRICS,
    CASH_FLOW_METRICS,
    INCOME_METRICS,
    TICKER,
    load_xlsx_financials_by_fiscal_period,
)

DEFAULT_DATA_DIR = Path("data/hyperscaler")
DEFAULT_XLSX_DIR = Path("data/hyperscaler/ir_documents/originals/MSFT")

DEBT_DEFINITION = "pure_financial_debt: current portion of long-term debt + long-term debt; excludes operating lease liabilities"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_statement_rows(data_dir: Path, statement: str) -> dict[str, list[dict[str, Any]]]:
    rows_by_ticker: dict[str, list[dict[str, Any]]] = {}
    for path in sorted((data_dir / "source" / statement).glob("*.json")):
        rows_by_ticker[path.stem] = read_json(path)
    return rows_by_ticker


def load_tickers(data_dir: Path, statement_rows: dict[str, list[dict[str, Any]]]) -> list[str]:
    metadata_path = data_dir / "metadata.json"
    if metadata_path.exists():
        metadata = read_json(metadata_path)
        tickers = metadata.get("tickers")
        if isinstance(tickers, list) and tickers:
            return [str(ticker) for ticker in tickers]
    return sorted(statement_rows)


def numeric_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def value_changed(current: Any, replacement: float) -> bool:
    current_value = numeric_or_none(current)
    return current_value is None or current_value != replacement


def patch_fields_from_xlsx(
    rows: list[dict[str, Any]],
    xlsx_by_fiscal_period: dict[str, dict[str, Any]],
    fields: list[str],
) -> tuple[int, int]:
    rows_touched = 0
    value_patched = 0

    for row in rows:
        if row.get("ticker") != TICKER:
            continue
        xlsx_info = xlsx_by_fiscal_period.get(row.get("fiscal_period", ""))
        if xlsx_info is None:
            continue

        changed_on_row = False
        metrics = xlsx_info["metrics"]
        for field in fields:
            metric = metrics.get(field)
            if metric is None or metric.value is None:
                continue
            if value_changed(row.get(field), metric.value):
                value_patched += 1
                changed_on_row = True
            row[field] = metric.value

        if changed_on_row:
            rows_touched += 1

    return rows_touched, value_patched


def annotate_msft_debt(
    balance_rows: list[dict[str, Any]],
    xlsx_by_fiscal_period: dict[str, dict[str, Any]],
) -> int:
    rows_touched = 0
    for row in balance_rows:
        if row.get("ticker") != TICKER:
            continue
        xlsx_info = xlsx_by_fiscal_period.get(row.get("fiscal_period", ""))
        if xlsx_info is None:
            continue
        row["debt_source"] = "msft_financialstatement_xlsx:pure_financial_debt"
        row["debt_definition"] = DEBT_DEFINITION
        row["debt_sec_accession_number"] = ""
        row["debt_sec_filed"] = ""
        row["debt_sec_filing_url"] = xlsx_info["path"]
        rows_touched += 1
    return rows_touched


def annotate_msft_capex(
    cash_rows: list[dict[str, Any]],
    xlsx_by_fiscal_period: dict[str, dict[str, Any]],
) -> int:
    rows_touched = 0
    for row in cash_rows:
        if row.get("ticker") != TICKER:
            continue
        xlsx_info = xlsx_by_fiscal_period.get(row.get("fiscal_period", ""))
        if xlsx_info is None:
            continue
        if "free_cash_flow_reported" not in row:
            row["free_cash_flow_reported"] = row.get("free_cash_flow")
        row["capex_source"] = "msft_financialstatement_xlsx:AdditionsToPropertyAndEquipment"
        row["capex_sec_accession_number"] = ""
        row["capex_sec_filed"] = ""
        row["capex_sec_frame"] = "quarterly FinancialStatement XLSX"
        row["capex_sec_filing_url"] = xlsx_info["path"]
        row["fcf_source"] = "calculated:net_cash_flow_from_operations_minus_abs_capital_expenditure"
        rows_touched += 1
    return rows_touched


def patchable_fields(metric_defs: list[Any]) -> list[str]:
    return [metric.metric for metric in metric_defs if metric.comparable]


def write_msft_source_files(
    data_dir: Path,
    balance_rows: list[dict[str, Any]],
    cash_rows: list[dict[str, Any]],
    income_rows: list[dict[str, Any]],
) -> None:
    write_json(data_dir / "source" / "balance_sheets" / f"{TICKER}.json", balance_rows)
    write_json(data_dir / "source" / "cash_flow_statements" / f"{TICKER}.json", cash_rows)
    write_json(data_dir / "source" / "income_statements" / f"{TICKER}.json", income_rows)
    write_csv(
        data_dir / "source" / "balance_sheets" / f"{TICKER}.csv",
        balance_rows,
        SOURCE_IDENTITY_FIELDS + BALANCE_SHEET_FIELDS + SOURCE_AUDIT_FIELDS,
    )
    write_csv(
        data_dir / "source" / "cash_flow_statements" / f"{TICKER}.csv",
        cash_rows,
        SOURCE_IDENTITY_FIELDS + CASH_FLOW_FIELDS + SOURCE_AUDIT_FIELDS,
    )
    write_csv(
        data_dir / "source" / "income_statements" / f"{TICKER}.csv",
        income_rows,
        SOURCE_IDENTITY_FIELDS + INCOME_STATEMENT_FIELDS + SOURCE_AUDIT_FIELDS,
    )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--xlsx-dir", type=Path, default=DEFAULT_XLSX_DIR)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    xlsx_by_fiscal_period = load_xlsx_financials_by_fiscal_period(args.xlsx_dir)
    if not xlsx_by_fiscal_period:
        print(f"No Microsoft FinancialStatement XLSX files found in {args.xlsx_dir}", file=sys.stderr)
        return 1

    balance_sheets = load_statement_rows(args.data_dir, "balance_sheets")
    cash_flows = load_statement_rows(args.data_dir, "cash_flow_statements")
    income_statements = load_statement_rows(args.data_dir, "income_statements")
    tickers = load_tickers(args.data_dir, balance_sheets)

    balance_rows = balance_sheets.get(TICKER, [])
    cash_rows = cash_flows.get(TICKER, [])
    income_rows = income_statements.get(TICKER, [])

    balance_touched, balance_changes = patch_fields_from_xlsx(balance_rows, xlsx_by_fiscal_period, patchable_fields(BALANCE_METRICS))
    cash_touched, cash_changes = patch_fields_from_xlsx(cash_rows, xlsx_by_fiscal_period, patchable_fields(CASH_FLOW_METRICS))
    income_touched, income_changes = patch_fields_from_xlsx(income_rows, xlsx_by_fiscal_period, patchable_fields(INCOME_METRICS))
    debt_annotated = annotate_msft_debt(balance_rows, xlsx_by_fiscal_period)
    capex_annotated = annotate_msft_capex(cash_rows, xlsx_by_fiscal_period)

    write_msft_source_files(args.data_dir, balance_rows, cash_rows, income_rows)

    limit = max(len(rows) for rows in balance_sheets.values())
    rows = build_panel(balance_sheets, cash_flows, income_statements, tickers, limit=limit)
    export_dataset(rows, args.data_dir, tickers, quarters_per_company=limit)

    print(f"Patched MSFT balance rows from FinancialStatement XLSX: {balance_touched} rows, {balance_changes} value changes; debt annotations {debt_annotated}")
    print(f"Patched MSFT cash flow rows from FinancialStatement XLSX: {cash_touched} rows, {cash_changes} value changes; capex annotations {capex_annotated}")
    print(f"Patched MSFT income rows from FinancialStatement XLSX: {income_touched} rows, {income_changes} value changes")
    print(f"Wrote refreshed derived dataset to {args.data_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
