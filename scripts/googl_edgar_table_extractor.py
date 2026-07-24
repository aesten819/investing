"""Extract GOOGL financial rows from SEC/EDGAR converted HTML tables."""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any


class HtmlTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[str]]] = []
        self._depth = 0
        self._table: list[list[str]] | None = None
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag == "table":
            self._depth += 1
            if self._depth == 1:
                self._table = []
        elif self._depth and tag == "tr":
            self._row = []
        elif self._depth and tag in {"td", "th"}:
            self._cell = []
        elif self._depth and tag == "br" and self._cell is not None:
            self._cell.append(" ")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self._depth and tag in {"td", "th"} and self._cell is not None:
            text = " ".join("".join(self._cell).split())
            if self._row is not None:
                self._row.append(text)
            self._cell = None
        elif self._depth and tag == "tr" and self._row is not None:
            if any(self._row):
                assert self._table is not None
                self._table.append(self._row)
            self._row = None
        elif tag == "table" and self._depth:
            if self._depth == 1 and self._table is not None:
                self.tables.append(self._table)
                self._table = None
            self._depth -= 1

    def handle_data(self, data: str) -> None:
        if self._depth and self._cell is not None:
            self._cell.append(data)


def parse_html_tables(path: Path) -> list[list[list[str]]]:
    parser = HtmlTableParser()
    parser.feed(path.read_text(encoding="utf-8", errors="replace"))
    return parser.tables


def normalized(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().lower()


def table_with_labels(tables: list[list[list[str]]], labels: tuple[str, ...]) -> list[list[str]]:
    normalized_labels = tuple(normalized(label) for label in labels)
    for table in tables:
        row_labels = [normalized(row[0]) for row in table if row]
        if all(any(label in row_label for row_label in row_labels) for label in normalized_labels):
            return table
    raise ValueError(f"Could not find table with labels: {labels}")


def matching_rows(table: list[list[str]], label: str) -> list[list[str]]:
    target = normalized(label)
    return [row for row in table if row and target in normalized(row[0])]


def parse_number(value: str) -> float | None:
    text = value.replace("\xa0", " ").strip()
    if text in {"", "$", "%", "_(1)"}:
        return None
    text = text.replace("$", "").replace(",", "").replace("%", "").strip()
    if text in {"", "-", "--"}:
        return None

    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1].strip()

    if not re.fullmatch(r"-?\d+(?:\.\d+)?", text):
        return None

    value_float = float(text)
    return -value_float if negative else value_float


def row_numbers(row: list[str]) -> list[float]:
    return [value for value in (parse_number(cell) for cell in row[1:]) if value is not None]


def table_value(
    table: list[list[str]],
    label: str,
    *,
    occurrence: int = 0,
    value_index: int = -1,
    scale: float = 1_000_000.0,
) -> float:
    rows = matching_rows(table, label)
    if len(rows) <= occurrence:
        raise ValueError(f"Could not find row {occurrence} for label: {label}")
    values = row_numbers(rows[occurrence])
    if not values:
        raise ValueError(f"Could not parse numeric values for label: {label}")
    return values[value_index] * scale


def prior_same_year_total(rows: list[dict[str, Any]], report_period: str, field: str) -> float:
    total = 0.0
    report_year = report_period[:4]
    for row in rows:
        row_period = str(row.get("report_period", ""))
        if row_period[:4] != report_year or row_period >= report_period:
            continue
        value = row.get(field)
        if value in (None, ""):
            continue
        total += float(value)
    return total


def current_quarter_from_ytd(
    cash_flow_table: list[list[str]],
    prior_cash_flow_rows: list[dict[str, Any]],
    report_period: str,
    label: str,
    field: str,
) -> float:
    ytd_value = table_value(cash_flow_table, label)
    return ytd_value - prior_same_year_total(prior_cash_flow_rows, report_period, field)


def ytd_sum(cash_flow_table: list[list[str]], labels: tuple[str, ...]) -> float:
    return sum(table_value(cash_flow_table, label) for label in labels)


