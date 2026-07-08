#!/usr/bin/env python3
"""Validate stored Amazon financial rows against locally archived SEC inline XBRL HTML."""

from __future__ import annotations

import argparse
import csv
import html
import json
import math
import re
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Callable

DEFAULT_COMPANY_PATH = Path("data/hyperscaler/companies/AMZN.json")
DEFAULT_DOCUMENT_MANIFEST_PATH = Path("data/hyperscaler/ir_documents/manifest.json")
DEFAULT_OUTPUT_DIR = Path("data/hyperscaler/validation/amzn_sec_html")
TICKER = "AMZN"

ATTR_RE = re.compile(r"([\w:.-]+)\s*=\s*\"([^\"]*)\"")
CONTEXT_RE = re.compile(r"<xbrli:context\b(?P<attrs>[^>]*)>(?P<body>.*?)</xbrli:context>", re.IGNORECASE | re.DOTALL)
FACT_RE = re.compile(r"<ix:nonFraction\b(?P<attrs>[^>]*)>(?P<value>.*?)</ix:nonFraction>", re.IGNORECASE | re.DOTALL)
TAG_RE = re.compile(r"<[^>]+>")

MONEY_TOLERANCE = 1_000_000.0
SHARE_TOLERANCE = 1_000_000.0
PER_SHARE_TOLERANCE = 0.005


@dataclass(frozen=True)
class Context:
    id: str
    start: str | None
    end: str | None
    instant: str | None
    dimensions: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class Fact:
    name: str
    context_ref: str
    value: float
    unit: str
    scale: int
    sign: str
    raw_value: str


@dataclass(frozen=True)
class SecMetric:
    metric: str
    statement: str
    value_type: str
    unit_kind: str
    expression: str
    tags: tuple[str, ...]
    calculator: Callable[["FilingFacts", dict[str, Any], dict[tuple[int, int, str], float]], tuple[float | None, str]]


class FilingFacts:
    def __init__(self, path: Path) -> None:
        self.path = path
        text = path.read_text(encoding="utf-8", errors="replace")
        self.contexts = parse_contexts(text)
        self.facts = parse_facts(text, self.contexts)

    def instant_value(self, report_period: str, tag: str) -> float | None:
        return self._value_for(tag, lambda context: context.instant == report_period)

    def duration_value(self, start: str, end: str, tag: str) -> float | None:
        return self._value_for(tag, lambda context: context.start == start and context.end == end)

    def quarter_duration_value(
        self,
        row: dict[str, Any],
        tag: str,
        ytd_history: dict[tuple[int, int, str], float],
    ) -> tuple[float | None, str]:
        fiscal_year, fiscal_quarter = fiscal_year_quarter(row["fiscal_period"])
        report_period = row["report_period"]
        quarter_start = quarter_start_date(fiscal_year, fiscal_quarter)
        ytd_start = f"{fiscal_year}-01-01"

        direct = self.duration_value(quarter_start, report_period, tag)
        if direct is not None:
            return direct, f"direct quarter {quarter_start} to {report_period}"

        ytd_value = self.duration_value(ytd_start, report_period, tag)
        if ytd_value is None:
            return None, f"missing direct quarter and YTD facts for {tag}"

        if fiscal_quarter == 1:
            return ytd_value, f"Q1 YTD {ytd_start} to {report_period}"

        previous = ytd_history.get((fiscal_year, fiscal_quarter - 1, tag))
        if previous is None:
            return None, f"missing prior YTD fact needed to derive Q{fiscal_quarter}"
        return ytd_value - previous, f"derived from YTD less prior YTD through Q{fiscal_quarter - 1}"

    def ytd_value(self, row: dict[str, Any], tag: str) -> float | None:
        fiscal_year, _ = fiscal_year_quarter(row["fiscal_period"])
        return self.duration_value(f"{fiscal_year}-01-01", row["report_period"], tag)

    def _value_for(self, tag: str, context_predicate: Callable[[Context], bool]) -> float | None:
        values: list[float] = []
        for fact in self.facts:
            if fact.name != tag:
                continue
            context = self.contexts.get(fact.context_ref)
            if not context or context.dimensions or not context_predicate(context):
                continue
            values.append(fact.value)
        return choose_value(values)


