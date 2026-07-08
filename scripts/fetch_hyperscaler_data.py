#!/usr/bin/env python3
"""Legacy Financial Datasets importer for hyperscaler financial statement data.

New updates should be sourced from official company IR/SEC materials. This
script is retained only as a historical bootstrap/import utility and requires
an explicit opt-in flag before it will call Financial Datasets.
"""

from __future__ import annotations

import argparse
import copy
import csv
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

API_BASE_URL = "https://api.financialdatasets.ai"
SEC_CIKS = {
    "MSFT": "0000789019",
    "AMZN": "0001018724",
    "GOOGL": "0001652044",
    "META": "0001326801",
    "ORCL": "0001341439",
}
SEC_COMPANYFACTS_URL_TEMPLATE = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
SEC_COMPANYFACTS_URL = SEC_COMPANYFACTS_URL_TEMPLATE.format(cik=SEC_CIKS["AMZN"])
DEFAULT_TICKERS = ["MSFT", "AMZN", "GOOGL", "META", "ORCL"]
DEFAULT_QUARTERS = 20
SEC_OPERATING_CASH_FLOW_TAG = "NetCashProvidedByUsedInOperatingActivities"
OFFICIAL_SOURCE_POLICY = (
    "Update policy: do not use Financial Datasets for new refreshes. Use each company's official "
    "IR/SEC source documents and keep legacy source/financials files only for audit/backfill history."
)

IDENTITY_FIELDS = ["ticker", "quarter", "report_period", "fiscal_period", "period", "currency"]
SOURCE_IDENTITY_FIELDS = [
    "ticker",
    "quarter",
    "report_period",
    "fiscal_period",
    "period",
    "currency",
    "accession_number",
    "filing_url",
]
SOURCE_AUDIT_FIELDS = [
    "capex_source",
    "capex_sec_accession_number",
    "capex_sec_filed",
    "capex_sec_frame",
    "capex_sec_filing_url",
    "debt_source",
    "debt_definition",
    "debt_sec_accession_number",
    "debt_sec_filed",
    "debt_sec_filing_url",
    "cash_flow_normalization",
    "fcf_source",
]
RAW_IDENTITY_FIELDS = [
    "ticker",
    "report_period",
    "fiscal_period",
    "period",
    "currency",
    "accession_number",
    "filing_url",
]
BALANCE_SHEET_FIELDS = [
    "total_assets",
    "current_assets",
    "cash_and_equivalents",
    "inventory",
    "current_investments",
    "trade_and_non_trade_receivables",
    "non_current_assets",
    "property_plant_and_equipment",
    "goodwill_and_intangible_assets",
    "investments",
    "non_current_investments",
    "outstanding_shares",
    "tax_assets",
    "total_liabilities",
    "current_liabilities",
    "current_debt",
    "trade_and_non_trade_payables",
    "deferred_revenue",
    "deposit_liabilities",
    "non_current_liabilities",
    "non_current_debt",
    "tax_liabilities",
    "shareholders_equity",
    "retained_earnings",
    "accumulated_other_comprehensive_income",
    "total_debt",
]
CASH_FLOW_FIELDS = [
    "net_income",
    "depreciation_and_amortization",
    "share_based_compensation",
    "net_cash_flow_from_operations",
    "capital_expenditure",
    "business_acquisitions_and_disposals",
    "investment_acquisitions_and_disposals",
    "net_cash_flow_from_investing",
    "issuance_or_repayment_of_debt_securities",
    "issuance_or_purchase_of_equity_shares",
    "dividends_and_other_cash_distributions",
    "net_cash_flow_from_financing",
    "change_in_cash_and_equivalents",
    "effect_of_exchange_rate_changes",
    "ending_cash_balance",
    "free_cash_flow",
    "free_cash_flow_reported",
]
YTD_CASH_FLOW_FIELDS = [
    "net_income",
    "depreciation_and_amortization",
    "share_based_compensation",
    "net_cash_flow_from_operations",
    "capital_expenditure",
    "business_acquisitions_and_disposals",
    "investment_acquisitions_and_disposals",
    "net_cash_flow_from_investing",
    "issuance_or_repayment_of_debt_securities",
    "issuance_or_purchase_of_equity_shares",
    "dividends_and_other_cash_distributions",
    "net_cash_flow_from_financing",
    "change_in_cash_and_equivalents",
    "effect_of_exchange_rate_changes",
    "free_cash_flow",
]
INCOME_STATEMENT_FIELDS = [
    "revenue",
    "cost_of_revenue",
    "gross_profit",
    "operating_expense",
    "selling_general_and_administrative_expenses",
    "research_and_development",
    "operating_income",
    "interest_expense",
    "ebit",
    "income_tax_expense",
    "net_income_discontinued_operations",
    "net_income_non_controlling_interests",
    "net_income",
    "net_income_common_stock",
    "preferred_dividends_impact",
    "consolidated_income",
    "earnings_per_share",
    "earnings_per_share_diluted",
    "dividends_per_common_share",
    "weighted_average_shares",
    "weighted_average_shares_diluted",
]
FINANCIAL_FIELDS = list(dict.fromkeys(BALANCE_SHEET_FIELDS + CASH_FLOW_FIELDS + INCOME_STATEMENT_FIELDS))
PANEL_FIELDS = IDENTITY_FIELDS + FINANCIAL_FIELDS


