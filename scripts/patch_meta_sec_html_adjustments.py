#!/usr/bin/env python3
"""Patch META derived financial data from archived SEC inline XBRL HTML."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from fetch_hyperscaler_data import (
    BALANCE_SHEET_FIELDS,
    CASH_FLOW_FIELDS,
    SOURCE_AUDIT_FIELDS,
    SOURCE_IDENTITY_FIELDS,
    build_panel,
    export_dataset,
    write_csv,
    write_json,
)
from validate_amzn_financials_against_sec_html import FilingFacts, fiscal_year_quarter

TICKER = "META"
DEFAULT_DATA_DIR = Path("data/hyperscaler")
DEFAULT_SEC_HTML_DIR = Path("data/hyperscaler/ir_documents/originals/META/sec_filing_html")

CAPEX_TAG = "us-gaap:PaymentsToAcquirePropertyPlantAndEquipment"
CURRENT_DEBT_TAGS = (
    "us-gaap:LongTermDebtCurrent",
    "us-gaap:ShortTermBorrowings",
    "us-gaap:FinanceLeaseLiabilityCurrent",
)
NON_CURRENT_DEBT_TAGS = (
    "us-gaap:LongTermDebtNoncurrent",
    "us-gaap:FinanceLeaseLiabilityNoncurrent",
)
DEBT_DEFINITION = (
    "pure_financial_debt: short-term borrowings + current/noncurrent long-term debt + "
    "current/noncurrent finance lease liabilities; excludes operating lease liabilities"
)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_sec_html_by_quarter(sec_html_dir: Path) -> dict[str, dict[str, str]]:
    results: dict[str, dict[str, str]] = {}
    for path in sorted(sec_html_dir.glob("META_*_sec_filing_html_*.html")):
        match = re.fullmatch(
            r"META_(\d{4}Q[1-4])_(\d{4}-Q[1-4])_sec_filing_html_(10-[qk])\.html",
            path.name,
            re.IGNORECASE,
        )
        if not match:
            continue
        results[match.group(1)] = {
            "fiscal_period": match.group(2),
            "form_type": match.group(3).upper(),
            "local_path": str(path),
        }
    return results


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


def sec_filing_for(
    row: dict[str, Any],
    html_by_quarter: dict[str, dict[str, str]],
    cache: dict[Path, FilingFacts],
) -> tuple[dict[str, str], FilingFacts]:
    html_info = html_by_quarter[row["quarter"]]
    path = Path(html_info["local_path"])
    filing = cache.setdefault(path, FilingFacts(path))
    return html_info, filing


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


def sec_instant_value(filing: FilingFacts, report_period: str, tag: str) -> float:
    return filing.instant_value(report_period, tag) or 0.0


def sec_debt_values(filing: FilingFacts, report_period: str) -> tuple[float, float, float]:
    current_debt = sum(sec_instant_value(filing, report_period, tag) for tag in CURRENT_DEBT_TAGS)
    non_current_debt = sum(sec_instant_value(filing, report_period, tag) for tag in NON_CURRENT_DEBT_TAGS)
    return current_debt, non_current_debt, current_debt + non_current_debt


def patch_meta_debt_from_sec_html(
    balance_rows: list[dict[str, Any]],
    html_by_quarter: dict[str, dict[str, str]],
    cache: dict[Path, FilingFacts],
) -> tuple[int, int]:
    rows_touched = 0
    value_patched = 0

    for row in balance_rows:
        if row.get("ticker") != TICKER or row.get("quarter") not in html_by_quarter:
            continue
        html_info, filing = sec_filing_for(row, html_by_quarter, cache)
        current_debt, non_current_debt, total_debt = sec_debt_values(filing, row["report_period"])
        changed = (
            value_changed(row.get("current_debt"), current_debt)
            or value_changed(row.get("non_current_debt"), non_current_debt)
            or value_changed(row.get("total_debt"), total_debt)
        )

        row["current_debt"] = current_debt
        row["non_current_debt"] = non_current_debt
        row["total_debt"] = total_debt
        row["debt_source"] = "sec_html:pure_financial_debt"
        row["debt_definition"] = DEBT_DEFINITION
        row["debt_sec_accession_number"] = ""
        row["debt_sec_filed"] = ""
        row["debt_sec_filing_url"] = html_info["local_path"]
        rows_touched += 1
        if changed:
            value_patched += 1

    return rows_touched, value_patched


def patch_meta_capex_from_sec_html(
    cash_rows: list[dict[str, Any]],
    html_by_quarter: dict[str, dict[str, str]],
    cache: dict[Path, FilingFacts],
) -> tuple[int, int]:
    rows_touched = 0
    value_patched = 0
    ytd_history: dict[tuple[int, int, str], float] = {}

    for row in sorted(cash_rows, key=lambda item: item.get("report_period", "")):
        if row.get("ticker") != TICKER or row.get("quarter") not in html_by_quarter:
            continue
        html_info, filing = sec_filing_for(row, html_by_quarter, cache)
        fiscal_year, fiscal_quarter = fiscal_year_quarter(row["fiscal_period"])

        ytd_value = filing.ytd_value(row, CAPEX_TAG)
        if ytd_value is not None:
            ytd_history[(fiscal_year, fiscal_quarter, CAPEX_TAG)] = ytd_value

        positive_capex, method = filing.quarter_duration_value(row, CAPEX_TAG, ytd_history)
        if positive_capex is None:
            continue

        sec_capex = -abs(positive_capex)
        if value_changed(row.get("capital_expenditure"), sec_capex):
            value_patched += 1
        if "free_cash_flow_reported" not in row:
            row["free_cash_flow_reported"] = row.get("free_cash_flow")

        row["capital_expenditure"] = sec_capex
        operating_cash_flow = numeric_or_none(row.get("net_cash_flow_from_operations"))
        if operating_cash_flow is not None:
            row["free_cash_flow"] = operating_cash_flow - abs(sec_capex)
            row["fcf_source"] = "calculated:net_cash_flow_from_operations_minus_abs_capital_expenditure"

        row["capex_source"] = "sec_html:PaymentsToAcquirePropertyPlantAndEquipment"
        row["capex_sec_accession_number"] = ""
        row["capex_sec_filed"] = ""
        row["capex_sec_frame"] = method
        row["capex_sec_filing_url"] = html_info["local_path"]
        rows_touched += 1

    return rows_touched, value_patched


def write_meta_source_files(data_dir: Path, balance_rows: list[dict[str, Any]], cash_rows: list[dict[str, Any]]) -> None:
    write_json(data_dir / "source" / "balance_sheets" / f"{TICKER}.json", balance_rows)
    write_json(data_dir / "source" / "cash_flow_statements" / f"{TICKER}.json", cash_rows)
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


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--sec-html-dir", type=Path, default=DEFAULT_SEC_HTML_DIR)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    html_by_quarter = load_sec_html_by_quarter(args.sec_html_dir)
    if not html_by_quarter:
        print(f"No downloaded META SEC HTML filings found in {args.sec_html_dir}", file=sys.stderr)
        return 1

    balance_sheets = load_statement_rows(args.data_dir, "balance_sheets")
    cash_flows = load_statement_rows(args.data_dir, "cash_flow_statements")
    income_statements = load_statement_rows(args.data_dir, "income_statements")
    tickers = load_tickers(args.data_dir, balance_sheets)
    cache: dict[Path, FilingFacts] = {}

    debt_rows, debt_value_patches = patch_meta_debt_from_sec_html(balance_sheets.get(TICKER, []), html_by_quarter, cache)
    capex_rows, capex_value_patches = patch_meta_capex_from_sec_html(cash_flows.get(TICKER, []), html_by_quarter, cache)
    write_meta_source_files(args.data_dir, balance_sheets.get(TICKER, []), cash_flows.get(TICKER, []))

    limit = max(len(rows) for rows in balance_sheets.values())
    rows = build_panel(balance_sheets, cash_flows, income_statements, tickers, limit=limit)
    export_dataset(rows, args.data_dir, tickers, quarters_per_company=limit)

    print(f"Patched META debt rows from SEC HTML: {debt_rows} rows, {debt_value_patches} value changes")
    print(f"Patched META capex rows from SEC HTML: {capex_rows} rows, {capex_value_patches} value changes")
    print(f"Wrote refreshed derived dataset to {args.data_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