def parse_contexts(text: str) -> dict[str, Context]:
    contexts: dict[str, Context] = {}
    for match in CONTEXT_RE.finditer(text):
        attrs = dict(ATTR_RE.findall(match.group("attrs")))
        context_id = attrs.get("id")
        if not context_id:
            continue
        body = match.group("body")
        start = extract_tag_text(body, "xbrli:startDate")
        end = extract_tag_text(body, "xbrli:endDate")
        instant = extract_tag_text(body, "xbrli:instant")
        dimensions = tuple(
            (dimension, TAG_RE.sub("", member).strip())
            for dimension, member in re.findall(
                r"<xbrldi:explicitMember[^>]*dimension=\"([^\"]*)\"[^>]*>(.*?)</xbrldi:explicitMember>",
                body,
                re.IGNORECASE | re.DOTALL,
            )
        )
        contexts[context_id] = Context(context_id, start, end, instant, dimensions)
    return contexts


def parse_facts(text: str, contexts: dict[str, Context]) -> list[Fact]:
    facts: list[Fact] = []
    for match in FACT_RE.finditer(text):
        attrs = dict(ATTR_RE.findall(match.group("attrs")))
        name = attrs.get("name", "")
        context_ref = attrs.get("contextRef", "")
        if not name or context_ref not in contexts:
            continue
        value = parse_numeric_fact(match.group("value"), attrs)
        if value is None:
            continue
        facts.append(
            Fact(
                name=name,
                context_ref=context_ref,
                value=value,
                unit=attrs.get("unitRef", ""),
                scale=int(attrs.get("scale") or 0),
                sign=attrs.get("sign", ""),
                raw_value=TAG_RE.sub("", match.group("value")).strip(),
            )
        )
    return facts


def extract_tag_text(text: str, tag: str) -> str | None:
    match = re.search(rf"<{tag}>(.*?)</{tag}>", text, re.IGNORECASE | re.DOTALL)
    if not match:
        return None
    return html.unescape(TAG_RE.sub("", match.group(1)).strip())


def parse_numeric_fact(value_html: str, attrs: dict[str, str]) -> float | None:
    value_text = html.unescape(TAG_RE.sub("", value_html)).strip()
    value_text = value_text.replace("\u00a0", "").replace("$", "").replace(",", "").strip()
    if value_text in {"", "—", "-", "no", "No"}:
        return 0.0 if value_text in {"—", "-"} else None

    negative = False
    if value_text.startswith("(") and value_text.endswith(")"):
        negative = True
        value_text = value_text[1:-1]

    try:
        value = float(value_text)
    except ValueError:
        return None

    if attrs.get("sign") == "-":
        negative = not negative
    if negative:
        value = -value

    scale = int(attrs.get("scale") or 0)
    return value * (10**scale)


def choose_value(values: list[float]) -> float | None:
    if not values:
        return None

    normalized = [round(value, 6) for value in values]
    counts = Counter(normalized)
    value, _ = counts.most_common(1)[0]
    return float(value)


def fiscal_year_quarter(fiscal_period: str) -> tuple[int, int]:
    match = re.fullmatch(r"(\d{4})-Q([1-4])", fiscal_period)
    if not match:
        raise ValueError(f"Unexpected fiscal period: {fiscal_period}")
    return int(match.group(1)), int(match.group(2))


def quarter_start_date(fiscal_year: int, fiscal_quarter: int) -> str:
    month = {1: 1, 2: 4, 3: 7, 4: 10}[fiscal_quarter]
    return date(fiscal_year, month, 1).isoformat()


def direct_instant(tag: str) -> Callable[[FilingFacts, dict[str, Any], dict[tuple[int, int, str], float]], tuple[float | None, str]]:
    def calculate(filing: FilingFacts, row: dict[str, Any], _: dict[tuple[int, int, str], float]) -> tuple[float | None, str]:
        value = filing.instant_value(row["report_period"], tag)
        return value, f"instant fact at {row['report_period']}"

    return calculate