def quarter_label(report_period: str) -> str:
    report_date = datetime.strptime(report_period, "%Y-%m-%d")
    quarter = ((report_date.month - 1) // 3) + 1
    return f"{report_date.year}Q{quarter}"


def api_get(path: str, api_key: str, params: dict[str, Any]) -> dict[str, Any]:
    query = urllib.parse.urlencode({key: value for key, value in params.items() if value is not None})
    url = f"{API_BASE_URL}/{path.lstrip('/')}"
    if query:
        url = f"{url}?{query}"

    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "investing-research/0.1",
            "X-API-KEY": api_key,
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Financial Datasets API returned {error.code} for {path}: {body}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"Could not reach Financial Datasets API for {path}: {error}") from error


def sec_get_companyfacts(ticker: str = "AMZN", url: str | None = None) -> dict[str, Any]:
    cik = SEC_CIKS.get(ticker.upper(), SEC_CIKS["AMZN"])
    url = url or SEC_COMPANYFACTS_URL_TEMPLATE.format(cik=cik)
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "investing-research contact@example.com",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"SEC companyfacts returned {error.code}: {body}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"Could not reach SEC companyfacts: {error}") from error


def sec_uses_ytd_interim_cash_flow(companyfacts: dict[str, Any]) -> bool:
    values = (
        companyfacts.get("facts", {})
        .get("us-gaap", {})
        .get(SEC_OPERATING_CASH_FLOW_TAG, {})
        .get("units", {})
        .get("USD", [])
    )
    has_interim_ytd = False

    for value in values:
        if value.get("form") != "10-Q" or value.get("fp") not in {"Q2", "Q3"}:
            continue
        frame = value.get("frame")
        if isinstance(frame, str) and "Q" in frame:
            return False
        has_interim_ytd = True

    return has_interim_ytd


def infer_ytd_cash_flow_tickers(companyfacts_by_ticker: dict[str, dict[str, Any]]) -> set[str]:
    return {
        ticker
        for ticker, companyfacts in companyfacts_by_ticker.items()
        if sec_uses_ytd_interim_cash_flow(companyfacts)
    }


def is_missing(value: Any) -> bool:
    return value is None or value == ""