def current_quarter_sum_from_ytd(
    cash_flow_table: list[list[str]],
    prior_cash_flow_rows: list[dict[str, Any]],
    report_period: str,
    labels: tuple[str, ...],
    field: str,
) -> float:
    return ytd_sum(cash_flow_table, labels) - prior_same_year_total(prior_cash_flow_rows, report_period, field)


def extract_outstanding_shares(balance_table: list[list[str]]) -> float:
    rows = matching_rows(balance_table, "Class A, Class B, and Class C stock")
    if not rows:
        return 0.0
    matches = re.findall(r"(?:;|and)\s*([\d,]+)\s*\(Class A", rows[0][0])
    if not matches:
        return 0.0
    return float(matches[-1].replace(",", "")) * 1_000_000.0


def extract_dividend_per_common_share(tables: list[list[list[str]]], report_period: str) -> float:
    quarter_header = f"Three Months Ended {report_period[:4] if report_period else ''}"
    for table in tables:
        joined = " ".join(" ".join(row) for row in table)
        if "Dividends and dividend equivalents declared on common stock" not in joined:
            continue
        if "Three Months Ended" not in joined:
            continue
        for row in table:
            match = re.search(
                r"Dividends and dividend equivalents declared on common stock \(\$(\d+(?:\.\d+)?) per share\)",
                row[0] if row else "",
            )
            if match and (quarter_header in joined or report_period[:4] in joined):
                return float(match.group(1))
    return 0.0


def extract_weighted_average_shares(tables: list[list[list[str]]]) -> tuple[float, float]:
    eps_table = table_with_labels(
        tables,
        (
            "Basic net income per common share:",
            "Diluted net income per common share:",
            "Number of shares used in per share computation",
        ),
    )
    share_rows = matching_rows(eps_table, "Number of shares used in per share computation")
    if len(share_rows) < 2:
        raise ValueError("Could not find basic and diluted weighted-average share rows")
    basic = row_numbers(share_rows[0])[-1] * 1_000_000.0
    diluted = row_numbers(share_rows[-1])[-1] * 1_000_000.0
    return basic, diluted