def duration_metric(tag: str, sign: int = 1) -> Callable[[FilingFacts, dict[str, Any], dict[tuple[int, int, str], float]], tuple[float | None, str]]:
    def calculate(
        filing: FilingFacts,
        row: dict[str, Any],
        ytd_history: dict[tuple[int, int, str], float],
    ) -> tuple[float | None, str]:
        value, method = filing.quarter_duration_value(row, tag, ytd_history)
        if value is None:
            return None, method
        return sign * value, method

    return calculate


def duration_metric_first_available(tags: tuple[str, ...], sign: int = 1) -> Callable[[FilingFacts, dict[str, Any], dict[tuple[int, int, str], float]], tuple[float | None, str]]:
    def calculate(
        filing: FilingFacts,
        row: dict[str, Any],
        ytd_history: dict[tuple[int, int, str], float],
    ) -> tuple[float | None, str]:
        notes: list[str] = []
        for tag in tags:
            value, method = filing.quarter_duration_value(row, tag, ytd_history)
            if value is not None:
                return sign * value, f"{tag}: {method}"
            notes.append(method)
        return None, "; ".join(notes)

    return calculate


def direct_duration_only(tag: str) -> Callable[[FilingFacts, dict[str, Any], dict[tuple[int, int, str], float]], tuple[float | None, str]]:
    def calculate(
        filing: FilingFacts,
        row: dict[str, Any],
        _: dict[tuple[int, int, str], float],
    ) -> tuple[float | None, str]:
        fiscal_year, fiscal_quarter = fiscal_year_quarter(row["fiscal_period"])
        if fiscal_quarter == 4:
            return None, "skipped: 10-K has no reliable standalone Q4 fact for non-additive per-share/share metric"
        quarter_start = quarter_start_date(fiscal_year, fiscal_quarter)
        value = filing.duration_value(quarter_start, row["report_period"], tag)
        return value, f"direct quarter {quarter_start} to {row['report_period']}"

    return calculate


