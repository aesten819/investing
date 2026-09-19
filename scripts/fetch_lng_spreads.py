#!/usr/bin/env python3
"""Publish three years of observed daily LNG futures spreads (no forward fill)."""

from __future__ import annotations

import argparse
import calendar
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
import json
import math
from pathlib import Path
import time
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

MMBTU_TO_MWH = 0.2930710701722222
SOURCES = {
    "hh": {"symbol": "NG=F", "name": "Henry Hub", "unit": "USD/MMBtu", "currency": "USD"},
    "ttf": {"symbol": "TTF=F", "name": "Dutch TTF", "unit": "EUR/MWh", "currency": "EUR"},
    "jkm": {"symbol": "JKM=F", "name": "Japan/Korea Marker", "unit": "USD/MMBtu", "currency": "USD"},
    "eurusd": {"symbol": "EURUSD=X", "name": "EUR/USD", "unit": "USD/EUR", "currency": "USD"},
}


def positive(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0


def parse_chart(payload, key, now):
    chart = payload["chart"]
    if chart.get("error") or not chart.get("result"):
        raise ValueError(f"{key}: missing Yahoo chart result")
    result = chart["result"][0]
    meta = result["meta"]
    source = SOURCES[key]
    if meta.get("symbol") != source["symbol"]:
        raise ValueError(f"{key}: unexpected symbol")
    # Yahoo's JKM alias has null currency metadata; the contract is USD/MMBtu.
    if meta.get("currency") != source["currency"] and not (key == "jkm" and meta.get("currency") is None):
        raise ValueError(f"{key}: unexpected currency")
    tz = ZoneInfo(meta["exchangeTimezoneName"])
    today = now.astimezone(tz).date()
    timestamps = result["timestamp"]
    closes = result["indicators"]["quote"][0]["close"]
    if len(timestamps) != len(closes):
        raise ValueError(f"{key}: timestamps and closes differ in length")
    observations = {}
    for stamp, close in zip(timestamps, closes):
        day = datetime.fromtimestamp(stamp, tz).date()
        # Exclude the exchange's current day: a partial session is not a daily close.
        if day < today and day.weekday() < 5 and positive(close):
            observations[day.isoformat()] = float(close)
    if not observations:
        raise ValueError(f"{key}: no completed daily observations")
    return observations


def fetch_source(key, now):
    params = urlencode({"range": "5y", "interval": "1d"})
    last_error = None
    for attempt in range(3):
        host = "query1" if attempt % 2 == 0 else "query2"
        url = f"https://{host}.finance.yahoo.com/v8/finance/chart/{quote(SOURCES[key]['symbol'], safe='')}?{params}"
        try:
            request = Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
            with urlopen(request, timeout=30) as response:
                return key, parse_chart(json.load(response), key, now)
        except Exception as error:
            last_error = error
            if attempt < 2:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"{key}: fetch failed; published snapshot is unchanged") from last_error


def shift_month(day):
    year, month = (day.year - 1, 12) if day.month == 1 else (day.year, day.month - 1)
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def build_snapshot(observations, now):
    today = now.date()
    start = today.replace(year=today.year - 3, day=min(today.day, calendar.monthrange(today.year - 3, today.month)[1]))
    dates = sorted(set().union(*(set(values) for values in observations.values())))
    rows = []
    for day in dates:
        if not start.isoformat() <= day < today.isoformat():
            continue
        hh, ttf, jkm, fx = (observations[key].get(day) for key in SOURCES)
        ttf_usd = ttf * fx * MMBTU_TO_MWH if ttf is not None and fx is not None else None
        rows.append({
            "date": day, "hh": hh, "ttf_eur": ttf, "eurusd": fx, "ttf_usd": ttf_usd, "jkm": jkm,
            "ttf_spread": ttf_usd - hh if ttf_usd is not None and hh is not None else None,
            "jkm_spread": jkm - hh if jkm is not None and hh is not None else None,
        })
    common = [row for row in rows if row["ttf_spread"] is not None and row["jkm_spread"] is not None]
    if not common:
        raise ValueError("No common observation date across all four sources")
    latest = common[-1]
    latest_day = date.fromisoformat(latest["date"])
    baselines = {"day": common[-2] if len(common) > 1 else None}
    for label, target in [("week", latest_day - timedelta(days=7)), ("month", shift_month(latest_day))]:
        candidates = [r for r in common if (target - timedelta(days=7)).isoformat() <= r["date"] <= target.isoformat()]
        baselines[label] = candidates[-1] if candidates else None
    changes = {
        key: {period: {"date": row["date"] if row else None, "value": latest[key] - row[key] if row else None}
              for period, row in baselines.items()}
        for key in ("ttf_spread", "jkm_spread")
    }
    return {
        "schema_version": 1,
        "generated_at": now.isoformat(),
        "as_of": latest["date"],
        "unit": "USD/MMBtu",
        "conversion_factor": MMBTU_TO_MWH,
        "sources": {key: {**source, "url": f"https://finance.yahoo.com/quote/{quote(source['symbol'], safe='')}/history/",
                           "latest_date": max(observations[key])} for key, source in SOURCES.items()},
        "common_observations": len(common),
        "latest": latest,
        "changes": changes,
        "rows": rows,
    }


def validate_snapshot(snapshot, now, previous=None):
    if snapshot["common_observations"] < 500:
        raise ValueError("Fewer than 500 common observations; refusing incomplete history")
    age = (now.date() - date.fromisoformat(snapshot["as_of"])).days
    if not 0 <= age <= 10:
        raise ValueError("Latest common date is stale or in the future")
    if previous and (snapshot["as_of"] < previous["as_of"] or snapshot["common_observations"] < previous["common_observations"] * .9):
        raise ValueError("New data regresses or loses substantial history")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("public/lng/spreads.json"))
    args = parser.parse_args()
    now = datetime.now(timezone.utc)
    with ThreadPoolExecutor(max_workers=4) as pool:
        observations = dict(pool.map(lambda key: fetch_source(key, now), SOURCES))
    snapshot = build_snapshot(observations, now)
    previous = json.loads(args.output.read_text()) if args.output.exists() else None
    validate_snapshot(snapshot, now, previous)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(".tmp")
    temporary.write_text(json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n")
    temporary.replace(args.output)
    print(f"LNG spreads: {snapshot['as_of']}, {snapshot['common_observations']} common observations → {args.output}")


if __name__ == "__main__":
    main()
