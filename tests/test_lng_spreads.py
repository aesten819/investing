import json
from datetime import date, datetime, timezone
from pathlib import Path
import unittest

from scripts.fetch_lng_spreads import build_snapshot, parse_chart, shift_month, validate_snapshot


class LngSpreadTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 20, tzinfo=timezone.utc)
        self.observations = {
            "hh": {"2026-08-18": 3, "2026-09-11": 3, "2026-09-17": 3, "2026-09-18": 2.91},
            "ttf": {"2026-08-18": 50, "2026-09-11": 60, "2026-09-17": 70, "2026-09-18": 80},
            "jkm": {"2026-08-18": 18, "2026-09-11": 22, "2026-09-17": 26.75, "2026-09-18": 27.51},
            "eurusd": {"2026-08-18": 1.1, "2026-09-11": 1.1, "2026-09-17": 1.1, "2026-09-18": 1.15},
        }

    def test_conversion_and_calendar_changes(self):
        data = build_snapshot(self.observations, self.now)
        self.assertAlmostEqual(data["latest"]["ttf_spread"], 80 * 1.15 / 3.41214163312794 - 2.91)
        self.assertAlmostEqual(data["latest"]["jkm_spread"], 24.60)
        self.assertAlmostEqual(data["changes"]["jkm_spread"]["day"]["value"], .85)
        self.assertEqual(data["changes"]["jkm_spread"]["week"]["date"], "2026-09-11")
        self.assertEqual(data["changes"]["jkm_spread"]["month"]["date"], "2026-08-18")

    def test_missing_fx_breaks_only_ttf_and_moves_common_date_back(self):
        del self.observations["eurusd"]["2026-09-18"]
        data = build_snapshot(self.observations, self.now)
        self.assertEqual(data["as_of"], "2026-09-17")
        self.assertIsNone(data["rows"][-1]["ttf_spread"])
        self.assertAlmostEqual(data["rows"][-1]["jkm_spread"], 24.6)

    def test_missing_hh_is_not_forward_filled(self):
        del self.observations["hh"]["2026-09-17"]
        data = build_snapshot(self.observations, self.now)
        self.assertIsNone(data["rows"][-2]["jkm_spread"])
        self.assertIsNone(data["rows"][-2]["ttf_spread"])
        self.assertEqual(data["changes"]["jkm_spread"]["day"]["date"], "2026-09-11")

    def test_weekend_target_uses_previous_observation_without_long_carry(self):
        self.observations = {key: {"2026-08-14": 10, "2026-09-11": 11, "2026-09-14": 12} for key in self.observations}
        data = build_snapshot(self.observations, self.now)
        self.assertEqual(data["changes"]["jkm_spread"]["month"]["date"], "2026-08-14")
        self.assertIsNone(data["changes"]["jkm_spread"]["week"]["value"])
        self.assertEqual(shift_month(date(2024, 3, 31)), date(2024, 2, 29))
        self.assertEqual(shift_month(date(2026, 1, 31)), date(2025, 12, 31))

    def test_negative_spreads_are_kept(self):
        self.observations["hh"]["2026-09-18"] = 30
        self.assertAlmostEqual(build_snapshot(self.observations, self.now)["latest"]["jkm_spread"], -2.49)

    def test_parser_rejects_partial_session_null_and_wrong_currency(self):
        payload = {"chart": {"result": [{
            "meta": {"symbol": "NG=F", "currency": "USD", "exchangeTimezoneName": "America/New_York"},
            "timestamp": [int(datetime(2026, 9, day, 4, tzinfo=timezone.utc).timestamp()) for day in [15, 16, 17, 18]],
            "indicators": {"quote": [{"close": [3, None, float("nan"), 4]}]},
        }]}}
        now = datetime(2026, 9, 18, 22, tzinfo=timezone.utc)
        self.assertEqual(parse_chart(payload, "hh", now), {"2026-09-15": 3.0})
        payload["chart"]["result"][0]["meta"]["currency"] = "EUR"
        with self.assertRaises(ValueError):
            parse_chart(payload, "hh", now)

    def test_exchange_date_not_utc_date(self):
        payload = {"chart": {"result": [{
            "meta": {"symbol": "EURUSD=X", "currency": "USD", "exchangeTimezoneName": "Europe/London"},
            "timestamp": [int(datetime(2026, 9, 17, 23, tzinfo=timezone.utc).timestamp())],
            "indicators": {"quote": [{"close": [1.15]}]},
        }]}}
        self.assertEqual(parse_chart(payload, "eurusd", self.now), {"2026-09-18": 1.15})

    def test_quality_gate_preserves_previous_snapshot(self):
        data = build_snapshot(self.observations, self.now)
        with self.assertRaises(ValueError):
            validate_snapshot(data, self.now)
        data["common_observations"] = 700
        validate_snapshot(data, self.now)
        with self.assertRaises(ValueError):
            validate_snapshot(data, datetime(2026, 10, 1, tzinfo=timezone.utc))
        with self.assertRaises(ValueError):
            validate_snapshot(data, self.now, {"as_of": "2026-09-19", "common_observations": 700})
        with self.assertRaises(ValueError):
            validate_snapshot(data, self.now, {"as_of": "2026-09-17", "common_observations": 800})

    def test_published_snapshot_reconciles_every_observation(self):
        data = json.loads(Path("public/lng/spreads.json").read_text())
        self.assertGreaterEqual(data["common_observations"], 500)
        days = [row["date"] for row in data["rows"]]
        self.assertEqual(days, sorted(set(days)))
        for row in data["rows"]:
            if row["ttf_eur"] is not None and row["eurusd"] is not None:
                self.assertAlmostEqual(row["ttf_usd"], row["ttf_eur"] * row["eurusd"] / 3.41214163312794)
            else:
                self.assertIsNone(row["ttf_usd"])
            for price, spread in [("ttf_usd", "ttf_spread"), ("jkm", "jkm_spread")]:
                if row[price] is not None and row["hh"] is not None:
                    self.assertAlmostEqual(row[spread], row[price] - row["hh"])
                else:
                    self.assertIsNone(row[spread])
        common = [row for row in data["rows"] if row["ttf_spread"] is not None and row["jkm_spread"] is not None]
        self.assertEqual(len(common), data["common_observations"])
        self.assertEqual(common[-1], data["latest"])
        self.assertEqual(common[-1]["date"], data["as_of"])
        for key, periods in data["changes"].items():
            for change in periods.values():
                if change["date"]:
                    baseline = next(row for row in common if row["date"] == change["date"])
                    self.assertAlmostEqual(change["value"], data["latest"][key] - baseline[key])


if __name__ == "__main__":
    unittest.main()