def extract_googl_financial_rows_from_html(
    html_path: Path,
    report_period: str,
    prior_cash_flow_rows: list[dict[str, Any]],
) -> dict[str, dict[str, float]]:
    tables = parse_html_tables(html_path)
    balance_table = table_with_labels(
        tables,
        ("Cash and cash equivalents", "Total assets", "Long-term debt", "Total stockholders"),
    )
    income_table = table_with_labels(
        tables,
        ("Revenues", "Cost of revenues", "Preferred stock dividends", "Diluted net income per common share"),
    )
    cash_flow_table = table_with_labels(
        tables,
        (
            "Net cash provided by operating activities",
            "Purchases of property and equipment",
            "Cash and cash equivalents at end of period",
        ),
    )
    lease_table = table_with_labels(tables, ("Total finance lease liabilities", "Other long-term liabilities"))
    debt_table = table_with_labels(tables, ("Total long-term debt", "Less: current portion of long-term notes"))

    cash_and_equivalents = table_value(balance_table, "Cash and cash equivalents")
    current_investments = table_value(balance_table, "Marketable securities")
    non_current_investments = table_value(balance_table, "Non-marketable securities")
    current_assets = table_value(balance_table, "Total current assets")
    total_assets = table_value(balance_table, "Total assets")
    goodwill = table_value(balance_table, "Goodwill")
    intangible_assets = table_value(balance_table, "Intangible assets, net")
    current_debt = abs(table_value(debt_table, "Less: current portion of long-term notes")) + table_value(
        lease_table,
        "Accrued expenses and other liabilities",
        occurrence=1,
    )
    non_current_debt = table_value(debt_table, "Total long-term debt") + table_value(
        lease_table,
        "Other long-term liabilities",
    )

    revenue = table_value(income_table, "Revenues", value_index=1)
    cost_of_revenue = table_value(income_table, "Cost of revenues", value_index=1)
    research_and_development = table_value(income_table, "Research and development", value_index=1)
    sales_and_marketing = table_value(income_table, "Sales and marketing", value_index=1)
    general_and_administrative = table_value(income_table, "General and administrative", value_index=1)
    net_income = table_value(income_table, "Net income", value_index=1)
    net_income_common_stock = table_value(income_table, "Net income available to common stockholders", value_index=1)
    preferred_dividends = table_value(income_table, "Preferred stock dividends", value_index=1)
    weighted_average_shares, weighted_average_shares_diluted = extract_weighted_average_shares(tables)

    cash_flow = {
        "net_income": current_quarter_from_ytd(cash_flow_table, prior_cash_flow_rows, report_period, "Net income", "net_income"),
        "depreciation_and_amortization": current_quarter_from_ytd(
            cash_flow_table,
            prior_cash_flow_rows,
            report_period,
            "Depreciation of property and equipment",
            "depreciation_and_amortization",
        ),
        "share_based_compensation": current_quarter_from_ytd(
            cash_flow_table,
            prior_cash_flow_rows,
            report_period,
            "Stock-based compensation expense",
            "share_based_compensation",
        ),
        "net_cash_flow_from_operations": current_quarter_from_ytd(
            cash_flow_table,
            prior_cash_flow_rows,
            report_period,
            "Net cash provided by operating activities",
            "net_cash_flow_from_operations",
        ),
        "capital_expenditure": current_quarter_from_ytd(
            cash_flow_table,
            prior_cash_flow_rows,
            report_period,
            "Purchases of property and equipment",
            "capital_expenditure",
        ),
        "business_acquisitions_and_disposals": current_quarter_from_ytd(
            cash_flow_table,
            prior_cash_flow_rows,
            report_period,
            "Acquisitions, net of cash acquired, and purchases of intangible assets",
            "business_acquisitions_and_disposals",
        ),
        "investment_acquisitions_and_disposals": current_quarter_sum_from_ytd(
            cash_flow_table,
            prior_cash_flow_rows,
            report_period,
            (
                "Purchases of marketable securities",
                "Maturities and sales of marketable securities",
                "Purchases of non-marketable securities",
                "Maturities and sales of non-marketable securities",
            ),
            "investment_acquisitions_and_disposals",
        ),
        "net_cash_flow_from_investing": current_quarter_from_ytd(
            cash_flow_table,
            prior_cash_flow_rows,
            report_period,
            "Net cash used in investing activities",
            "net_cash_flow_from_investing",
        ),
        "issuance_or_repayment_of_debt_securities": current_quarter_sum_from_ytd(
            cash_flow_table,
            prior_cash_flow_rows,
            report_period,
            ("Proceeds from issuance of debt, net of costs", "Repayments of debt"),
            "issuance_or_repayment_of_debt_securities",
        ),
        "issuance_or_purchase_of_equity_shares": current_quarter_sum_from_ytd(
            cash_flow_table,
            prior_cash_flow_rows,
            report_period,
            (
                "Net payments related to stock-based award activities",
                "Repurchases of stock",
                "Proceeds from issuance of common stock, net of costs",
                "Proceeds from issuance of mandatory convertible preferred stock, net of costs",
            ),
            "issuance_or_purchase_of_equity_shares",
        ),
        "dividends_and_other_cash_distributions": current_quarter_from_ytd(
            cash_flow_table,
            prior_cash_flow_rows,
            report_period,
            "Dividend payments",
            "dividends_and_other_cash_distributions",
        ),
        "net_cash_flow_from_financing": current_quarter_from_ytd(
            cash_flow_table,
            prior_cash_flow_rows,
            report_period,
            "Net cash provided by (used in) financing activities",
            "net_cash_flow_from_financing",
        ),
        "change_in_cash_and_equivalents": current_quarter_from_ytd(
            cash_flow_table,
            prior_cash_flow_rows,
            report_period,
            "Net increase (decrease) in cash and cash equivalents",
            "change_in_cash_and_equivalents",
        ),
        "effect_of_exchange_rate_changes": current_quarter_from_ytd(
            cash_flow_table,
            prior_cash_flow_rows,
            report_period,
            "Effect of exchange rate changes on cash and cash equivalents",
            "effect_of_exchange_rate_changes",
        ),
        "ending_cash_balance": table_value(cash_flow_table, "Cash and cash equivalents at end of period"),
    }
    cash_flow["free_cash_flow"] = cash_flow["net_cash_flow_from_operations"] - abs(cash_flow["capital_expenditure"])
    cash_flow["free_cash_flow_reported"] = cash_flow["free_cash_flow"]

    income_statement = {
        "revenue": revenue,
        "cost_of_revenue": cost_of_revenue,
        "gross_profit": revenue - cost_of_revenue,
        "operating_expense": research_and_development + sales_and_marketing + general_and_administrative,
        "selling_general_and_administrative_expenses": sales_and_marketing + general_and_administrative,
        "research_and_development": research_and_development,
        "operating_income": table_value(income_table, "Income from operations", value_index=1),
        "interest_expense": 0.0,
        "ebit": table_value(income_table, "Income before income taxes", value_index=1),
        "income_tax_expense": table_value(income_table, "Provision for income taxes", value_index=1),
        "net_income_discontinued_operations": 0.0,
        "net_income_non_controlling_interests": 0.0,
        "net_income": net_income,
        "net_income_common_stock": net_income_common_stock,
        "preferred_dividends_impact": preferred_dividends,
        "consolidated_income": net_income,
        "earnings_per_share": table_value(income_table, "Basic net income per common share", value_index=1, scale=1.0),
        "earnings_per_share_diluted": table_value(
            income_table,
            "Diluted net income per common share",
            value_index=1,
            scale=1.0,
        ),
        "dividends_per_common_share": extract_dividend_per_common_share(tables, report_period),
        "weighted_average_shares": weighted_average_shares,
        "weighted_average_shares_diluted": weighted_average_shares_diluted,
    }

    balance_sheet = {
        "total_assets": total_assets,
        "current_assets": current_assets,
        "cash_and_equivalents": cash_and_equivalents,
        "inventory": table_value(balance_table, "Inventory"),
        "current_investments": current_investments,
        "trade_and_non_trade_receivables": table_value(balance_table, "Accounts receivable, net"),
        "non_current_assets": total_assets - current_assets,
        "property_plant_and_equipment": table_value(balance_table, "Property and equipment, net"),
        "goodwill_and_intangible_assets": goodwill + intangible_assets,
        "investments": current_investments + non_current_investments,
        "non_current_investments": non_current_investments,
        "outstanding_shares": extract_outstanding_shares(balance_table),
        "tax_assets": table_value(balance_table, "Deferred income taxes", occurrence=0),
        "total_liabilities": table_value(balance_table, "Total liabilities"),
        "current_liabilities": table_value(balance_table, "Total current liabilities"),
        "current_debt": current_debt,
        "trade_and_non_trade_payables": table_value(balance_table, "Accounts payable"),
        "deferred_revenue": table_value(balance_table, "Deferred revenue"),
        "deposit_liabilities": 0.0,
        "non_current_liabilities": table_value(balance_table, "Total liabilities")
        - table_value(balance_table, "Total current liabilities"),
        "non_current_debt": non_current_debt,
        "tax_liabilities": table_value(balance_table, "Income taxes payable, non-current"),
        "shareholders_equity": table_value(balance_table, "Total stockholders"),
        "retained_earnings": table_value(balance_table, "Retained earnings"),
        "accumulated_other_comprehensive_income": table_value(
            balance_table,
            "Accumulated other comprehensive income",
        ),
        "total_debt": current_debt + non_current_debt,
    }

    return {
        "balance_sheet": balance_sheet,
        "cash_flow_statement": cash_flow,
        "income_statement": income_statement,
    }