def expression_metric(
    tags: tuple[str, ...],
    expression: str,
    calculator: Callable[[dict[str, float]], float | None],
    period_type: str,
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
        for tag in tags:
            if period_type == "instant":
                value = filing.instant_value(row["report_period"], tag)
                method = f"{tag} instant"
            else:
                value, method = filing.quarter_duration_value(row, tag, ytd_history)
            if value is None:
                if not missing_as_zero:
                    return None, f"missing {tag} for {expression}"
                value = 0.0
                method = f"{tag} absent; treated as 0"
            values[tag] = value
            methods.append(method)
        return calculator(values), "; ".join(methods)

    return calculate


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
    SecMetric(
        "current_investments",
        "balance_sheet",
        "instant",
        "money",
        "us-gaap:MarketableSecuritiesCurrent",
        ("us-gaap:MarketableSecuritiesCurrent",),
        direct_instant("us-gaap:MarketableSecuritiesCurrent"),
    ),
    SecMetric("inventory", "balance_sheet", "instant", "money", "us-gaap:InventoryNet", ("us-gaap:InventoryNet",), direct_instant("us-gaap:InventoryNet")),
    SecMetric(
        "trade_and_non_trade_receivables",
        "balance_sheet",
        "instant",
        "money",
        "us-gaap:AccountsReceivableNetCurrent",
        ("us-gaap:AccountsReceivableNetCurrent",),
        direct_instant("us-gaap:AccountsReceivableNetCurrent"),
    ),
    SecMetric(
        "property_plant_and_equipment",
        "balance_sheet",
        "instant",
        "money",
        "PropertyPlantAndEquipmentAndFinanceLeaseROU + OperatingLeaseRightOfUseAsset",
        ("us-gaap:PropertyPlantAndEquipmentAndFinanceLeaseRightOfUseAssetAfterAccumulatedDepreciationAndAmortization", "us-gaap:OperatingLeaseRightOfUseAsset"),
        expression_metric(
            ("us-gaap:PropertyPlantAndEquipmentAndFinanceLeaseRightOfUseAssetAfterAccumulatedDepreciationAndAmortization", "us-gaap:OperatingLeaseRightOfUseAsset"),
            "PropertyPlantAndEquipmentAndFinanceLeaseROU + OperatingLeaseRightOfUseAsset",
            lambda values: sum(values.values()),
            "instant",
        ),
    ),
    SecMetric("goodwill_and_intangible_assets", "balance_sheet", "instant", "money", "us-gaap:Goodwill", ("us-gaap:Goodwill",), direct_instant("us-gaap:Goodwill")),
    SecMetric(
        "total_liabilities",
        "balance_sheet",
        "instant",
        "money",
        "us-gaap:Assets - us-gaap:StockholdersEquity",
        ("us-gaap:Assets", "us-gaap:StockholdersEquity"),
        expression_metric(
            ("us-gaap:Assets", "us-gaap:StockholdersEquity"),
            "Assets - StockholdersEquity",
            lambda values: values["us-gaap:Assets"] - values["us-gaap:StockholdersEquity"],
            "instant",
        ),
    ),
    SecMetric("current_liabilities", "balance_sheet", "instant", "money", "us-gaap:LiabilitiesCurrent", ("us-gaap:LiabilitiesCurrent",), direct_instant("us-gaap:LiabilitiesCurrent")),
    SecMetric("trade_and_non_trade_payables", "balance_sheet", "instant", "money", "us-gaap:AccountsPayableCurrent", ("us-gaap:AccountsPayableCurrent",), direct_instant("us-gaap:AccountsPayableCurrent")),
    SecMetric(
        "deferred_revenue",
        "balance_sheet",
        "instant",
        "money",
        "us-gaap:ContractWithCustomerLiabilityCurrent",
        ("us-gaap:ContractWithCustomerLiabilityCurrent",),
        direct_instant("us-gaap:ContractWithCustomerLiabilityCurrent"),
    ),
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
    SecMetric("outstanding_shares", "balance_sheet", "instant", "shares", "us-gaap:CommonStockSharesOutstanding", ("us-gaap:CommonStockSharesOutstanding",), direct_instant("us-gaap:CommonStockSharesOutstanding")),
    SecMetric(
        "current_debt",
        "balance_sheet",
        "instant",
        "money",
        "LongTermDebtCurrent + ShortTermBorrowings + FinanceLeaseLiabilityCurrent",
        ("us-gaap:LongTermDebtCurrent", "us-gaap:ShortTermBorrowings", "us-gaap:FinanceLeaseLiabilityCurrent"),
        expression_metric(
            ("us-gaap:LongTermDebtCurrent", "us-gaap:ShortTermBorrowings", "us-gaap:FinanceLeaseLiabilityCurrent"),
            "LongTermDebtCurrent + ShortTermBorrowings + FinanceLeaseLiabilityCurrent",
            lambda values: sum(values.values()),
            "instant",
            missing_as_zero=True,
        ),
    ),
    SecMetric(
        "non_current_debt",
        "balance_sheet",
        "instant",
        "money",
        "LongTermDebtNoncurrent + FinanceLeaseLiabilityNoncurrent",
        ("us-gaap:LongTermDebtNoncurrent", "us-gaap:FinanceLeaseLiabilityNoncurrent"),
        expression_metric(
            ("us-gaap:LongTermDebtNoncurrent", "us-gaap:FinanceLeaseLiabilityNoncurrent"),
            "LongTermDebtNoncurrent + FinanceLeaseLiabilityNoncurrent",
            lambda values: sum(values.values()),
            "instant",
            missing_as_zero=True,
        ),
    ),
    SecMetric(
        "total_debt",
        "balance_sheet",
        "instant",
        "money",
        "LongTermDebtCurrent + ShortTermBorrowings + FinanceLeaseLiabilityCurrent + LongTermDebtNoncurrent + FinanceLeaseLiabilityNoncurrent",
        (
            "us-gaap:LongTermDebtCurrent",
            "us-gaap:ShortTermBorrowings",
            "us-gaap:FinanceLeaseLiabilityCurrent",
            "us-gaap:LongTermDebtNoncurrent",
            "us-gaap:FinanceLeaseLiabilityNoncurrent",
        ),
        expression_metric(
            (
                "us-gaap:LongTermDebtCurrent",
                "us-gaap:ShortTermBorrowings",
                "us-gaap:FinanceLeaseLiabilityCurrent",
                "us-gaap:LongTermDebtNoncurrent",
                "us-gaap:FinanceLeaseLiabilityNoncurrent",
            ),
            "Current financial debt + noncurrent financial debt",
            lambda values: sum(values.values()),
            "instant",
            missing_as_zero=True,
        ),
    ),
    SecMetric("revenue", "income_statement", "duration", "money", "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax", ("us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",), duration_metric("us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax")),
    SecMetric("cost_of_revenue", "income_statement", "duration", "money", "us-gaap:CostOfGoodsAndServicesSold", ("us-gaap:CostOfGoodsAndServicesSold",), duration_metric("us-gaap:CostOfGoodsAndServicesSold")),
    SecMetric(
        "gross_profit",
        "income_statement",
        "duration",
        "money",
        "RevenueFromContractWithCustomerExcludingAssessedTax - CostOfGoodsAndServicesSold",
        ("us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax", "us-gaap:CostOfGoodsAndServicesSold"),
        expression_metric(
            ("us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax", "us-gaap:CostOfGoodsAndServicesSold"),
            "Revenue - CostOfRevenue",
            lambda values: values["us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"] - values["us-gaap:CostOfGoodsAndServicesSold"],
            "duration",
        ),
    ),
    SecMetric("operating_income", "income_statement", "duration", "money", "us-gaap:OperatingIncomeLoss", ("us-gaap:OperatingIncomeLoss",), duration_metric("us-gaap:OperatingIncomeLoss")),
    SecMetric(
        "interest_expense",
        "income_statement",
        "duration",
        "money",
        "us-gaap:InterestExpenseNonoperating or us-gaap:InterestExpense",
        ("us-gaap:InterestExpenseNonoperating", "us-gaap:InterestExpense"),
        duration_metric_first_available(("us-gaap:InterestExpenseNonoperating", "us-gaap:InterestExpense")),
    ),
    SecMetric("income_tax_expense", "income_statement", "duration", "money", "us-gaap:IncomeTaxExpenseBenefit", ("us-gaap:IncomeTaxExpenseBenefit",), duration_metric("us-gaap:IncomeTaxExpenseBenefit")),
    SecMetric("net_income", "income_statement", "duration", "money", "us-gaap:NetIncomeLoss", ("us-gaap:NetIncomeLoss",), duration_metric("us-gaap:NetIncomeLoss")),
    SecMetric("earnings_per_share", "income_statement", "duration", "per_share", "us-gaap:EarningsPerShareBasic", ("us-gaap:EarningsPerShareBasic",), direct_duration_only("us-gaap:EarningsPerShareBasic")),
    SecMetric("earnings_per_share_diluted", "income_statement", "duration", "per_share", "us-gaap:EarningsPerShareDiluted", ("us-gaap:EarningsPerShareDiluted",), direct_duration_only("us-gaap:EarningsPerShareDiluted")),
    SecMetric("weighted_average_shares", "income_statement", "duration", "shares", "us-gaap:WeightedAverageNumberOfSharesOutstandingBasic", ("us-gaap:WeightedAverageNumberOfSharesOutstandingBasic",), direct_duration_only("us-gaap:WeightedAverageNumberOfSharesOutstandingBasic")),
    SecMetric("weighted_average_shares_diluted", "income_statement", "duration", "shares", "us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding", ("us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding",), direct_duration_only("us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding")),
    SecMetric("depreciation_and_amortization", "cash_flow_statement", "duration", "money", "us-gaap:DepreciationDepletionAndAmortization", ("us-gaap:DepreciationDepletionAndAmortization",), duration_metric("us-gaap:DepreciationDepletionAndAmortization")),
    SecMetric("share_based_compensation", "cash_flow_statement", "duration", "money", "us-gaap:ShareBasedCompensation", ("us-gaap:ShareBasedCompensation",), duration_metric("us-gaap:ShareBasedCompensation")),
    SecMetric("net_cash_flow_from_operations", "cash_flow_statement", "duration", "money", "us-gaap:NetCashProvidedByUsedInOperatingActivities", ("us-gaap:NetCashProvidedByUsedInOperatingActivities",), duration_metric("us-gaap:NetCashProvidedByUsedInOperatingActivities")),
    SecMetric("capital_expenditure", "cash_flow_statement", "duration", "money", "-us-gaap:PaymentsToAcquireProductiveAssets", ("us-gaap:PaymentsToAcquireProductiveAssets",), duration_metric("us-gaap:PaymentsToAcquireProductiveAssets", sign=-1)),
    SecMetric("net_cash_flow_from_investing", "cash_flow_statement", "duration", "money", "us-gaap:NetCashProvidedByUsedInInvestingActivities", ("us-gaap:NetCashProvidedByUsedInInvestingActivities",), duration_metric("us-gaap:NetCashProvidedByUsedInInvestingActivities")),
    SecMetric("net_cash_flow_from_financing", "cash_flow_statement", "duration", "money", "us-gaap:NetCashProvidedByUsedInFinancingActivities", ("us-gaap:NetCashProvidedByUsedInFinancingActivities",), duration_metric("us-gaap:NetCashProvidedByUsedInFinancingActivities")),
    SecMetric(
        "effect_of_exchange_rate_changes",
        "cash_flow_statement",
        "duration",
        "money",
        "us-gaap:EffectOfExchangeRateOnCashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsIncludingDisposalGroupAndDiscontinuedOperations",
        ("us-gaap:EffectOfExchangeRateOnCashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsIncludingDisposalGroupAndDiscontinuedOperations",),
        duration_metric("us-gaap:EffectOfExchangeRateOnCashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsIncludingDisposalGroupAndDiscontinuedOperations"),
    ),
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
        "free_cash_flow",
        "cash_flow_statement",
        "duration",
        "money",
        "NetCashProvidedByUsedInOperatingActivities - PaymentsToAcquireProductiveAssets",
        ("us-gaap:NetCashProvidedByUsedInOperatingActivities", "us-gaap:PaymentsToAcquireProductiveAssets"),
        expression_metric(
            ("us-gaap:NetCashProvidedByUsedInOperatingActivities", "us-gaap:PaymentsToAcquireProductiveAssets"),
            "OCF - capex",
            lambda values: values["us-gaap:NetCashProvidedByUsedInOperatingActivities"] - values["us-gaap:PaymentsToAcquireProductiveAssets"],
            "duration",
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


def local_sec_html_by_quarter(manifest_path: Path) -> dict[str, Path]:
    rows = read_json(manifest_path)
    paths: dict[str, Path] = {}
    for row in rows:
        if row.get("ticker") == TICKER and row.get("document_kind") == "sec_filing_html" and row.get("status") == "downloaded":
            paths[row["quarter"]] = Path(row["local_path"])
    return paths


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


def validation_status(source: float | None, sec: float | None, tolerance: float, method: str = "") -> str:
    if method.startswith("skipped:"):
        return "skipped"
    if source is None:
        return "missing_source"
    if sec is None:
        return "missing_sec"
    return "match" if abs(source - sec) <= tolerance else "mismatch"


def validate(company_rows: list[dict[str, Any]], html_paths: dict[str, Path]) -> list[dict[str, Any]]:
    ytd_history: dict[tuple[int, int, str], float] = {}
    rows: list[dict[str, Any]] = []
    filing_cache: dict[Path, FilingFacts] = {}

    for company_row in sorted(company_rows, key=lambda row: row["report_period"]):
        quarter = company_row["quarter"]
        html_path = html_paths.get(quarter)
        if html_path is None:
            rows.extend(missing_filing_rows(company_row))
            continue

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
                    "status": validation_status(current_value, sec_value, tolerance, method),
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
    if metric == "current_debt":
        return "Pure financial debt: current long-term debt, short-term borrowings, and current finance lease liability; excludes operating lease liability and Amazon financing obligations."
    if metric == "non_current_debt":
        return "Pure financial debt: noncurrent long-term debt and noncurrent finance lease liability; excludes operating lease liability and Amazon financing obligations."
    if metric == "total_debt":
        return "Pure financial debt: current_debt + non_current_debt; excludes operating lease liability and Amazon financing obligations."
    if metric == "goodwill_and_intangible_assets":
        return "Amazon SEC tag used here is Goodwill; source field name is broader than the observed Amazon tag."
    return ""


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    status_counts = Counter(row["status"] for row in rows)
    by_metric: dict[str, dict[str, int]] = {}
    by_statement: dict[str, dict[str, int]] = {}
    largest_mismatches = []

    for row in rows:
        by_metric.setdefault(row["metric"], Counter())
        by_metric[row["metric"]][row["status"]] += 1
        by_statement.setdefault(row["statement"], Counter())
        by_statement[row["statement"]][row["status"]] += 1
        if row["status"] == "mismatch" and row["difference"] is not None:
            largest_mismatches.append(row)

    largest_mismatches = sorted(largest_mismatches, key=lambda row: abs(row["difference"]), reverse=True)[:20]

    return {
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "ticker": TICKER,
        "rows": len(rows),
        "status_counts": dict(status_counts),
        "by_statement": {statement: dict(counts) for statement, counts in sorted(by_statement.items())},
        "by_metric": {metric: dict(counts) for metric, counts in sorted(by_metric.items())},
        "largest_mismatches": [
            {
                "quarter": row["quarter"],
                "metric": row["metric"],
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
    mismatch_lines = "\n".join(
        f"- {row['quarter']} {row['metric']}: source={format_number(row['source_value'])}, sec={format_number(row['sec_value'])}, diff={format_number(row['difference'])}"
        for row in summary["largest_mismatches"][:10]
    )
    text = f"""# AMZN SEC HTML Validation

Validation of stored AMZN financial data against locally archived SEC inline XBRL HTML filings.

Generated: {summary['generated_at']}

## Status Counts

{status_lines}

## Largest Mismatches

{mismatch_lines or "- None"}

## Files

- `validation_rows.csv` and `validation_rows.json`: metric-level comparisons.
- `summary.json`: aggregate counts and largest mismatches.

## Method

- Balance sheet metrics use no-dimension instant XBRL facts at each report period.
- Income statement and cash flow metrics use exact quarterly duration facts when available.
- When SEC filings only provide year-to-date cash flow or annual 10-K facts, quarter values are derived by subtracting the prior YTD period.
- Money and share values allow a 1 million tolerance because Amazon reports most SEC facts rounded to millions.
"""
    (output_dir / "README.md").write_text(text, encoding="utf-8")


def format_number(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return ""
    return f"{value:,.0f}" if abs(float(value)) >= 10 else f"{value:,.4f}"


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--company-path", type=Path, default=DEFAULT_COMPANY_PATH)
    parser.add_argument("--manifest-path", type=Path, default=DEFAULT_DOCUMENT_MANIFEST_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    company_rows = [row for row in read_json(args.company_path) if row.get("ticker") == TICKER]
    html_paths = local_sec_html_by_quarter(args.manifest_path)
    validation_rows = validate(company_rows, html_paths)
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

    print(f"Wrote AMZN SEC HTML validation to {args.output_dir}")
    print("Status counts:", ", ".join(f"{status}={count}" for status, count in sorted(summary["status_counts"].items())))
    return 1 if summary["status_counts"].get("missing_sec") else 0


if __name__ == "__main__":
    raise SystemExit(main())