def numeric_or_none(value: Any) -> float | None:
    if is_missing(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def fiscal_year_quarter(row: dict[str, Any]) -> tuple[str, int] | None:
    fiscal_period = str(row.get("fiscal_period", "")).upper()
    match = re.search(r"(\d{4})-?Q([1-4])", fiscal_period)
    if not match:
        return None
    return match.group(1), int(match.group(2))


def preserve_reported_free_cash_flow(cash_flows: dict[str, list[dict[str, Any]]]) -> None:
    for rows in cash_flows.values():
        for row in rows:
            if "free_cash_flow_reported" not in row:
                row["free_cash_flow_reported"] = row.get("free_cash_flow")


def normalize_ytd_cash_flow_statements(
    cash_flows: dict[str, list[dict[str, Any]]],
    ytd_tickers: set[str],
) -> int:
    adjusted_fields = 0

    for ticker in ytd_tickers:
        rows = cash_flows.get(ticker, [])
        rows_by_fiscal_year: dict[str, dict[int, dict[str, Any]]] = {}
        original_by_fiscal_year: dict[str, dict[int, dict[str, Any]]] = {}

        for row in rows:
            fiscal = fiscal_year_quarter(row)
            if not fiscal:
                continue
            fiscal_year, fiscal_quarter = fiscal
            rows_by_fiscal_year.setdefault(fiscal_year, {})[fiscal_quarter] = row
            original_by_fiscal_year.setdefault(fiscal_year, {})[fiscal_quarter] = copy.deepcopy(row)

        for fiscal_year, rows_by_quarter in rows_by_fiscal_year.items():
            originals = original_by_fiscal_year[fiscal_year]
            for fiscal_quarter in (2, 3):
                row = rows_by_quarter.get(fiscal_quarter)
                current = originals.get(fiscal_quarter)
                previous = originals.get(fiscal_quarter - 1)
                if not row or not current or not previous:
                    continue

                row_adjusted = False
                for field in YTD_CASH_FLOW_FIELDS:
                    current_value = numeric_or_none(current.get(field))
                    previous_value = numeric_or_none(previous.get(field))
                    if current_value is None or previous_value is None:
                        continue
                    row[field] = current_value - previous_value
                    row_adjusted = True
                    adjusted_fields += 1

                if row_adjusted:
                    row["cash_flow_normalization"] = "fiscal_ytd_to_quarter"

    return adjusted_fields


def sec_amzn_capex_by_period(companyfacts: dict[str, Any]) -> dict[str, dict[str, Any]]:
    facts = companyfacts.get("facts", {}).get("us-gaap", {})
    productive_assets = facts.get("PaymentsToAcquireProductiveAssets", {})
    usd_values = productive_assets.get("units", {}).get("USD", [])
    capex_by_period: dict[str, dict[str, Any]] = {}

    for value in usd_values:
        frame = value.get("frame", "")
        report_period = value.get("end")
        amount = value.get("val")
        if not report_period or amount is None:
            continue
        if not isinstance(frame, str) or "Q" not in frame:
            continue
        accession_number = value.get("accn", "")
        accession_path = accession_number.replace("-", "")
        filing_url = (
            f"https://www.sec.gov/Archives/edgar/data/1018724/{accession_path}/{accession_number}-index.htm"
            if accession_number
            else ""
        )

        capex_by_period[report_period] = {
            "value": -abs(float(amount)),
            "accession_number": accession_number,
            "filed": value.get("filed", ""),
            "frame": frame,
            "filing_url": filing_url,
            "tag": "PaymentsToAcquireProductiveAssets",
        }

    return capex_by_period


def patch_amzn_capex_from_sec_companyfacts(
    cash_flows: dict[str, list[dict[str, Any]]],
    companyfacts: dict[str, Any],
) -> int:
    sec_capex = sec_amzn_capex_by_period(companyfacts)
    patched = 0

    for row in cash_flows.get("AMZN", []):
        if not is_missing(row.get("capital_expenditure")):
            continue

        report_period = row.get("report_period")
        sec_value = sec_capex.get(report_period)
        if not sec_value:
            continue

        row["capital_expenditure"] = sec_value["value"]
        row["capex_source"] = "sec_companyfacts:PaymentsToAcquireProductiveAssets"
        row["capex_sec_accession_number"] = sec_value["accession_number"]
        row["capex_sec_filed"] = sec_value["filed"]
        row["capex_sec_frame"] = sec_value["frame"]
        row["capex_sec_filing_url"] = sec_value["filing_url"]
        patched += 1

    return patched


def patch_free_cash_flow_from_ocf_and_capex(cash_flows: dict[str, list[dict[str, Any]]]) -> int:
    recalculated = 0

    for rows in cash_flows.values():
        for row in rows:
            operating_cash_flow = numeric_or_none(row.get("net_cash_flow_from_operations"))
            capex = numeric_or_none(row.get("capital_expenditure"))
            if operating_cash_flow is None or capex is None:
                continue

            calculated_fcf = operating_cash_flow - abs(capex)
            if "free_cash_flow_reported" not in row:
                row["free_cash_flow_reported"] = row.get("free_cash_flow")

            row["free_cash_flow"] = calculated_fcf
            row["fcf_source"] = "calculated:net_cash_flow_from_operations_minus_abs_capital_expenditure"
            recalculated += 1

    return recalculated


def fetch_statement(
    api_key: str,
    endpoint: str,
    response_key: str,
    ticker: str,
    period: str,
    limit: int,
) -> list[dict[str, Any]]:
    response = api_get(
        endpoint,
        api_key,
        {
            "ticker": ticker,
            "period": period,
            "limit": limit,
        },
    )
    statements = response.get(response_key)
    if not isinstance(statements, list):
        raise RuntimeError(f"Unexpected response for {ticker} {endpoint}: missing {response_key}")
    return statements


def fetch_statement_history(
    api_key: str,
    endpoint: str,
    response_key: str,
    ticker: str,
    period: str,
    limit: int,
) -> list[dict[str, Any]]:
    collected: list[dict[str, Any]] = []
    seen_periods: set[str] = set()
    report_period_lt: str | None = None

    while len(collected) < limit:
        response = api_get(
            endpoint,
            api_key,
            {
                "ticker": ticker,
                "period": period,
                "limit": limit,
                "report_period_lt": report_period_lt,
            },
        )
        statements = response.get(response_key)
        if not isinstance(statements, list):
            raise RuntimeError(f"Unexpected response for {ticker} {endpoint}: missing {response_key}")
        if not statements:
            break

        page_periods = [row.get("report_period") for row in statements if row.get("report_period")]
        if not page_periods:
            break

        starting_count = len(collected)
        for statement in sorted(statements, key=lambda item: item.get("report_period", ""), reverse=True):
            report_period = statement.get("report_period")
            if report_period and report_period not in seen_periods:
                collected.append(statement)
                seen_periods.add(report_period)
                if len(collected) == limit:
                    break

        oldest_period = min(page_periods)
        if len(collected) == starting_count or oldest_period == report_period_lt:
            break
        report_period_lt = oldest_period

    return sorted(collected, key=lambda item: item.get("report_period", ""), reverse=True)[:limit]


def fetch_financials_history(
    api_key: str,
    ticker: str,
    period: str,
    limit: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    balance_sheets: list[dict[str, Any]] = []
    cash_flows: list[dict[str, Any]] = []
    income_statements: list[dict[str, Any]] = []
    seen_balance_periods: set[str] = set()
    seen_cash_flow_periods: set[str] = set()
    seen_income_periods: set[str] = set()
    report_period_lt: str | None = None

    while len(balance_sheets) < limit or len(cash_flows) < limit or len(income_statements) < limit:
        response = api_get(
            "/financials",
            api_key,
            {
                "ticker": ticker,
                "period": period,
                "limit": limit,
                "report_period_lt": report_period_lt,
            },
        )
        financials = response.get("financials")
        if not isinstance(financials, dict):
            raise RuntimeError(f"Unexpected response for {ticker} /financials: missing financials")

        page_balance_sheets = financials.get("balance_sheets")
        page_cash_flows = financials.get("cash_flow_statements")
        page_income_statements = financials.get("income_statements")
        if (
            not isinstance(page_balance_sheets, list)
            or not isinstance(page_cash_flows, list)
            or not isinstance(page_income_statements, list)
        ):
            raise RuntimeError(f"Unexpected response for {ticker} /financials: missing statement arrays")
        if not page_balance_sheets and not page_cash_flows and not page_income_statements:
            break

        page_periods = [
            row.get("report_period")
            for row in [*page_balance_sheets, *page_cash_flows, *page_income_statements]
            if row.get("report_period")
        ]
        if not page_periods:
            break

        starting_count = len(balance_sheets) + len(cash_flows) + len(income_statements)
        for statement in sorted(page_balance_sheets, key=lambda item: item.get("report_period", ""), reverse=True):
            report_period = statement.get("report_period")
            if report_period and report_period not in seen_balance_periods and len(balance_sheets) < limit:
                balance_sheets.append(statement)
                seen_balance_periods.add(report_period)

        for statement in sorted(page_cash_flows, key=lambda item: item.get("report_period", ""), reverse=True):
            report_period = statement.get("report_period")
            if report_period and report_period not in seen_cash_flow_periods and len(cash_flows) < limit:
                cash_flows.append(statement)
                seen_cash_flow_periods.add(report_period)

        for statement in sorted(page_income_statements, key=lambda item: item.get("report_period", ""), reverse=True):
            report_period = statement.get("report_period")
            if report_period and report_period not in seen_income_periods and len(income_statements) < limit:
                income_statements.append(statement)
                seen_income_periods.add(report_period)

        if (
            len(page_balance_sheets) < limit
            and len(page_cash_flows) < limit
            and len(page_income_statements) < limit
        ):
            break

        oldest_period = min(page_periods)
        if len(balance_sheets) + len(cash_flows) + len(income_statements) == starting_count or oldest_period == report_period_lt:
            break
        report_period_lt = oldest_period

    return (
        sorted(balance_sheets, key=lambda item: item.get("report_period", ""), reverse=True)[:limit],
        sorted(cash_flows, key=lambda item: item.get("report_period", ""), reverse=True)[:limit],
        sorted(income_statements, key=lambda item: item.get("report_period", ""), reverse=True)[:limit],
    )


def selected_fields(record: dict[str, Any] | None, fields: list[str]) -> dict[str, Any]:
    record = record or {}
    return {field: record.get(field, "") for field in fields}


def identity_fields(record: dict[str, Any] | None) -> dict[str, Any]:
    record = record or {}
    report_period = record.get("report_period", "")
    return {
        "ticker": record.get("ticker", ""),
        "quarter": quarter_label(report_period) if report_period else "",
        "report_period": report_period,
        "fiscal_period": record.get("fiscal_period", ""),
        "period": record.get("period", ""),
        "currency": record.get("currency", ""),
    }


def source_identity_fields(record: dict[str, Any] | None) -> dict[str, Any]:
    record = record or {}
    return {
        **identity_fields(record),
        "accession_number": record.get("accession_number", ""),
        "filing_url": record.get("filing_url", ""),
    }


def statement_rows(
    rows: list[dict[str, Any]],
    statement_fields: list[str],
    limit: int,
) -> list[dict[str, Any]]:
    return [
        {
            **source_identity_fields(row),
            **selected_fields(row, statement_fields),
            **selected_fields(row, SOURCE_AUDIT_FIELDS),
        }
        for row in sorted(rows, key=lambda item: item.get("report_period", ""))[-limit:]
    ]


def build_panel(
    balance_sheets: dict[str, list[dict[str, Any]]],
    cash_flows: dict[str, list[dict[str, Any]]],
    income_statements: dict[str, list[dict[str, Any]]],
    tickers: list[str],
    limit: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    for ticker in tickers:
        balance_by_period = {
            row["report_period"]: row
            for row in balance_sheets.get(ticker, [])
            if row.get("report_period")
        }
        cash_flow_by_period = {
            row["report_period"]: row
            for row in cash_flows.get(ticker, [])
            if row.get("report_period")
        }
        income_by_period = {
            row["report_period"]: row
            for row in income_statements.get(ticker, [])
            if row.get("report_period")
        }
        recent_periods = sorted(
            set(balance_by_period) | set(cash_flow_by_period) | set(income_by_period),
            reverse=True,
        )[:limit]

        for report_period in sorted(recent_periods):
            balance_row = balance_by_period.get(report_period)
            cash_flow_row = cash_flow_by_period.get(report_period)
            income_row = income_by_period.get(report_period)
            source_row = balance_row or cash_flow_row or income_row or {}

            row: dict[str, Any] = {
                "ticker": ticker,
                "quarter": quarter_label(report_period),
                "report_period": report_period,
                "fiscal_period": source_row.get("fiscal_period", ""),
                "period": source_row.get("period", "quarterly"),
                "currency": source_row.get("currency", ""),
            }
            row.update(selected_fields(balance_row, BALANCE_SHEET_FIELDS))
            row.update(selected_fields(cash_flow_row, CASH_FLOW_FIELDS))
            row.update(selected_fields(income_row, INCOME_STATEMENT_FIELDS))
            rows.append(row)

    return sorted(rows, key=lambda item: (item["ticker"], item["report_period"]))


def pivot_metric(rows: list[dict[str, Any]], metric: str, tickers: list[str]) -> list[dict[str, Any]]:
    quarters = sorted({row["quarter"] for row in rows})
    values = {
        (row["quarter"], row["ticker"]): row.get(metric, "")
        for row in rows
    }

    return [
        {
            "quarter": quarter,
            **{ticker: values.get((quarter, ticker), "") for ticker in tickers},
        }
        for quarter in quarters
    ]


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def export_financials_source(
    raw_financials: dict[str, dict[str, Any]],
    base_dir: Path,
    tickers: list[str],
    limit: int,
    statement_financials: dict[str, dict[str, Any]] | None = None,
) -> None:
    for ticker in tickers:
        raw = raw_financials.get(ticker, {"financials": {}})
        statements = statement_financials.get(ticker, raw) if statement_financials else raw
        financials = statements.get("financials", {})
        balance_rows = statement_rows(financials.get("balance_sheets", []), BALANCE_SHEET_FIELDS, limit)
        cash_flow_rows = statement_rows(financials.get("cash_flow_statements", []), CASH_FLOW_FIELDS, limit)
        income_rows = statement_rows(financials.get("income_statements", []), INCOME_STATEMENT_FIELDS, limit)

        write_json(base_dir / "source" / "financials" / f"{ticker}.json", raw)
        write_json(base_dir / "source" / "balance_sheets" / f"{ticker}.json", balance_rows)
        write_json(base_dir / "source" / "cash_flow_statements" / f"{ticker}.json", cash_flow_rows)
        write_json(base_dir / "source" / "income_statements" / f"{ticker}.json", income_rows)
        write_csv(
            base_dir / "source" / "balance_sheets" / f"{ticker}.csv",
            balance_rows,
            SOURCE_IDENTITY_FIELDS + BALANCE_SHEET_FIELDS + SOURCE_AUDIT_FIELDS,
        )
        write_csv(
            base_dir / "source" / "cash_flow_statements" / f"{ticker}.csv",
            cash_flow_rows,
            SOURCE_IDENTITY_FIELDS + CASH_FLOW_FIELDS + SOURCE_AUDIT_FIELDS,
        )
        write_csv(
            base_dir / "source" / "income_statements" / f"{ticker}.csv",
            income_rows,
            SOURCE_IDENTITY_FIELDS + INCOME_STATEMENT_FIELDS + SOURCE_AUDIT_FIELDS,
        )


def export_sanitized_source(
    balance_sheets: dict[str, list[dict[str, Any]]],
    cash_flows: dict[str, list[dict[str, Any]]],
    base_dir: Path,
    tickers: list[str],
    limit: int,
) -> None:
    raw_financials = {
        ticker: {
            "financials": {
                "balance_sheets": balance_sheets.get(ticker, []),
                "cash_flow_statements": cash_flows.get(ticker, []),
                "income_statements": [],
            }
        }
        for ticker in tickers
    }
    export_financials_source(raw_financials, base_dir, tickers, limit)


def export_dataset(
    rows: list[dict[str, Any]],
    base_dir: Path,
    tickers: list[str],
    quarters_per_company: int = DEFAULT_QUARTERS,
    generated_at: str | None = None,
) -> None:
    generated_at = generated_at or datetime.now(UTC).isoformat().replace("+00:00", "Z")
    available_quarters_by_ticker = {
        ticker: len({row["report_period"] for row in rows if row["ticker"] == ticker})
        for ticker in tickers
    }

    write_json(base_dir / "panel" / "quarterly_hyperscaler_financials.json", rows)
    write_csv(base_dir / "panel" / "quarterly_hyperscaler_financials.csv", rows, PANEL_FIELDS)

    for ticker in tickers:
        company_rows = [row for row in rows if row["ticker"] == ticker]
        write_json(base_dir / "companies" / f"{ticker}.json", company_rows)
        write_csv(base_dir / "companies" / f"{ticker}.csv", company_rows, PANEL_FIELDS)

    for metric in FINANCIAL_FIELDS:
        metric_rows = pivot_metric(rows, metric, tickers)
        write_json(base_dir / "metrics" / f"{metric}.json", metric_rows)
        write_csv(base_dir / "metrics" / f"{metric}.csv", metric_rows, ["quarter", *tickers])

    metadata = {
        "generated_at": generated_at,
        "dataset": "hyperscaler_quarterly_financials",
        "period": "quarterly",
        "quarters_per_company": quarters_per_company,
        "row_count": len(rows),
        "available_quarters_by_ticker": available_quarters_by_ticker,
        "tickers": tickers,
        "fields": {
            "identity": IDENTITY_FIELDS,
            "balance_sheet": BALANCE_SHEET_FIELDS,
            "cash_flow": CASH_FLOW_FIELDS,
            "income_statement": INCOME_STATEMENT_FIELDS,
        },
        "units": "Raw reported values in each company's reported currency.",
        "notes": [
            OFFICIAL_SOURCE_POLICY,
            "source/financials keeps legacy raw aggregated /financials responses for audit/backfill history only.",
            "AMZN historical missing capital_expenditure values are filled from SEC companyfacts when available.",
            "AMZN Q4 capital_expenditure values are patched from locally archived SEC inline XBRL HTML when the legacy source value differs from the annual SEC value less Q1-Q3.",
            "AMZN debt metrics use pure financial debt from SEC inline XBRL when available: short-term borrowings, current/noncurrent long-term debt, and finance lease liabilities; operating lease liabilities and Amazon financing obligations are excluded.",
            "GOOGL capital_expenditure values are sign-normalized from locally archived GOOG SEC inline XBRL HTML when available, using the SEC cash outflow convention.",
            "GOOGL debt metrics use pure financial debt from locally archived GOOG SEC inline XBRL HTML when available: short-term borrowings, current/noncurrent long-term debt, and finance lease liabilities; operating lease liabilities are excluded.",
            "META capital_expenditure values are sign-normalized from locally archived SEC inline XBRL HTML when available, using the SEC cash outflow convention.",
            "META debt metrics use pure financial debt from locally archived SEC inline XBRL HTML when available: short-term borrowings, current/noncurrent long-term debt, and finance lease liabilities; operating lease liabilities are excluded.",
            "MSFT comparable fields are patched from locally archived Microsoft FinancialStatement XLSX files when available; Microsoft fiscal quarters are mapped to calendar quarters by report_period.",
            "MSFT capital_expenditure values are sign-normalized from FinancialStatement XLSX cash flow line Additions to property and equipment.",
            "MSFT debt metrics use pure financial debt from FinancialStatement XLSX: current portion of long-term debt plus long-term debt; operating lease liabilities are excluded.",
            "ORCL comparable fields are patched from locally archived Oracle official financial table XLSX files when available; Oracle fiscal quarters are mapped to calendar quarters by report_period.",
            "ORCL capital_expenditure values are sign-normalized from Oracle financial table XLSX cash flow line Capital expenditures.",
            "ORCL debt metrics use pure financial debt from Oracle financial table XLSX: notes payable and other borrowings, current plus non-current. Operating lease liabilities are excluded.",
            "SEC companyfacts are used to identify tickers whose interim cash flow statements are fiscal YTD values; those Q2/Q3 flow fields are differenced to quarterly values.",
            "free_cash_flow is recalculated as net_cash_flow_from_operations minus absolute capital_expenditure when a source value is missing or inconsistent; the original legacy/source value is kept in free_cash_flow_reported.",
            "quarter is a calendar quarter label derived from report_period.",
            "panel and metric files are derived views for easier analysis.",
        ],
    }
    write_json(base_dir / "metadata.json", metadata)
    write_readme(base_dir, tickers, quarters_per_company, available_quarters_by_ticker)


def write_readme(
    base_dir: Path,
    tickers: list[str],
    quarters_per_company: int,
    available_quarters_by_ticker: dict[str, int],
) -> None:
    availability = "\n".join(
        f"- {ticker}: {available_quarters_by_ticker.get(ticker, 0)} quarters"
        for ticker in tickers
    )
    text = f"""# Hyperscaler Financial Dataset

Quarterly income statement, balance sheet, and cash flow dataset for {", ".join(tickers)}.

Requested range: latest {quarters_per_company} quarters per company.

Available range in the current dataset:

{availability}

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
"""
    (base_dir / "README.md").write_text(text, encoding="utf-8")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data/hyperscaler"))
    parser.add_argument("--quarters", type=int, default=DEFAULT_QUARTERS)
    parser.add_argument("--period", choices=["quarterly"], default="quarterly")
    parser.add_argument("--tickers", nargs="+", default=DEFAULT_TICKERS)
    parser.add_argument("--api-key", default=os.environ.get("FINANCIAL_DATASETS_API_KEY"))
    parser.add_argument(
        "--allow-financialdatasets",
        action="store_true",
        help="Legacy escape hatch. Future refreshes should use official company IR/SEC documents instead.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    if not args.allow_financialdatasets:
        print(
            "Financial Datasets import is disabled for future refreshes. "
            "Use official company IR/SEC source documents, or pass --allow-financialdatasets for legacy bootstrap only.",
            file=sys.stderr,
        )
        return 2

    if not args.api_key:
        print("FINANCIAL_DATASETS_API_KEY is required.", file=sys.stderr)
        return 2

    balance_sheets: dict[str, list[dict[str, Any]]] = {}
    cash_flows: dict[str, list[dict[str, Any]]] = {}
    income_statements: dict[str, list[dict[str, Any]]] = {}
    raw_financials: dict[str, dict[str, Any]] = {}
    statement_financials: dict[str, dict[str, Any]] = {}
    companyfacts_by_ticker: dict[str, dict[str, Any]] = {}

    for ticker in args.tickers:
        print(f"Fetching {ticker} financials...")
        balance_sheets[ticker], cash_flows[ticker], income_statements[ticker] = fetch_financials_history(
            args.api_key,
            ticker,
            args.period,
            args.quarters,
        )
        raw_financials[ticker] = {
            "financials": {
                "income_statements": copy.deepcopy(income_statements[ticker]),
                "balance_sheets": copy.deepcopy(balance_sheets[ticker]),
                "cash_flow_statements": copy.deepcopy(cash_flows[ticker]),
            }
        }

    sec_tickers = [ticker for ticker in args.tickers if ticker in SEC_CIKS]
    if sec_tickers:
        print("Fetching SEC companyfacts for cash flow checks...")
        for ticker in sec_tickers:
            companyfacts_by_ticker[ticker] = sec_get_companyfacts(ticker)

    if "AMZN" in args.tickers:
        patched = patch_amzn_capex_from_sec_companyfacts(cash_flows, companyfacts_by_ticker.get("AMZN", {}))
        if patched:
            print(f"Patched {patched} AMZN capital_expenditure rows from SEC companyfacts.")

    preserve_reported_free_cash_flow(cash_flows)
    ytd_tickers = infer_ytd_cash_flow_tickers(companyfacts_by_ticker)
    normalized = normalize_ytd_cash_flow_statements(cash_flows, ytd_tickers)
    if normalized:
        print(f"Normalized {normalized} fiscal YTD cash flow fields to quarterly values for {', '.join(sorted(ytd_tickers))}.")

    fcf_patched = patch_free_cash_flow_from_ocf_and_capex(cash_flows)
    if fcf_patched:
        print(f"Recalculated {fcf_patched} free_cash_flow rows from OCF and capex.")

    for ticker in args.tickers:
        statement_financials[ticker] = {
            "financials": {
                "income_statements": income_statements[ticker],
                "balance_sheets": balance_sheets[ticker],
                "cash_flow_statements": cash_flows[ticker],
            }
        }

    rows = build_panel(balance_sheets, cash_flows, income_statements, args.tickers, args.quarters)
    export_financials_source(raw_financials, args.data_dir, args.tickers, args.quarters, statement_financials)
    export_dataset(rows, args.data_dir, args.tickers, quarters_per_company=args.quarters)
    expected_rows = len(args.tickers) * args.quarters
    if len(rows) < expected_rows:
        print(
            f"Warning: requested {expected_rows} rows, but API returned enough data for {len(rows)} rows.",
            file=sys.stderr,
        )
    print(f"Wrote {len(rows)} panel rows to {args.data_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
