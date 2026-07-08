import csv
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.fetch_hyperscaler_data import (
    BALANCE_SHEET_FIELDS,
    CASH_FLOW_FIELDS,
    INCOME_STATEMENT_FIELDS,
    api_get,
    build_panel,
    export_dataset,
    export_financials_source,
    fetch_financials_history,
    fetch_statement_history,
    main,
    normalize_ytd_cash_flow_statements,
    patch_amzn_capex_from_sec_companyfacts,
    patch_free_cash_flow_from_ocf_and_capex,
    pivot_metric,
    quarter_label,
)


class HyperscalerDataTests(unittest.TestCase):
    def test_api_get_sends_explicit_user_agent(self):
        captured = {}

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_value, traceback):
                return False

            def read(self):
                return b'{"ok": true}'

        def fake_urlopen(request, timeout):
            captured["user_agent"] = request.get_header("User-agent")
            return FakeResponse()

        with patch("scripts.fetch_hyperscaler_data.urllib.request.urlopen", fake_urlopen):
            self.assertEqual(api_get("/test", "api-key", {"ticker": "MSFT"}), {"ok": True})

        self.assertTrue(captured["user_agent"])
        self.assertIn("investing-research", captured["user_agent"])

    def test_fetch_statement_history_pages_until_requested_limit(self):
        calls = []
        pages = [
            {
                "balance_sheets": [
                    {"report_period": "2026-03-31", "ticker": "MSFT"},
                    {"report_period": "2025-12-31", "ticker": "MSFT"},
                ]
            },
            {
                "balance_sheets": [
                    {"report_period": "2025-09-30", "ticker": "MSFT"},
                    {"report_period": "2025-06-30", "ticker": "MSFT"},
                ]
            },
        ]

        def fake_api_get(path, api_key, params):
            calls.append(params.copy())
            return pages[len(calls) - 1]

        with patch("scripts.fetch_hyperscaler_data.api_get", fake_api_get):
            rows = fetch_statement_history(
                "api-key",
                "/financials/balance-sheets",
                "balance_sheets",
                "MSFT",
                "quarterly",
                3,
            )

        self.assertEqual([row["report_period"] for row in rows], ["2026-03-31", "2025-12-31", "2025-09-30"])
        self.assertIsNone(calls[0].get("report_period_lt"))
        self.assertEqual(calls[1]["report_period_lt"], "2025-12-31")

    def test_fetch_financials_history_uses_all_financials_endpoint(self):
        calls = []

        def fake_api_get(path, api_key, params):
            calls.append((path, params.copy()))
            return {
                "financials": {
                    "balance_sheets": [
                        {
                            "ticker": "MSFT",
                            "report_period": "2026-03-31",
                            "total_assets": 100,
                        }
                    ],
                    "cash_flow_statements": [
                        {
                            "ticker": "MSFT",
                            "report_period": "2026-03-31",
                            "capital_expenditure": -10,
                        }
                    ],
                    "income_statements": [
                        {
                            "ticker": "MSFT",
                            "report_period": "2026-03-31",
                            "revenue": 200,
                        }
                    ],
                }
            }

        with patch("scripts.fetch_hyperscaler_data.api_get", fake_api_get):
            balance_sheets, cash_flows, income_statements = fetch_financials_history(
                "api-key",
                "MSFT",
                "quarterly",
                1,
            )

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], "/financials")
        self.assertEqual(balance_sheets[0]["total_assets"], 100)
        self.assertEqual(cash_flows[0]["capital_expenditure"], -10)
        self.assertEqual(income_statements[0]["revenue"], 200)

    def test_fetch_financials_history_does_not_request_empty_older_page_when_first_page_is_short(self):
        calls = []

        def fake_api_get(path, api_key, params):
            calls.append((path, params.copy()))
            return {
                "financials": {
                    "balance_sheets": [{"ticker": "MSFT", "report_period": "2026-03-31"}],
                    "cash_flow_statements": [{"ticker": "MSFT", "report_period": "2026-03-31"}],
                    "income_statements": [{"ticker": "MSFT", "report_period": "2026-03-31"}],
                }
            }

        with patch("scripts.fetch_hyperscaler_data.api_get", fake_api_get):
            fetch_financials_history("api-key", "MSFT", "quarterly", 20)

        self.assertEqual(len(calls), 1)

    def test_main_fetches_all_financials_once_per_ticker(self):
        calls = []

        def fake_api_get(path, api_key, params):
            calls.append((path, params.copy()))
            return {
                "financials": {
                    "balance_sheets": [
                        {
                            "ticker": params["ticker"],
                            "report_period": "2026-03-31",
                            "fiscal_period": "2026-Q1",
                            "period": "quarterly",
                            "currency": "USD",
                            **{field: 1 for field in BALANCE_SHEET_FIELDS},
                        }
                    ],
                    "cash_flow_statements": [
                        {
                            "ticker": params["ticker"],
                            "report_period": "2026-03-31",
                            "fiscal_period": "2026-Q1",
                            "period": "quarterly",
                            "currency": "USD",
                            **{field: 1 for field in CASH_FLOW_FIELDS},
                        }
                    ],
                    "income_statements": [
                        {
                            "ticker": params["ticker"],
                            "report_period": "2026-03-31",
                            "fiscal_period": "2026-Q1",
                            "period": "quarterly",
                            "currency": "USD",
                            **{field: 1 for field in INCOME_STATEMENT_FIELDS},
                        }
                    ],
                }
            }

        with tempfile.TemporaryDirectory() as directory:
            with (
                patch("scripts.fetch_hyperscaler_data.api_get", fake_api_get),
                patch("scripts.fetch_hyperscaler_data.sec_get_companyfacts", return_value={"facts": {"us-gaap": {}}}),
            ):
                result = main(
                    [
                        "--allow-financialdatasets",
                        "--api-key",
                        "api-key",
                        "--tickers",
                        "MSFT",
                        "AMZN",
                        "--quarters",
                        "1",
                        "--data-dir",
                        directory,
                    ]
                )

        self.assertEqual(result, 0)
        self.assertEqual([call[0] for call in calls], ["/financials", "/financials"])
        self.assertEqual([call[1]["ticker"] for call in calls], ["MSFT", "AMZN"])

    def test_main_blocks_financialdatasets_without_explicit_legacy_flag(self):
        with tempfile.TemporaryDirectory() as directory:
            stderr = io.StringIO()
            with patch("scripts.fetch_hyperscaler_data.api_get") as api_get_mock:
                with contextlib.redirect_stderr(stderr):
                    result = main(
                        [
                            "--api-key",
                            "api-key",
                            "--tickers",
                            "MSFT",
                            "--quarters",
                            "1",
                            "--data-dir",
                            directory,
                        ]
                    )

        self.assertEqual(result, 2)
        self.assertIn("Financial Datasets import is disabled", stderr.getvalue())
        api_get_mock.assert_not_called()

    def test_build_panel_merges_quarterly_balance_sheet_and_capex(self):
        balance_sheets = {
            "MSFT": [
                {
                    "ticker": "MSFT",
                    "report_period": "2025-03-31",
                    "fiscal_period": "Q3",
                    "period": "quarterly",
                    "currency": "USD",
                    "accession_number": "should-not-be-kept",
                    "filing_url": "https://example.test/filing",
                    "cash_and_equivalents": 10,
                    "current_investments": 20,
                    "total_assets": 100,
                    "property_plant_and_equipment": 30,
                    "total_debt": 40,
                    "total_liabilities": 50,
                    "shareholders_equity": 60,
                    "deferred_revenue": 70,
                }
            ]
        }
        cash_flows = {
            "MSFT": [
                {
                    "ticker": "MSFT",
                    "report_period": "2025-03-31",
                    "fiscal_period": "Q3",
                    "period": "quarterly",
                    "currency": "USD",
                    "accession_number": "should-not-be-kept",
                    "filing_url": "https://example.test/cash-flow",
                    "capital_expenditure": -15,
                    "net_cash_flow_from_operations": 80,
                    "free_cash_flow": 65,
                }
            ]
        }
        income_statements = {
            "MSFT": [
                {
                    "ticker": "MSFT",
                    "report_period": "2025-03-31",
                    "fiscal_period": "Q3",
                    "period": "quarterly",
                    "currency": "USD",
                    "accession_number": "should-not-be-kept",
                    "filing_url": "https://example.test/income",
                    "revenue": 200,
                    "gross_profit": 120,
                    "operating_income": 90,
                    "net_income": 75,
                }
            ]
        }

        rows = build_panel(balance_sheets, cash_flows, income_statements, ["MSFT"], limit=20)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["ticker"], "MSFT")
        self.assertEqual(rows[0]["quarter"], "2025Q1")
        self.assertEqual(rows[0]["report_period"], "2025-03-31")
        self.assertEqual(rows[0]["capital_expenditure"], -15)
        self.assertEqual(rows[0]["free_cash_flow"], 65)
        self.assertEqual(rows[0]["revenue"], 200)
        self.assertEqual(rows[0]["net_income"], 75)
        self.assertNotIn("accession_number", rows[0])
        self.assertNotIn("filing_url", rows[0])

    def test_quarter_label_uses_calendar_quarters(self):
        self.assertEqual(quarter_label("2026-02-28"), "2026Q1")
        self.assertEqual(quarter_label("2026-03-31"), "2026Q1")
        self.assertEqual(quarter_label("2025-11-30"), "2025Q4")

    def test_build_panel_keeps_requested_number_of_quarters_per_company(self):
        balance_sheets = {
            "AMZN": [
                {
                    "ticker": "AMZN",
                    "report_period": f"2025-0{month}-30",
                    "fiscal_period": "Q1",
                    "period": "quarterly",
                    "currency": "USD",
                    **{field: month for field in BALANCE_SHEET_FIELDS},
                }
                for month in [5, 4, 3]
            ]
        }
        cash_flows = {
            "AMZN": [
                {
                    "ticker": "AMZN",
                    "report_period": f"2025-0{month}-30",
                    "fiscal_period": "Q1",
                    "period": "quarterly",
                    "currency": "USD",
                    **{field: month for field in CASH_FLOW_FIELDS},
                }
                for month in [5, 4, 3]
            ]
        }

        income_statements = {
            "AMZN": [
                {
                    "ticker": "AMZN",
                    "report_period": f"2025-0{month}-30",
                    "fiscal_period": "Q1",
                    "period": "quarterly",
                    "currency": "USD",
                    **{field: month for field in INCOME_STATEMENT_FIELDS},
                }
                for month in [5, 4, 3]
            ]
        }

        rows = build_panel(balance_sheets, cash_flows, income_statements, ["AMZN"], limit=2)

        self.assertEqual([row["report_period"] for row in rows], ["2025-04-30", "2025-05-30"])

    def test_pivot_metric_places_report_periods_in_rows_and_tickers_in_columns(self):
        rows = [
            {"ticker": "MSFT", "quarter": "2025Q1", "capital_expenditure": -10},
            {"ticker": "AMZN", "quarter": "2025Q1", "capital_expenditure": -20},
            {"ticker": "MSFT", "quarter": "2025Q2", "capital_expenditure": -11},
        ]

        pivoted = pivot_metric(rows, "capital_expenditure", ["MSFT", "AMZN"])

        self.assertEqual(
            pivoted,
            [
                {"quarter": "2025Q1", "MSFT": -10, "AMZN": -20},
                {"quarter": "2025Q2", "MSFT": -11, "AMZN": ""},
            ],
        )

    def test_export_dataset_writes_panel_company_and_metric_views(self):
        rows = [
            {
                "ticker": "MSFT",
                "quarter": "2025Q1",
                "report_period": "2025-03-31",
                "fiscal_period": "Q3",
                "period": "quarterly",
                "currency": "USD",
                "cash_and_equivalents": 10,
                "current_investments": 20,
                "total_assets": 100,
                "property_plant_and_equipment": 30,
                "total_debt": 40,
                "total_liabilities": 50,
                "shareholders_equity": 60,
                "deferred_revenue": 70,
                "capital_expenditure": -15,
                "net_cash_flow_from_operations": 80,
                "free_cash_flow": 65,
                "revenue": 200,
                "cost_of_revenue": 80,
                "gross_profit": 120,
                "operating_expense": 30,
                "selling_general_and_administrative_expenses": 10,
                "research_and_development": 20,
                "operating_income": 90,
                "interest_expense": 5,
                "ebit": 95,
                "income_tax_expense": 20,
                "net_income_discontinued_operations": 0,
                "net_income_non_controlling_interests": 0,
                "net_income": 75,
                "net_income_common_stock": 75,
                "preferred_dividends_impact": 0,
                "consolidated_income": 75,
                "earnings_per_share": 1.1,
                "earnings_per_share_diluted": 1.0,
                "dividends_per_common_share": 0.2,
                "weighted_average_shares": 100,
                "weighted_average_shares_diluted": 110,
            }
        ]

        with tempfile.TemporaryDirectory() as directory:
            base_dir = Path(directory)
            export_dataset(rows, base_dir, ["MSFT"], generated_at="2026-07-05T00:00:00Z")

            panel_csv = base_dir / "panel" / "quarterly_hyperscaler_financials.csv"
            company_json = base_dir / "companies" / "MSFT.json"
            metric_csv = base_dir / "metrics" / "capital_expenditure.csv"
            revenue_metric_csv = base_dir / "metrics" / "revenue.csv"
            metadata_json = base_dir / "metadata.json"

            self.assertTrue(panel_csv.exists())
            self.assertTrue(company_json.exists())
            self.assertTrue(metric_csv.exists())
            self.assertTrue(revenue_metric_csv.exists())
            self.assertTrue(metadata_json.exists())

            with panel_csv.open(newline="", encoding="utf-8") as file:
                csv_rows = list(csv.DictReader(file))
            self.assertEqual(csv_rows[0]["ticker"], "MSFT")
            self.assertEqual(csv_rows[0]["quarter"], "2025Q1")
            self.assertEqual(csv_rows[0]["capital_expenditure"], "-15")
            self.assertEqual(csv_rows[0]["revenue"], "200")

            with company_json.open(encoding="utf-8") as file:
                company_rows = json.load(file)
            self.assertEqual(company_rows[0]["quarter"], "2025Q1")

            with metadata_json.open(encoding="utf-8") as file:
                metadata = json.load(file)
            self.assertEqual(metadata["tickers"], ["MSFT"])
            self.assertEqual(metadata["quarters_per_company"], 20)
            self.assertEqual(metadata["fields"]["income_statement"], INCOME_STATEMENT_FIELDS)

    def test_export_financials_source_writes_full_raw_and_statement_files(self):
        raw_financials = {
            "MSFT": {
                "financials": {
                    "balance_sheets": [
                        {
                            "ticker": "MSFT",
                            "report_period": "2025-03-31",
                            "fiscal_period": "2025-Q1",
                            "period": "quarterly",
                            "currency": "USD",
                            "accession_number": "raw-kept",
                            "filing_url": "https://example.test/raw",
                            "total_assets": 100,
                            "current_assets": 50,
                        }
                    ],
                    "cash_flow_statements": [
                        {
                            "ticker": "MSFT",
                            "report_period": "2025-03-31",
                            "fiscal_period": "2025-Q1",
                            "period": "quarterly",
                            "currency": "USD",
                            "capital_expenditure": -10,
                            "free_cash_flow": 90,
                        }
                    ],
                    "income_statements": [
                        {
                            "ticker": "MSFT",
                            "report_period": "2025-03-31",
                            "fiscal_period": "2025-Q1",
                            "period": "quarterly",
                            "currency": "USD",
                            "revenue": 200,
                            "net_income": 70,
                        }
                    ],
                }
            }
        }

        with tempfile.TemporaryDirectory() as directory:
            base_dir = Path(directory)
            export_financials_source(raw_financials, base_dir, ["MSFT"], limit=20)

            raw_json = base_dir / "source" / "financials" / "MSFT.json"
            balance_csv = base_dir / "source" / "balance_sheets" / "MSFT.csv"
            income_csv = base_dir / "source" / "income_statements" / "MSFT.csv"

            self.assertTrue(raw_json.exists())
            self.assertTrue(balance_csv.exists())
            self.assertTrue(income_csv.exists())

            raw = json.loads(raw_json.read_text(encoding="utf-8"))
            self.assertEqual(raw["financials"]["balance_sheets"][0]["accession_number"], "raw-kept")

            with balance_csv.open(newline="", encoding="utf-8") as file:
                balance_rows = list(csv.DictReader(file))
            self.assertEqual(balance_rows[0]["accession_number"], "raw-kept")
            self.assertEqual(balance_rows[0]["current_assets"], "50")

            with income_csv.open(newline="", encoding="utf-8") as file:
                income_rows = list(csv.DictReader(file))
            self.assertEqual(income_rows[0]["revenue"], "200")

    def test_export_financials_source_keeps_raw_separate_from_patched_statements(self):
        raw_financials = {
            "AMZN": {
                "financials": {
                    "balance_sheets": [],
                    "cash_flow_statements": [
                        {
                            "ticker": "AMZN",
                            "report_period": "2026-03-31",
                            "fiscal_period": "2026-Q1",
                            "period": "quarterly",
                            "currency": "USD",
                            "capital_expenditure": None,
                        }
                    ],
                    "income_statements": [],
                }
            }
        }
        patched_financials = {
            "AMZN": {
                "financials": {
                    "balance_sheets": [],
                    "cash_flow_statements": [
                        {
                            "ticker": "AMZN",
                            "report_period": "2026-03-31",
                            "fiscal_period": "2026-Q1",
                            "period": "quarterly",
                            "currency": "USD",
                            "capital_expenditure": -44203000000,
                            "capex_source": "sec_companyfacts:PaymentsToAcquireProductiveAssets",
                        }
                    ],
                    "income_statements": [],
                }
            }
        }

        with tempfile.TemporaryDirectory() as directory:
            base_dir = Path(directory)
            export_financials_source(raw_financials, base_dir, ["AMZN"], limit=20, statement_financials=patched_financials)

            raw = json.loads((base_dir / "source" / "financials" / "AMZN.json").read_text(encoding="utf-8"))
            self.assertIsNone(raw["financials"]["cash_flow_statements"][0]["capital_expenditure"])

            with (base_dir / "source" / "cash_flow_statements" / "AMZN.csv").open(newline="", encoding="utf-8") as file:
                cash_rows = list(csv.DictReader(file))
            self.assertEqual(cash_rows[0]["capital_expenditure"], "-44203000000")
            self.assertEqual(cash_rows[0]["capex_source"], "sec_companyfacts:PaymentsToAcquireProductiveAssets")

    def test_patch_amzn_capex_from_sec_companyfacts_fills_only_missing_values(self):
        cash_flows = {
            "AMZN": [
                {
                    "ticker": "AMZN",
                    "report_period": "2026-03-31",
                    "capital_expenditure": None,
                    "capex_source": "financialdatasets",
                },
                {
                    "ticker": "AMZN",
                    "report_period": "2025-12-31",
                    "capital_expenditure": -38469000000,
                    "capex_source": "financialdatasets",
                },
            ],
            "MSFT": [
                {
                    "ticker": "MSFT",
                    "report_period": "2026-03-31",
                    "capital_expenditure": None,
                }
            ],
        }
        companyfacts = {
            "facts": {
                "us-gaap": {
                    "PaymentsToAcquireProductiveAssets": {
                        "units": {
                            "USD": [
                                {
                                    "end": "2026-03-31",
                                    "val": 44203000000,
                                    "form": "10-Q",
                                    "filed": "2026-04-30",
                                    "frame": "CY2026Q1",
                                    "accn": "0001018724-26-000001",
                                },
                                {
                                    "end": "2025-12-31",
                                    "val": 131819000000,
                                    "form": "10-K",
                                    "filed": "2026-02-06",
                                    "frame": "CY2025",
                                    "accn": "0001018724-26-000002",
                                },
                            ]
                        }
                    }
                }
            }
        }

        patched = patch_amzn_capex_from_sec_companyfacts(cash_flows, companyfacts)

        self.assertEqual(patched, 1)
        self.assertEqual(cash_flows["AMZN"][0]["capital_expenditure"], -44203000000)
        self.assertEqual(cash_flows["AMZN"][0]["capex_source"], "sec_companyfacts:PaymentsToAcquireProductiveAssets")
        self.assertEqual(cash_flows["AMZN"][0]["capex_sec_accession_number"], "0001018724-26-000001")
        self.assertEqual(cash_flows["AMZN"][0]["capex_sec_filed"], "2026-04-30")
        self.assertEqual(
            cash_flows["AMZN"][0]["capex_sec_filing_url"],
            "https://www.sec.gov/Archives/edgar/data/1018724/000101872426000001/0001018724-26-000001-index.htm",
        )
        self.assertEqual(cash_flows["AMZN"][1]["capital_expenditure"], -38469000000)
        self.assertNotIn("capex_sec_accession_number", cash_flows["AMZN"][1])
        self.assertIsNone(cash_flows["MSFT"][0]["capital_expenditure"])

    def test_patch_free_cash_flow_from_ocf_and_capex_recalculates_inconsistent_values(self):
        cash_flows = {
            "MSFT": [
                {
                    "ticker": "MSFT",
                    "report_period": "2025-09-30",
                    "net_cash_flow_from_operations": 45057000000,
                    "capital_expenditure": 19394000000,
                    "free_cash_flow": 8353000000,
                }
            ],
            "AMZN": [
                {
                    "ticker": "AMZN",
                    "report_period": "2026-03-31",
                    "net_cash_flow_from_operations": 26032000000,
                    "capital_expenditure": -44203000000,
                    "free_cash_flow": None,
                }
            ],
        }

        patched = patch_free_cash_flow_from_ocf_and_capex(cash_flows)

        self.assertEqual(patched, 2)
        self.assertEqual(cash_flows["MSFT"][0]["free_cash_flow_reported"], 8353000000)
        self.assertEqual(cash_flows["MSFT"][0]["free_cash_flow"], 25663000000)
        self.assertEqual(
            cash_flows["MSFT"][0]["fcf_source"],
            "calculated:net_cash_flow_from_operations_minus_abs_capital_expenditure",
        )
        self.assertIsNone(cash_flows["AMZN"][0]["free_cash_flow_reported"])
        self.assertEqual(cash_flows["AMZN"][0]["free_cash_flow"], -18171000000)

    def test_normalize_ytd_cash_flow_statements_converts_interim_periods_to_quarters(self):
        cash_flows = {
            "GOOGL": [
                {
                    "ticker": "GOOGL",
                    "report_period": "2025-03-31",
                    "fiscal_period": "2025-Q1",
                    "net_cash_flow_from_operations": 100,
                    "capital_expenditure": 10,
                    "net_cash_flow_from_investing": -30,
                },
                {
                    "ticker": "GOOGL",
                    "report_period": "2025-06-30",
                    "fiscal_period": "2025-Q2",
                    "net_cash_flow_from_operations": 250,
                    "capital_expenditure": 30,
                    "net_cash_flow_from_investing": -80,
                },
                {
                    "ticker": "GOOGL",
                    "report_period": "2025-09-30",
                    "fiscal_period": "2025-Q3",
                    "net_cash_flow_from_operations": 450,
                    "capital_expenditure": 60,
                    "net_cash_flow_from_investing": -140,
                },
                {
                    "ticker": "GOOGL",
                    "report_period": "2025-12-31",
                    "fiscal_period": "2025-Q4",
                    "net_cash_flow_from_operations": 200,
                    "capital_expenditure": -25,
                    "net_cash_flow_from_investing": -70,
                },
            ],
            "AMZN": [
                {
                    "ticker": "AMZN",
                    "report_period": "2025-06-30",
                    "fiscal_period": "2025-Q2",
                    "net_cash_flow_from_operations": 250,
                    "capital_expenditure": -30,
                }
            ],
        }

        normalized = normalize_ytd_cash_flow_statements(cash_flows, {"GOOGL"})

        self.assertEqual(normalized, 6)
        self.assertEqual(cash_flows["GOOGL"][0]["net_cash_flow_from_operations"], 100)
        self.assertEqual(cash_flows["GOOGL"][1]["net_cash_flow_from_operations"], 150)
        self.assertEqual(cash_flows["GOOGL"][1]["capital_expenditure"], 20)
        self.assertEqual(cash_flows["GOOGL"][1]["net_cash_flow_from_investing"], -50)
        self.assertEqual(cash_flows["GOOGL"][2]["net_cash_flow_from_operations"], 200)
        self.assertEqual(cash_flows["GOOGL"][2]["capital_expenditure"], 30)
        self.assertEqual(cash_flows["GOOGL"][3]["net_cash_flow_from_operations"], 200)
        self.assertEqual(cash_flows["GOOGL"][1]["cash_flow_normalization"], "fiscal_ytd_to_quarter")
        self.assertEqual(cash_flows["AMZN"][0]["net_cash_flow_from_operations"], 250)


if __name__ == "__main__":
    unittest.main()
