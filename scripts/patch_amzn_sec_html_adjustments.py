#!/usr/bin/env python3
"""Patch AMZN derived financial data from archived SEC inline XBRL HTML."""

from __future__ import annotations

import argparse
import csv
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
from validate_amzn_financials_against_sec_html import FilingFacts, fiscal_year_quarter

TICKER = "AMZN"
DEFAULT_DATA_DIR = Path("data/hyperscaler")
DEFAULT_IR_DOCUMENT_MANIFEST = Path("data/hyperscaler/ir_documents/manifest.json")
CAPEX_TAG = "us-gaap:PaymentsToAcquireProductiveAssets"
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
    "current/noncurrent finance lease liabilities; excludes operating lease liabilities and Amazon financing obligations"
)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_manifest_by_quarter(manifest_path: Path) -> dict[str, dict[str, Any]]:
    rows = read_json(manifest_path)
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row.get("ticker") != TICKER or row.get("document_kind") != "sec_filing_html":
            continue
        if row.get("status") != "downloaded":
            continue
        result[row["quarter"]] = row
    return result


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


def sec_filing_for(row: dict[str, Any], manifest_by_quarter: dict[str, dict[str, Any]], cache: dict[Path, FilingFacts]) -> tuple[dict[str, Any], FilingFacts]:
    manifest_row = manifest_by_quarter[row["quarter"]]
    path = Path(manifest_row["local_path"])
    filing = cache.setdefault(path, FilingFacts(path))
    return manifest_row, filing


def sec_instant_value(filing: FilingFacts, report_period: str, tag: str) -> float:
    return filing.instant_value(report_period, tag) or 0.0


def sec_debt_values(filing: FilingFacts, report_period: str) -> tuple[float, float, float]:
    current_debt = sum(sec_instant_value(filing, report_period, tag) for tag in CURRENT_DEBT_TAGS)
    non_current_debt = sum(sec_instant_value(filing, report_period, tag) for tag in NON_CURRENT_DEBT_TAGS)
    return current_debt, non_current_debt, current_debt + non_current_debt


def patch_amzn_debt_from_sec_html(
    balance_rows: list[dict[str, Any]],
    manifest_by_quarter: dict[str, dict[str, Any]],
    cache: dict[Path, FilingFacts],
) -> int:
    patched = 0
    for row in balance_rows:
        if row.get("ticker") != TICKER or row.get("quarter") not in manifest_by_quarter:
            continue
        manifest_row, filing = sec_filing_for(row, manifest_by_quarter, cache)
        current_debt, non_current_debt, total_debt = sec_debt_values(filing, row["report_period"])
        if (
            row.get("current_debt") == current_debt
            and row.get("non_current_debt") == non_current_debt
            and row.get("total_debt") == total_debt
        ):
            continue
        row["current_debt"] = current_debt
        row["non_current_debt"] = non_current_debt
        row["total_debt"] = total_debt
        row["debt_source"] = "sec_html:pure_financial_debt"
        row["debt_definition"] = DEBT_DEFINITION
        row["debt_sec_accession_number"] = manifest_row.get("accession_number", "")
        row["debt_sec_filed"] = manifest_row.get("filing_date", "")
        row["debt_sec_filing_url"] = manifest_row.get("final_url") or manifest_row.get("source_url", "")
        patched += 1
    return patched


def patch_amzn_q4_capex_from_sec_html(
    cash_rows: list[dict[str, Any]],
    manifest_by_quarter: dict[str, dict[str, Any]],
    cache: dict[Path, FilingFacts],
) -> int:
    patched = 0
    ytd_history: dict[tuple[int, int, str], float] = {}

    for row in sorted(cash_rows, key=lambda item: item.get("report_period", "")):
        if row.get("ticker") != TICKER or row.get("quarter") not in manifest_by_quarter:
            continue
        manifest_row, filing = sec_filing_for(row, manifest_by_quarter, cache)
        fiscal_year, fiscal_quarter = fiscal_year_quarter(row["fiscal_period"])

        ytd_value = filing.ytd_value(row, CAPEX_TAG)
        if ytd_value is not None:
            ytd_history[(fiscal_year, fiscal_quarter, CAPEX_TAG)] = ytd_value

        if fiscal_quarter != 4:
            continue

        positive_capex, method = filing.quarter_duration_value(row, CAPEX_TAG, ytd_history)
        if positive_capex is None:
            continue
        sec_capex = -abs(positive_capex)
        if row.get("capital_expenditure") == sec_capex:
            continue

        if "free_cash_flow_reported" not in row:
            row["free_cash_flow_reported"] = row.get("free_cash_flow")
        row["capital_expenditure"] = sec_capex
        operating_cash_flow = numeric_or_none(row.get("net_cash_flow_from_operations"))
        if operating_cash_flow is not None:
            row["free_cash_flow"] = operating_cash_flow - abs(sec_capex)
            row["fcf_source"] = "calculated:net_cash_flow_from_operations_minus_abs_capital_expenditure"

        row["capex_source"] = "sec_html:PaymentsToAcquireProductiveAssets"
        row["capex_sec_accession_number"] = manifest_row.get("accession_number", "")
        row["capex_sec_filed"] = manifest_row.get("filing_date", "")
        row["capex_sec_frame"] = method
        row["capex_sec_filing_url"] = manifest_row.get("final_url") or manifest_row.get("source_url", "")
        patched += 1

    return patched


def numeric_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def write_amzn_source_files(data_dir: Path, balance_rows: list[dict[str, Any]], cash_rows: list[dict[str, Any]]) -> None:
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
    parser.add_argument("--manifest-path", type=Path, default=DEFAULT_IR_DOCUMENT_MANIFEST)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    manifest_by_quarter = load_manifest_by_quarter(args.manifest_path)
    if not manifest_by_quarter:
        print(f"No downloaded AMZN SEC HTML filings found in {args.manifest_path}", file=sys.stderr)
        return 1

    balance_sheets = load_statement_rows(args.data_dir, "balance_sheets")
    cash_flows = load_statement_rows(args.data_dir, "cash_flow_statements")
    income_statements = load_statement_rows(args.data_dir, "income_statements")
    tickers = load_tickers(args.data_dir, balance_sheets)
    cache: dict[Path, FilingFacts] = {}

    debt_patched = patch_amzn_debt_from_sec_html(balance_sheets.get(TICKER, []), manifest_by_quarter, cache)
    q4_capex_patched = patch_amzn_q4_capex_from_sec_html(cash_flows.get(TICKER, []), manifest_by_quarter, cache)
    write_amzn_source_files(args.data_dir, balance_sheets.get(TICKER, []), cash_flows.get(TICKER, []))

    rows = build_panel(balance_sheets, cash_flows, income_statements, tickers, limit=max(len(rows) for rows in balance_sheets.values()))
    export_dataset(rows, args.data_dir, tickers, quarters_per_company=max(len(rows) for rows in balance_sheets.values()))

    print(f"Patched AMZN debt rows from SEC HTML: {debt_patched}")
    print(f"Patched AMZN Q4 capex rows from SEC HTML: {q4_capex_patched}")
    print(f"Wrote refreshed derived dataset to {args.data_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
