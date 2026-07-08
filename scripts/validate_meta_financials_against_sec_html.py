#!/usr/bin/env python3
"""Validate stored META financial rows against locally archived SEC inline XBRL HTML."""

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

TICKER = "META"
DEFAULT_COMPANY_PATH = Path("data/hyperscaler/companies/META.json")
DEFAULT_SEC_HTML_DIR = Path("data/hyperscaler/ir_documents/originals/META/sec_filing_html")
DEFAULT_OUTPUT_DIR = Path("data/hyperscaler/validation/meta_sec_html")

MONEY_TOLERANCE = 1_000_000.0
SHARE_TOLERANCE = 1_000_000.0
PER_SHARE_TOLERANCE = 0.005


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


def instant_first_available_or_skip(
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
        return None, f"skipped: {reason}"

    return calculate


def duration_first_available_or_not_comparable(
    tags: tuple[str, ...],
    reason: str,
) -> Callable[[FilingFacts, dict[str, Any], dict[tuple[int, int, str], float]], tuple[float | None, str]]:
    def calculate(
        filing: FilingFacts,
        row: dict[str, Any],
        ytd_history: dict[tuple[int, int, str], float],
    ) -> tuple[float | None, str]:
        notes: list[str] = []
        for tag in tags:
            value, method = filing.quarter_duration_value(row, tag, ytd_history)
            if value is not None:
                return value, f"{tag}: {method}"
            notes.append(method)
        return None, f"not_comparable: {reason}; {'; '.join(notes)}"

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


REVENUE_TAGS = ("us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax", "us-gaap:Revenues")
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
NON_CURRENT_INVESTMENT_TAGS = (
    "meta:NonmarketableEquitySecuritiesCarryingValue",
    "us-gaap:EquityMethodInvestments",
    "us-gaap:MarketableSecuritiesNoncurrent",
)
PPE_TAGS = (
    "us-gaap:PropertyPlantAndEquipmentAndFinanceLeaseRightOfUseAssetAfterAccumulatedDepreciationAndAmortization",
    "us-gaap:PropertyPlantAndEquipmentNet",
)
CHANGE_IN_CASH_TAG = "us-gaap:CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsPeriodIncreaseDecreaseIncludingExchangeRateEffect"


SEC_METRICS = [
    SecMetric("total_assets", "balance_sheet", "instant", "money", "us-gaap:Assets", ("us-gaap:Assets",), direct_instant("us-gaap:Assets")),
    SecMetric("current_assets", "balance_sheet", "instant", "money", "us-gaap:AssetsCurrent", ("us-gaap:AssetsCurrent",), direct_instant("us-gaap:AssetsCurrent")),
    SecMetric("cash_and_equivalents", "balance_sheet", "instant", "money", "us-gaap:CashAndCashEquivalentsAtCarryingValue", ("us-gaap:CashAndCashEquivalentsAtCarryingValue",), direct_instant("us-gaap:CashAndCashEquivalentsAtCarryingValue")),
    SecMetric("current_investments", "balance_sheet", "instant", "money", "us-gaap:MarketableSecuritiesCurrent", ("us-gaap:MarketableSecuritiesCurrent",), direct_instant("us-gaap:MarketableSecuritiesCurrent")),
    SecMetric("non_current_investments", "balance_sheet", "instant", "money", "nonmarketable/equity-method investments", NON_CURRENT_INVESTMENT_TAGS, instant_first_available(NON_CURRENT_INVESTMENT_TAGS)),
    SecMetric(
        "investments",
        "balance_sheet",
        "instant",
        "money",
        "MarketableSecuritiesCurrent + nonmarketable/equity-method investments",
        ("us-gaap:MarketableSecuritiesCurrent", *NON_CURRENT_INVESTMENT_TAGS),
        instant_expression_first_available(
            {
                "current": ("us-gaap:MarketableSecuritiesCurrent",),
                "noncurrent": NON_CURRENT_INVESTMENT_TAGS,
            },
            "current marketable securities + noncurrent investments",
            lambda values: values["current"] + values["noncurrent"],
            missing_as_zero=True,
        ),
    ),
    SecMetric("property_plant_and_equipment", "balance_sheet", "instant", "money", "PP&E and finance lease ROU asset", PPE_TAGS, instant_first_available(PPE_TAGS)),
    SecMetric(
        "non_current_assets",
        "balance_sheet",
        "instant",
        "money",
        "Assets - AssetsCurrent",
        ("us-gaap:Assets", "us-gaap:AssetsCurrent"),
        instant_expression_first_available(
            {"assets": ("us-gaap:Assets",), "current": ("us-gaap:AssetsCurrent",)},
            "Assets - AssetsCurrent",
            lambda values: values["assets"] - values["current"],
        ),
    ),
    SecMetric(
        "goodwill_and_intangible_assets",
        "balance_sheet",
        "instant",
        "money",
        "Goodwill + finite-lived intangible assets",
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
    SecMetric(
        "non_current_liabilities",
        "balance_sheet",
        "instant",
        "money",
        "Liabilities - LiabilitiesCurrent",
        ("us-gaap:Liabilities", "us-gaap:LiabilitiesCurrent"),
        instant_expression_first_available(
            {"liabilities": ("us-gaap:Liabilities",), "current": ("us-gaap:LiabilitiesCurrent",)},
            "Liabilities - LiabilitiesCurrent",
            lambda values: values["liabilities"] - values["current"],
        ),
    ),
    SecMetric("shareholders_equity", "balance_sheet", "instant", "money", "us-gaap:StockholdersEquity", ("us-gaap:StockholdersEquity",), direct_instant("us-gaap:StockholdersEquity")),
    SecMetric("retained_earnings", "balance_sheet", "instant", "money", "us-gaap:RetainedEarningsAccumulatedDeficit", ("us-gaap:RetainedEarningsAccumulatedDeficit",), direct_instant("us-gaap:RetainedEarningsAccumulatedDeficit")),
    SecMetric("accumulated_other_comprehensive_income", "balance_sheet", "instant", "money", "us-gaap:AccumulatedOtherComprehensiveIncomeLossNetOfTax", ("us-gaap:AccumulatedOtherComprehensiveIncomeLossNetOfTax",), direct_instant("us-gaap:AccumulatedOtherComprehensiveIncomeLossNetOfTax")),
    SecMetric("outstanding_shares", "balance_sheet", "instant", "shares", "us-gaap:CommonStockSharesOutstanding", ("us-gaap:CommonStockSharesOutstanding",), instant_first_available_or_skip(("us-gaap:CommonStockSharesOutstanding",), "Meta reports common shares by class/dimension rather than as one consolidated no-dimension instant fact.")),
    SecMetric("current_debt", "balance_sheet", "instant", "money", "LongTermDebtCurrent + ShortTermBorrowings + FinanceLeaseLiabilityCurrent", CURRENT_DEBT_TAGS, expression_metric(CURRENT_DEBT_TAGS, "current financial debt", lambda values: sum(values.values()), "instant", missing_as_zero=True)),
    SecMetric("non_current_debt", "balance_sheet", "instant", "money", "LongTermDebtNoncurrent + FinanceLeaseLiabilityNoncurrent", NON_CURRENT_DEBT_TAGS, expression_metric(NON_CURRENT_DEBT_TAGS, "noncurrent financial debt", lambda values: sum(values.values()), "instant", missing_as_zero=True)),
    SecMetric("total_debt", "balance_sheet", "instant", "money", "current financial debt + noncurrent financial debt", (*CURRENT_DEBT_TAGS, *NON_CURRENT_DEBT_TAGS), expression_metric((*CURRENT_DEBT_TAGS, *NON_CURRENT_DEBT_TAGS), "total financial debt", lambda values: sum(values.values()), "instant", missing_as_zero=True)),
    SecMetric("revenue", "income_statement", "duration", "money", "RevenueFromContractWithCustomerExcludingAssessedTax or Revenues", REVENUE_TAGS, duration_metric_first_available(REVENUE_TAGS)),
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
    SecMetric("research_and_development", "income_statement", "duration", "money", "us-gaap:ResearchAndDevelopmentExpense", ("us-gaap:ResearchAndDevelopmentExpense",), duration_metric("us-gaap:ResearchAndDevelopmentExpense")),
    SecMetric(
        "selling_general_and_administrative_expenses",
        "income_statement",
        "duration",
        "money",
        "SellingAndMarketingExpense + GeneralAndAdministrativeExpense",
        ("us-gaap:SellingAndMarketingExpense", "us-gaap:GeneralAndAdministrativeExpense"),
        duration_expression_first_available(
            {
                "selling_marketing": ("us-gaap:SellingAndMarketingExpense",),
                "general_admin": ("us-gaap:GeneralAndAdministrativeExpense",),
            },
            "Selling/marketing + G&A",
            lambda values: values["selling_marketing"] + values["general_admin"],
        ),
    ),
    SecMetric(
        "operating_expense",
        "income_statement",
        "duration",
        "money",
        "CostOfRevenue + R&D + Selling/Marketing + G&A",
        ("us-gaap:CostOfRevenue", "us-gaap:ResearchAndDevelopmentExpense", "us-gaap:SellingAndMarketingExpense", "us-gaap:GeneralAndAdministrativeExpense"),
        duration_expression_first_available(
            {
                "cost": ("us-gaap:CostOfRevenue",),
                "research": ("us-gaap:ResearchAndDevelopmentExpense",),
                "selling_marketing": ("us-gaap:SellingAndMarketingExpense",),
                "general_admin": ("us-gaap:GeneralAndAdministrativeExpense",),
            },
            "CostOfRevenue + R&D + Selling/Marketing + G&A",
            lambda values: values["cost"] + values["research"] + values["selling_marketing"] + values["general_admin"],
        ),
    ),
    SecMetric("operating_income", "income_statement", "duration", "money", "us-gaap:OperatingIncomeLoss", ("us-gaap:OperatingIncomeLoss",), duration_metric("us-gaap:OperatingIncomeLoss")),
    SecMetric("interest_expense", "income_statement", "duration", "money", "us-gaap:InterestExpenseNonoperating or us-gaap:InterestExpense", ("us-gaap:InterestExpenseNonoperating", "us-gaap:InterestExpense"), duration_first_available_or_not_comparable(("us-gaap:InterestExpenseNonoperating", "us-gaap:InterestExpense"), "Meta often reports interest within interest and other income (expense), net rather than a standalone no-dimension interest expense fact.")),
    SecMetric("income_tax_expense", "income_statement", "duration", "money", "us-gaap:IncomeTaxExpenseBenefit", ("us-gaap:IncomeTaxExpenseBenefit",), duration_metric("us-gaap:IncomeTaxExpenseBenefit")),
    SecMetric("net_income", "income_statement", "duration", "money", "us-gaap:NetIncomeLoss", ("us-gaap:NetIncomeLoss",), duration_metric("us-gaap:NetIncomeLoss")),
    SecMetric("earnings_per_share", "income_statement", "duration", "per_share", "us-gaap:EarningsPerShareBasic", ("us-gaap:EarningsPerShareBasic",), direct_duration_only("us-gaap:EarningsPerShareBasic")),
    SecMetric("earnings_per_share_diluted", "income_statement", "duration", "per_share", "us-gaap:EarningsPerShareDiluted", ("us-gaap:EarningsPerShareDiluted",), direct_duration_only("us-gaap:EarningsPerShareDiluted")),
    SecMetric("weighted_average_shares", "income_statement", "duration", "shares", "us-gaap:WeightedAverageNumberOfSharesOutstandingBasic", ("us-gaap:WeightedAverageNumberOfSharesOutstandingBasic",), direct_duration_only("us-gaap:WeightedAverageNumberOfSharesOutstandingBasic")),
    SecMetric("weighted_average_shares_diluted", "income_statement", "duration", "shares", "us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding", ("us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding",), direct_duration_only("us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding")),
    SecMetric("net_income", "cash_flow_statement", "duration", "money", "us-gaap:NetIncomeLoss", ("us-gaap:NetIncomeLoss",), duration_metric("us-gaap:NetIncomeLoss")),
    SecMetric("depreciation_and_amortization", "cash_flow_statement", "duration", "money", "us-gaap:DepreciationDepletionAndAmortization", ("us-gaap:DepreciationDepletionAndAmortization",), duration_metric("us-gaap:DepreciationDepletionAndAmortization")),
    SecMetric("share_based_compensation", "cash_flow_statement", "duration", "money", "us-gaap:ShareBasedCompensation", ("us-gaap:ShareBasedCompensation",), duration_metric("us-gaap:ShareBasedCompensation")),
    SecMetric("net_cash_flow_from_operations", "cash_flow_statement", "duration", "money", "us-gaap:NetCashProvidedByUsedInOperatingActivities", ("us-gaap:NetCashProvidedByUsedInOperatingActivities",), duration_metric("us-gaap:NetCashProvidedByUsedInOperatingActivities")),
    SecMetric("capital_expenditure", "cash_flow_statement", "duration", "money", "-us-gaap:PaymentsToAcquirePropertyPlantAndEquipment", (CAPEX_TAG,), duration_metric(CAPEX_TAG, sign=-1)),
    SecMetric("business_acquisitions_and_disposals", "cash_flow_statement", "duration", "money", "business and intangible asset acquisitions", ("meta:PaymentsToAcquireBusinessesNetOfCashAcquiredAndPurchasesOfIntangibleAndOtherAssets", "us-gaap:PaymentsToAcquireBusinessesNetOfCashAcquired"), duration_metric_first_available(("meta:PaymentsToAcquireBusinessesNetOfCashAcquiredAndPurchasesOfIntangibleAndOtherAssets", "us-gaap:PaymentsToAcquireBusinessesNetOfCashAcquired"), sign=-1)),
    SecMetric(
        "investment_acquisitions_and_disposals",
        "cash_flow_statement",
        "duration",
        "money",
        "ProceedsFromSaleAndMaturityOfAvailableForSaleSecurities - PaymentsToAcquireAvailableForSaleSecuritiesDebt",
        ("us-gaap:ProceedsFromSaleAndMaturityOfAvailableForSaleSecurities", "us-gaap:PaymentsToAcquireAvailableForSaleSecuritiesDebt"),
        duration_expression_first_available(
            {
                "proceeds": ("us-gaap:ProceedsFromSaleAndMaturityOfAvailableForSaleSecurities",),
                "purchases": ("us-gaap:PaymentsToAcquireAvailableForSaleSecuritiesDebt",),
            },
            "sales/maturities less purchases of AFS securities",
            lambda values: values["proceeds"] - values["purchases"],
            missing_as_zero=True,
        ),
    ),
    SecMetric("net_cash_flow_from_investing", "cash_flow_statement", "duration", "money", "us-gaap:NetCashProvidedByUsedInInvestingActivities", ("us-gaap:NetCashProvidedByUsedInInvestingActivities",), duration_metric("us-gaap:NetCashProvidedByUsedInInvestingActivities")),
    SecMetric("issuance_or_purchase_of_equity_shares", "cash_flow_statement", "duration", "money", "-us-gaap:PaymentsForRepurchaseOfCommonStock", ("us-gaap:PaymentsForRepurchaseOfCommonStock",), duration_metric("us-gaap:PaymentsForRepurchaseOfCommonStock", sign=-1)),
    SecMetric(
        "dividends_and_other_cash_distributions",
        "cash_flow_statement",
        "duration",
        "money",
        "-PaymentsOfDividends",
        ("us-gaap:PaymentsOfDividends", "us-gaap:PaymentsOfDividendsCommonStock"),
        duration_expression_first_available(
            {"dividends": ("us-gaap:PaymentsOfDividends", "us-gaap:PaymentsOfDividendsCommonStock")},
            "cash dividends paid",
            lambda values: -values["dividends"],
            missing_as_zero=True,
        ),
    ),
    SecMetric("net_cash_flow_from_financing", "cash_flow_statement", "duration", "money", "us-gaap:NetCashProvidedByUsedInFinancingActivities", ("us-gaap:NetCashProvidedByUsedInFinancingActivities",), duration_metric("us-gaap:NetCashProvidedByUsedInFinancingActivities")),
    SecMetric("change_in_cash_and_equivalents", "cash_flow_statement", "duration", "money", CHANGE_IN_CASH_TAG, (CHANGE_IN_CASH_TAG,), duration_metric(CHANGE_IN_CASH_TAG)),
    SecMetric("effect_of_exchange_rate_changes", "cash_flow_statement", "duration", "money", "us-gaap:EffectOfExchangeRateOnCashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents", ("us-gaap:EffectOfExchangeRateOnCashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",), duration_metric("us-gaap:EffectOfExchangeRateOnCashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents")),
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
    for path in sorted(sec_html_dir.glob("META_*_sec_filing_html_*.html")):
        match = re.fullmatch(r"META_(\d{4}Q[1-4])_(\d{4}-Q[1-4])_sec_filing_html_(10-[qk])\.html", path.name, re.IGNORECASE)
        if not match:
            continue
        results[match.group(1)] = {
            "fiscal_period": match.group(2),
            "form_type": match.group(3).upper(),
            "path": str(path),
        }
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
        return "SEC check uses marketable securities plus nonmarketable/equity-method investment tags; source provider definitions may be broader."
    if metric == "property_plant_and_equipment":
        return "SEC check uses PP&E and finance lease ROU asset after accumulated depreciation/amortization."
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
        "investments",
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
    core_lines = "\n".join(f"- {metric}: {counts}" for metric, counts in summary["core_metric_status"].items())
    mismatch_lines = "\n".join(
        f"- {row['quarter']} {row['metric']} ({row['status']}): source={format_number(row['source_value'])}, sec={format_number(row['sec_value'])}, diff={format_number(row['difference'])}"
        for row in summary["largest_mismatches"][:12]
    )
    text = f"""# META SEC HTML Validation

Validation of stored META financial data against locally archived Meta SEC inline XBRL HTML filings.

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

- Stored `META` data is checked against local SEC filing HTML files in `data/hyperscaler/ir_documents/originals/META/sec_filing_html`.
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

    print(f"Wrote META SEC HTML validation to {args.output_dir}")
    print("Status counts:", ", ".join(f"{status}={count}" for status, count in sorted(summary["status_counts"].items())))
    missing_filing = any(row["sec_method"] == "missing SEC HTML filing" for row in validation_rows)
    return 1 if missing_filing else 0


if __name__ == "__main__":
    raise SystemExit(main())
