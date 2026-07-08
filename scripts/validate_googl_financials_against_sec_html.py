#!/usr/bin/env python3
"""Validate stored GOOGL financial rows against locally archived GOOG SEC inline XBRL HTML."""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from validate_amzn_financials_against_sec_html import (
    FilingFacts,
    SecMetric,
    direct_duration_only,
    direct_instant,
    duration_metric,
    duration_metric_first_available,
    expression_metric,
    fiscal_year_quarter,
)

TICKER = "GOOGL"
SOURCE_FOLDER_TICKER = "GOOG"
DEFAULT_COMPANY_PATH = Path("data/hyperscaler/companies/GOOGL.json")
DEFAULT_SEC_HTML_DIR = Path("data/hyperscaler/ir_documents/originals/GOOG/sec_filing_html")
DEFAULT_OUTPUT_DIR = Path("data/hyperscaler/validation/googl_sec_html")

MONEY_TOLERANCE = 1_000_000.0
SHARE_TOLERANCE = 1_000_000.0
PER_SHARE_TOLERANCE = 0.005


def quarter_label(report_period: str) -> str:
    year, month, _ = report_period.split("-")
    quarter = ((int(month) - 1) // 3) + 1
    return f"{year}Q{quarter}"


def instant_first_available(tags: tuple[str, ...]) -> Callable[[FilingFacts, dict[str, Any], dict[tuple[int, int, str], float]], tuple[float | None, str]]:
    def calculate(
        filing: FilingFacts,
        row: dict[str, Any],
        _: dict[tuple[int, int, str], float],
    ) -> tuple[float | None, str]:
        for tag in tags:
            value = filing.instant_value(row["report_period"], tag)
            if value is not None:
                return value, f"{tag} instant fact at {row['report_period']}"
        return None, f"missing all instant facts: {'|'.join(tags)}"

    return calculate


def instant_first_available_or_not_comparable(
    tags: tuple[str, ...],
    reason: str,
) -> Callable[[FilingFacts, dict[str, Any], dict[tuple[int, int, str], float]], tuple[float | None, str]]:
    def calculate(
        filing: FilingFacts,
        row: dict[str, Any],
        _: dict[tuple[int, int, str], float],
    ) -> tuple[float | None, str]:
        for tag in tags:
            value = filing.instant_value(row["report_period"], tag)
            if value is not None:
                return value, f"{tag} instant fact at {row['report_period']}"
        return None, f"not_comparable: {reason}"

    return calculate


def direct_duration_only_or_skip(tag: str) -> Callable[[FilingFacts, dict[str, Any], dict[tuple[int, int, str], float]], tuple[float | None, str]]:
    def calculate(
        filing: FilingFacts,
        row: dict[str, Any],
        _: dict[tuple[int, int, str], float],
    ) -> tuple[float | None, str]:
        fiscal_year, fiscal_quarter = fiscal_year_quarter(row["fiscal_period"])
        if fiscal_quarter == 4:
            return None, "skipped: 10-K has no reliable standalone Q4 fact for non-additive per-share/share metric"
        month = {1: 1, 2: 4, 3: 7, 4: 10}[fiscal_quarter]
        quarter_start = f"{fiscal_year}-{month:02d}-01"
        value = filing.duration_value(quarter_start, row["report_period"], tag)
        if value is None:
            return None, "skipped: filing reports share metric by share class, not as one no-dimension consolidated fact"
        return value, f"direct quarter {quarter_start} to {row['report_period']}"

    return calculate


def instant_expression_first_available(
    components: dict[str, tuple[str, ...]],
    expression: str,
    calculator: Callable[[dict[str, float]], float],
    *,
    missing_as_zero: bool = False,
) -> Callable[[FilingFacts, dict[str, Any], dict[tuple[int, int, str], float]], tuple[float | None, str]]:
    def calculate(
        filing: FilingFacts,
        row: dict[str, Any],
        _: dict[tuple[int, int, str], float],
    ) -> tuple[float | None, str]:
        values: dict[str, float] = {}
        methods: list[str] = []
        for name, tags in components.items():
            selected_value = None
            selected_tag = ""
            for tag in tags:
                value = filing.instant_value(row["report_period"], tag)
                if value is not None:
                    selected_value = value
                    selected_tag = tag
                    break
            if selected_value is None:
                if not missing_as_zero:
                    return None, f"missing {name} for {expression}"
                selected_value = 0.0
                selected_tag = f"{name} absent; treated as 0"
            values[name] = selected_value
            methods.append(selected_tag)
        return calculator(values), "; ".join(methods)

    return calculate


def duration_expression_first_available(
    components: dict[str, tuple[str, ...]],
    expression: str,
    calculator: Callable[[dict[str, float]], float],
    *,
    missing_as_zero: bool = False,
) -> Callable[[FilingFacts, dict[str, Any], dict[tuple[int, int, str], float]], tuple[float | None, str]]:
    def calculate(
        filing: FilingFacts,
        row: dict[str, Any],
        ytd_history: dict[tuple[int, int, str], float],
    ) -> tuple[float | None, str]:
        values: dict[str, float] = {}
        methods: list[str] = []
        for name, tags in components.items():
            selected_value = None
            selected_method = ""
            for tag in tags:
                value, method = filing.quarter_duration_value(row, tag, ytd_history)
                if value is not None:
                    selected_value = value
                    selected_method = f"{tag}: {method}"
                    break
            if selected_value is None:
                if not missing_as_zero:
                    return None, f"missing {name} for {expression}"
                selected_value = 0.0
                selected_method = f"{name} absent; treated as 0"
            values[name] = selected_value
            methods.append(selected_method)
        return calculator(values), "; ".join(methods)

    return calculate


REVENUE_TAGS = ("us-gaap:Revenues", "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax")
SELLING_MARKETING_TAGS = ("us-gaap:SellingAndMarketingExpense", "us-gaap:MarketingAndAdvertisingExpense")
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


SEC_METRICS = [
    SecMetric("total_assets", "balance_sheet", "instant", "money", "us-gaap:Assets", ("us-gaap:Assets",), direct_instant("us-gaap:Assets")),
    SecMetric("current_assets", "balance_sheet", "instant", "money", "us-gaap:AssetsCurrent", ("us-gaap:AssetsCurrent",), direct_instant("us-gaap:AssetsCurrent")),
    SecMetric(
        "cash_and_equivalents",
        "balance_sheet",
        "instant",
        "money",
        "us-gaap:CashAndCashEquivalentsAtCarryingValue",
        ("us-gaap:CashAndCashEquivalentsAtCarryingValue",),
        direct_instant("us-gaap:CashAndCashEquivalentsAtCarryingValue"),
    ),
    SecMetric("current_investments", "balance_sheet", "instant", "money", "us-gaap:MarketableSecuritiesCurrent", ("us-gaap:MarketableSecuritiesCurrent",), direct_instant("us-gaap:MarketableSecuritiesCurrent")),
    SecMetric(
        "non_current_investments",
        "balance_sheet",
        "instant",
        "money",
        "us-gaap:MarketableSecuritiesNoncurrent",
        ("us-gaap:MarketableSecuritiesNoncurrent",),
        instant_first_available_or_not_comparable(
            ("us-gaap:MarketableSecuritiesNoncurrent",),
            "Alphabet does not disclose a no-dimension MarketableSecuritiesNoncurrent tag in this filing; source provider appears to use a broader investment definition.",
        ),
    ),
    SecMetric(
        "investments",
        "balance_sheet",
        "instant",
        "money",
        "MarketableSecuritiesCurrent + MarketableSecuritiesNoncurrent",
        ("us-gaap:MarketableSecuritiesCurrent", "us-gaap:MarketableSecuritiesNoncurrent"),
        instant_expression_first_available(
            {
                "current": ("us-gaap:MarketableSecuritiesCurrent",),
                "noncurrent": ("us-gaap:MarketableSecuritiesNoncurrent",),
            },
            "MarketableSecuritiesCurrent + MarketableSecuritiesNoncurrent",
            lambda values: values["current"] + values["noncurrent"],
            missing_as_zero=True,
        ),
    ),
    SecMetric(
        "property_plant_and_equipment",
        "balance_sheet",
        "instant",
        "money",
        "PropertyPlantAndEquipmentNet or PropertyPlantAndEquipmentAndFinanceLeaseROU",
        (
            "us-gaap:PropertyPlantAndEquipmentNet",
            "us-gaap:PropertyPlantAndEquipmentAndFinanceLeaseRightOfUseAssetAfterAccumulatedDepreciationAndAmortization",
        ),
        instant_first_available(
            (
                "us-gaap:PropertyPlantAndEquipmentNet",
                "us-gaap:PropertyPlantAndEquipmentAndFinanceLeaseRightOfUseAssetAfterAccumulatedDepreciationAndAmortization",
            )
        ),
    ),
    SecMetric("non_current_assets", "balance_sheet", "instant", "money", "us-gaap:NoncurrentAssets", ("us-gaap:NoncurrentAssets",), direct_instant("us-gaap:NoncurrentAssets")),
    SecMetric(
        "goodwill_and_intangible_assets",
        "balance_sheet",
        "instant",
        "money",
        "Goodwill + FiniteLivedIntangibleAssetsNet",
        ("us-gaap:Goodwill", "us-gaap:FiniteLivedIntangibleAssetsNet"),
        instant_expression_first_available(
            {
                "goodwill": ("us-gaap:Goodwill",),
                "intangibles": ("us-gaap:FiniteLivedIntangibleAssetsNet",),
            },
            "Goodwill + finite-lived intangibles",
            lambda values: values["goodwill"] + values["intangibles"],
            missing_as_zero=True,
        ),
    ),
    SecMetric("total_liabilities", "balance_sheet", "instant", "money", "us-gaap:Liabilities", ("us-gaap:Liabilities",), direct_instant("us-gaap:Liabilities")),
    SecMetric("current_liabilities", "balance_sheet", "instant", "money", "us-gaap:LiabilitiesCurrent", ("us-gaap:LiabilitiesCurrent",), direct_instant("us-gaap:LiabilitiesCurrent")),
    SecMetric("shareholders_equity", "balance_sheet", "instant", "money", "us-gaap:StockholdersEquity", ("us-gaap:StockholdersEquity",), direct_instant("us-gaap:StockholdersEquity")),
    SecMetric("retained_earnings", "balance_sheet", "instant", "money", "us-gaap:RetainedEarningsAccumulatedDeficit", ("us-gaap:RetainedEarningsAccumulatedDeficit",), direct_instant("us-gaap:RetainedEarningsAccumulatedDeficit")),
    SecMetric(
        "accumulated_other_comprehensive_income",
        "balance_sheet",
        "instant",
        "money",
        "us-gaap:AccumulatedOtherComprehensiveIncomeLossNetOfTax",
        ("us-gaap:AccumulatedOtherComprehensiveIncomeLossNetOfTax",),
        direct_instant("us-gaap:AccumulatedOtherComprehensiveIncomeLossNetOfTax"),
    ),
    SecMetric(
        "current_debt",
        "balance_sheet",
        "instant",
        "money",
        "LongTermDebtCurrent + ShortTermBorrowings + FinanceLeaseLiabilityCurrent",
        CURRENT_DEBT_TAGS,
        expression_metric(CURRENT_DEBT_TAGS, "LongTermDebtCurrent + ShortTermBorrowings + FinanceLeaseLiabilityCurrent", lambda values: sum(values.values()), "instant", missing_as_zero=True),
    ),
    SecMetric(
        "non_current_debt",
        "balance_sheet",
        "instant",
        "money",
        "LongTermDebtNoncurrent + FinanceLeaseLiabilityNoncurrent",
        NON_CURRENT_DEBT_TAGS,
        expression_metric(NON_CURRENT_DEBT_TAGS, "LongTermDebtNoncurrent + FinanceLeaseLiabilityNoncurrent", lambda values: sum(values.values()), "instant", missing_as_zero=True),
    ),
    SecMetric(
        "total_debt",
        "balance_sheet",
        "instant",
        "money",
        "current financial debt + noncurrent financial debt",
        (*CURRENT_DEBT_TAGS, *NON_CURRENT_DEBT_TAGS),
        expression_metric((*CURRENT_DEBT_TAGS, *NON_CURRENT_DEBT_TAGS), "current financial debt + noncurrent financial debt", lambda values: sum(values.values()), "instant", missing_as_zero=True),
    ),
    SecMetric("revenue", "income_statement", "duration", "money", "us-gaap:Revenues or RevenueFromContractWithCustomerExcludingAssessedTax", REVENUE_TAGS, duration_metric_first_available(REVENUE_TAGS)),
    SecMetric("cost_of_revenue", "income_statement", "duration", "money", "us-gaap:CostOfRevenue", ("us-gaap:CostOfRevenue",), duration_metric("us-gaap:CostOfRevenue")),
    SecMetric(
        "gross_profit",
        "income_statement",
        "duration",
        "money",
        "Revenue - CostOfRevenue",
        (*REVENUE_TAGS, "us-gaap:CostOfRevenue"),
        duration_expression_first_available(
            {"revenue": REVENUE_TAGS, "cost": ("us-gaap:CostOfRevenue",)},
            "Revenue - CostOfRevenue",
            lambda values: values["revenue"] - values["cost"],
        ),
    ),
    SecMetric(
        "selling_general_and_administrative_expenses",
        "income_statement",
        "duration",
        "money",
        "SellingAndMarketingExpense + GeneralAndAdministrativeExpense",
        (*SELLING_MARKETING_TAGS, "us-gaap:GeneralAndAdministrativeExpense"),
        duration_expression_first_available(
            {"selling_marketing": SELLING_MARKETING_TAGS, "general_admin": ("us-gaap:GeneralAndAdministrativeExpense",)},
            "Selling/marketing + G&A",
            lambda values: values["selling_marketing"] + values["general_admin"],
        ),
    ),
    SecMetric("research_and_development", "income_statement", "duration", "money", "us-gaap:ResearchAndDevelopmentExpense", ("us-gaap:ResearchAndDevelopmentExpense",), duration_metric("us-gaap:ResearchAndDevelopmentExpense")),
    SecMetric(
        "operating_expense",
        "income_statement",
        "duration",
        "money",
        "R&D + Selling/Marketing + G&A",
        ("us-gaap:ResearchAndDevelopmentExpense", *SELLING_MARKETING_TAGS, "us-gaap:GeneralAndAdministrativeExpense"),
        duration_expression_first_available(
            {
                "research": ("us-gaap:ResearchAndDevelopmentExpense",),
                "selling_marketing": SELLING_MARKETING_TAGS,
                "general_admin": ("us-gaap:GeneralAndAdministrativeExpense",),
            },
            "R&D + Selling/Marketing + G&A",
            lambda values: values["research"] + values["selling_marketing"] + values["general_admin"],
        ),
    ),
    SecMetric("operating_income", "income_statement", "duration", "money", "us-gaap:OperatingIncomeLoss", ("us-gaap:OperatingIncomeLoss",), duration_metric("us-gaap:OperatingIncomeLoss")),
    SecMetric("interest_expense", "income_statement", "duration", "money", "us-gaap:InterestExpenseNonoperating or us-gaap:InterestExpense", ("us-gaap:InterestExpenseNonoperating", "us-gaap:InterestExpense"), duration_metric_first_available(("us-gaap:InterestExpenseNonoperating", "us-gaap:InterestExpense"))),
    SecMetric("income_tax_expense", "income_statement", "duration", "money", "us-gaap:IncomeTaxExpenseBenefit", ("us-gaap:IncomeTaxExpenseBenefit",), duration_metric("us-gaap:IncomeTaxExpenseBenefit")),
    SecMetric("net_income", "income_statement", "duration", "money", "us-gaap:NetIncomeLoss", ("us-gaap:NetIncomeLoss",), duration_metric("us-gaap:NetIncomeLoss")),
    SecMetric("earnings_per_share", "income_statement", "duration", "per_share", "us-gaap:EarningsPerShareBasic", ("us-gaap:EarningsPerShareBasic",), direct_duration_only("us-gaap:EarningsPerShareBasic")),
    SecMetric("earnings_per_share_diluted", "income_statement", "duration", "per_share", "us-gaap:EarningsPerShareDiluted", ("us-gaap:EarningsPerShareDiluted",), direct_duration_only("us-gaap:EarningsPerShareDiluted")),
    SecMetric("weighted_average_shares", "income_statement", "duration", "shares", "us-gaap:WeightedAverageNumberOfSharesOutstandingBasic", ("us-gaap:WeightedAverageNumberOfSharesOutstandingBasic",), direct_duration_only_or_skip("us-gaap:WeightedAverageNumberOfSharesOutstandingBasic")),
    SecMetric("weighted_average_shares_diluted", "income_statement", "duration", "shares", "us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding", ("us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding",), direct_duration_only_or_skip("us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding")),
    SecMetric("share_based_compensation", "cash_flow_statement", "duration", "money", "us-gaap:ShareBasedCompensation", ("us-gaap:ShareBasedCompensation",), duration_metric("us-gaap:ShareBasedCompensation")),
    SecMetric("net_cash_flow_from_operations", "cash_flow_statement", "duration", "money", "us-gaap:NetCashProvidedByUsedInOperatingActivities", ("us-gaap:NetCashProvidedByUsedInOperatingActivities",), duration_metric("us-gaap:NetCashProvidedByUsedInOperatingActivities")),
    SecMetric("capital_expenditure", "cash_flow_statement", "duration", "money", "-us-gaap:PaymentsToAcquirePropertyPlantAndEquipment", (CAPEX_TAG,), duration_metric(CAPEX_TAG, sign=-1)),
    SecMetric("net_cash_flow_from_investing", "cash_flow_statement", "duration", "money", "us-gaap:NetCashProvidedByUsedInInvestingActivities", ("us-gaap:NetCashProvidedByUsedInInvestingActivities",), duration_metric("us-gaap:NetCashProvidedByUsedInInvestingActivities")),
    SecMetric("net_cash_flow_from_financing", "cash_flow_statement", "duration", "money", "us-gaap:NetCashProvidedByUsedInFinancingActivities", ("us-gaap:NetCashProvidedByUsedInFinancingActivities",), duration_metric("us-gaap:NetCashProvidedByUsedInFinancingActivities")),
    SecMetric(
        "change_in_cash_and_equivalents",
        "cash_flow_statement",
        "duration",
        "money",
        "us-gaap:CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsPeriodIncreaseDecreaseIncludingExchangeRateEffect",
        ("us-gaap:CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsPeriodIncreaseDecreaseIncludingExchangeRateEffect",),
        duration_metric("us-gaap:CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsPeriodIncreaseDecreaseIncludingExchangeRateEffect"),
    ),
    SecMetric(
        "effect_of_exchange_rate_changes",
        "cash_flow_statement",
        "duration",
        "money",
        "us-gaap:EffectOfExchangeRateOnCashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
        ("us-gaap:EffectOfExchangeRateOnCashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",),
        duration_metric("us-gaap:EffectOfExchangeRateOnCashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"),
    ),
    SecMetric(
        "free_cash_flow",
        "cash_flow_statement",
        "duration",
        "money",
        "NetCashProvidedByUsedInOperatingActivities - PaymentsToAcquirePropertyPlantAndEquipment",
        ("us-gaap:NetCashProvidedByUsedInOperatingActivities", CAPEX_TAG),
        duration_expression_first_available(
            {"ocf": ("us-gaap:NetCashProvidedByUsedInOperatingActivities",), "capex": (CAPEX_TAG,)},
            "OCF - capex",
            lambda values: values["ocf"] - values["capex"],
        ),
    ),
]


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows([{field: row.get(field, "") for field in fields} for row in rows])


def local_sec_html_by_quarter(sec_html_dir: Path) -> dict[str, dict[str, str]]:
    results: dict[str, dict[str, str]] = {}
    for path in sorted(sec_html_dir.glob("goog-*.html")):
        match = re.fullmatch(r"goog-(\d{4})(\d{2})(\d{2})\.html", path.name)
        if not match:
            continue
        report_period = f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
        results[quarter_label(report_period)] = {"report_period": report_period, "path": str(path)}
    return results


def source_value(row: dict[str, Any], metric: str) -> float | None:
    value = row.get(metric)
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def tolerance_for(unit_kind: str) -> float:
    if unit_kind == "per_share":
        return PER_SHARE_TOLERANCE
    if unit_kind == "shares":
        return SHARE_TOLERANCE
    return MONEY_TOLERANCE


def validation_status(metric: str, source: float | None, sec: float | None, tolerance: float, method: str = "") -> str:
    if method.startswith("skipped:"):
        return "skipped"
    if method.startswith("not_comparable:"):
        return "not_comparable"
    if source is None:
        return "missing_source"
    if sec is None:
        return "missing_sec"
    if abs(source - sec) <= tolerance:
        return "match"
    if metric == "capital_expenditure" and abs(abs(source) - abs(sec)) <= tolerance:
        return "sign_mismatch"
    return "mismatch"


def validate(company_rows: list[dict[str, Any]], html_by_quarter: dict[str, dict[str, str]]) -> list[dict[str, Any]]:
    ytd_history: dict[tuple[int, int, str], float] = {}
    rows: list[dict[str, Any]] = []
    filing_cache: dict[Path, FilingFacts] = {}

    for company_row in sorted(company_rows, key=lambda row: row["report_period"]):
        quarter = company_row["quarter"]
        html_info = html_by_quarter.get(quarter)
        if html_info is None:
            rows.extend(missing_filing_rows(company_row))
            continue

        html_path = Path(html_info["path"])
        filing = filing_cache.setdefault(html_path, FilingFacts(html_path))
        fiscal_year, fiscal_quarter = fiscal_year_quarter(company_row["fiscal_period"])

        for metric_def in SEC_METRICS:
            for tag in metric_def.tags:
                if metric_def.value_type == "duration":
                    ytd_value = filing.ytd_value(company_row, tag)
                    if ytd_value is not None:
                        ytd_history[(fiscal_year, fiscal_quarter, tag)] = ytd_value

            sec_value, method = metric_def.calculator(filing, company_row, ytd_history)
            current_value = source_value(company_row, metric_def.metric)
            tolerance = tolerance_for(metric_def.unit_kind)
            difference = None if current_value is None or sec_value is None else current_value - sec_value
            pct_difference = None
            if difference is not None and sec_value not in (None, 0):
                pct_difference = difference / abs(sec_value)

            rows.append(
                {
                    "ticker": TICKER,
                    "source_folder_ticker": SOURCE_FOLDER_TICKER,
                    "quarter": quarter,
                    "report_period": company_row["report_period"],
                    "fiscal_period": company_row["fiscal_period"],
                    "statement": metric_def.statement,
                    "metric": metric_def.metric,
                    "source_value": current_value,
                    "sec_value": sec_value,
                    "difference": difference,
                    "pct_difference": pct_difference,
                    "tolerance": tolerance,
                    "status": validation_status(metric_def.metric, current_value, sec_value, tolerance, method),
                    "sec_method": method,
                    "sec_expression": metric_def.expression,
                    "sec_tags": "|".join(metric_def.tags),
                    "sec_file": str(html_path),
                    "note": note_for(metric_def.metric),
                }
            )
    return rows


def missing_filing_rows(company_row: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for metric_def in SEC_METRICS:
        rows.append(
            {
                "ticker": TICKER,
                "source_folder_ticker": SOURCE_FOLDER_TICKER,
                "quarter": company_row["quarter"],
                "report_period": company_row["report_period"],
                "fiscal_period": company_row["fiscal_period"],
                "statement": metric_def.statement,
                "metric": metric_def.metric,
                "source_value": source_value(company_row, metric_def.metric),
                "sec_value": None,
                "difference": None,
                "pct_difference": None,
                "tolerance": tolerance_for(metric_def.unit_kind),
                "status": "missing_sec",
                "sec_method": "missing SEC HTML filing",
                "sec_expression": metric_def.expression,
                "sec_tags": "|".join(metric_def.tags),
                "sec_file": "",
                "note": note_for(metric_def.metric),
            }
        )
    return rows


def note_for(metric: str) -> str:
    if metric == "capital_expenditure":
        return "SEC value is normalized as a negative investing cash outflow; sign_mismatch means absolute amount matches but source sign differs."
    if metric in {"current_debt", "non_current_debt", "total_debt"}:
        return "Pure financial debt check: current/noncurrent long-term debt and finance lease liabilities; excludes operating lease liabilities."
    if metric in {"current_investments", "non_current_investments", "investments"}:
        return "SEC check uses marketable securities tags only; source provider may include broader investment categories."
    if metric == "property_plant_and_equipment":
        return "SEC check uses pure PP&E/finance lease ROU tags; source provider sometimes maps this field to noncurrent assets or includes operating lease ROU assets."
    return ""


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    status_counts = Counter(row["status"] for row in rows)
    by_metric: dict[str, Counter[str]] = {}
    by_statement: dict[str, Counter[str]] = {}
    largest_mismatches = []

    for row in rows:
        by_metric.setdefault(row["metric"], Counter())
        by_metric[row["metric"]][row["status"]] += 1
        by_statement.setdefault(row["statement"], Counter())
        by_statement[row["statement"]][row["status"]] += 1
        if row["status"] in {"mismatch", "sign_mismatch"} and row["difference"] is not None:
            largest_mismatches.append(row)

    largest_mismatches = sorted(largest_mismatches, key=lambda row: abs(row["difference"]), reverse=True)[:30]
    core_metrics = [
        "cash_and_equivalents",
        "current_investments",
        "net_cash_flow_from_operations",
        "capital_expenditure",
        "free_cash_flow",
        "current_debt",
        "non_current_debt",
        "total_debt",
        "revenue",
        "operating_income",
        "net_income",
    ]

    return {
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "ticker": TICKER,
        "source_folder_ticker": SOURCE_FOLDER_TICKER,
        "rows": len(rows),
        "status_counts": dict(status_counts),
        "by_statement": {statement: dict(counts) for statement, counts in sorted(by_statement.items())},
        "by_metric": {metric: dict(counts) for metric, counts in sorted(by_metric.items())},
        "core_metric_status": {
            metric: dict(Counter(row["status"] for row in rows if row["metric"] == metric))
            for metric in core_metrics
        },
        "largest_mismatches": [
            {
                "quarter": row["quarter"],
                "metric": row["metric"],
                "status": row["status"],
                "source_value": row["source_value"],
                "sec_value": row["sec_value"],
                "difference": row["difference"],
                "sec_expression": row["sec_expression"],
                "note": row["note"],
            }
            for row in largest_mismatches
        ],
    }


def write_readme(output_dir: Path, summary: dict[str, Any]) -> None:
    status_lines = "\n".join(f"- {status}: {count}" for status, count in sorted(summary["status_counts"].items()))
    core_lines = "\n".join(
        f"- {metric}: {counts}"
        for metric, counts in summary["core_metric_status"].items()
    )
    mismatch_lines = "\n".join(
        f"- {row['quarter']} {row['metric']} ({row['status']}): source={format_number(row['source_value'])}, sec={format_number(row['sec_value'])}, diff={format_number(row['difference'])}"
        for row in summary["largest_mismatches"][:12]
    )
    text = f"""# GOOGL SEC HTML Validation

Validation of stored GOOGL financial data against locally archived GOOG SEC inline XBRL HTML filings.

Generated: {summary['generated_at']}

## Status Counts

{status_lines}

## Core Metrics

{core_lines}

## Largest Mismatches

{mismatch_lines or "- None"}

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
"""
    (output_dir / "README.md").write_text(text, encoding="utf-8")


def format_number(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return ""
    return f"{float(value):,.0f}" if abs(float(value)) >= 10 else f"{float(value):,.4f}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--company-path", type=Path, default=DEFAULT_COMPANY_PATH)
    parser.add_argument("--sec-html-dir", type=Path, default=DEFAULT_SEC_HTML_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    company_rows = [row for row in read_json(args.company_path) if row.get("ticker") == TICKER]
    html_by_quarter = local_sec_html_by_quarter(args.sec_html_dir)
    validation_rows = validate(company_rows, html_by_quarter)
    summary = summarize(validation_rows)

    fields = [
        "ticker",
        "source_folder_ticker",
        "quarter",
        "report_period",
        "fiscal_period",
        "statement",
        "metric",
        "source_value",
        "sec_value",
        "difference",
        "pct_difference",
        "tolerance",
        "status",
        "sec_method",
        "sec_expression",
        "sec_tags",
        "sec_file",
        "note",
    ]
    write_json(args.output_dir / "validation_rows.json", validation_rows)
    write_csv(args.output_dir / "validation_rows.csv", validation_rows, fields)
    write_json(args.output_dir / "summary.json", summary)
    write_readme(args.output_dir, summary)

    print(f"Wrote GOOGL SEC HTML validation to {args.output_dir}")
    print("Status counts:", ", ".join(f"{status}={count}" for status, count in sorted(summary["status_counts"].items())))
    return 1 if summary["status_counts"].get("missing_sec") else 0


if __name__ == "__main__":
    raise SystemExit(main())
