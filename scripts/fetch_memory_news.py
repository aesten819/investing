#!/usr/bin/env python3
"""Fetch memory-semiconductor news cards from official and industry RSS feeds."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from xml.etree import ElementTree


DEFAULT_OUTPUT_DIR = Path("data/memory-news")

DEFAULT_SOURCES: list[dict[str, str]] = [
    {
        "id": "samsung_semiconductor",
        "name": "Samsung Semiconductor",
        "url": "https://news.samsungsemiconductor.com/global/feed/",
    },
    {
        "id": "sk_hynix",
        "name": "SK hynix Newsroom",
        "url": "https://news.skhynix.com/feed/",
    },
    {
        "id": "micron",
        "name": "Micron",
        "url": "https://investors.micron.com/rss/news-releases.xml",
    },
    {
        "id": "trendforce",
        "name": "TrendForce",
        "url": "https://www.trendforce.com/feed/Semiconductors.html",
    },
    {
        "id": "semiconductor_today",
        "name": "Semiconductor Today",
        "url": "https://www.semiconductor-today.com/rss/news.xml",
    },
]

TAG_KEYWORDS: dict[str, tuple[str, ...]] = {
    "HBM": ("hbm", "high bandwidth memory"),
    "DRAM": ("dram", "ddr", "ddr5", "lpddr", "gddr"),
    "NAND": ("nand", "v-nand", "3d nand", "flash memory", "flash"),
    "SSD": ("ssd", "essd", "solid state drive", "storage"),
    "Memory": ("memory", "cxl memory"),
    "Pricing": ("contract price", "spot price", "pricing", "price", "prices"),
    "Capacity": ("capacity", "capex", "supply", "fab"),
    "AI Server": ("ai server", "ai servers", "server demand"),
}

CORE_MEMORY_KEYWORDS = (
    "hbm",
    "high bandwidth memory",
    "dram",
    "ddr",
    "ddr5",
    "lpddr",
    "gddr",
    "nand",
    "v-nand",
    "3d nand",
    "flash memory",
    "ssd",
    "essd",
    "solid state drive",
    "ufs",
    "memory",
    "cxl memory",
)

UTM_PARAMS = {"fbclid", "gclid", "mc_cid", "mc_eid"}


def normalize_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def strip_html(value: str) -> str:
    without_scripts = re.sub(r"<(script|style).*?</\1>", " ", value, flags=re.IGNORECASE | re.DOTALL)
    without_tags = re.sub(r"<[^>]+>", " ", without_scripts)
    return normalize_whitespace(html.unescape(without_tags))


def summarize_text(value: str, max_length: int = 180) -> str:
    text = strip_html(value)
    if len(text) <= max_length:
        return text

    sentences = re.split(r"(?<=[.!?])\s+", text)
    if sentences and len(sentences[0]) <= max_length:
        return sentences[0]

    clipped = text[: max(0, max_length - 1)].rstrip()
    return f"{clipped}..."


def canonical_url(url: str) -> str:
    parsed = urllib.parse.urlsplit(url.strip())
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    filtered_query = [
        (key, value)
        for key, value in query
        if not key.lower().startswith("utm_") and key.lower() not in UTM_PARAMS
    ]
    path = parsed.path.rstrip("/") or parsed.path
    return urllib.parse.urlunsplit(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            path,
            urllib.parse.urlencode(filtered_query, doseq=True),
            "",
        )
    )


def article_id(url: str) -> str:
    return hashlib.sha1(canonical_url(url).encode("utf-8")).hexdigest()[:12]


def parse_datetime(value: str | None) -> str:
    if not value:
        return ""

    raw = value.strip()
    parsed: datetime | None = None
    try:
        parsed = parsedate_to_datetime(raw)
    except (TypeError, ValueError, IndexError):
        pass

    if parsed is None:
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return raw

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    return parsed.astimezone(timezone.utc).isoformat()


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def child_text(element: ElementTree.Element, names: tuple[str, ...]) -> str:
    wanted = {name.lower() for name in names}
    for child in list(element):
        if local_name(child.tag) in wanted:
            return child.text or ""
    return ""


def contains_keyword(text: str, keyword: str) -> bool:
    escaped = re.escape(keyword.lower()).replace(r"\ ", r"\s+")
    return re.search(rf"(?<![a-z0-9]){escaped}(?![a-z0-9])", text) is not None


def match_tags(title: str, summary: str) -> list[str]:
    haystack = f"{title} {summary}".lower()
    tags = [
        tag
        for tag, keywords in TAG_KEYWORDS.items()
        if any(contains_keyword(haystack, keyword) for keyword in keywords)
    ]
    return tags


def is_memory_related(title: str, summary: str) -> bool:
    haystack = f"{title} {summary}".lower()
    return any(contains_keyword(haystack, keyword) for keyword in CORE_MEMORY_KEYWORDS)


def parse_rss_feed(xml_bytes: bytes, source: dict[str, str]) -> list[dict[str, Any]]:
    root = ElementTree.fromstring(xml_bytes)
    items = root.findall(".//item")
    articles: list[dict[str, Any]] = []

    for item in items:
        headline = normalize_whitespace(html.unescape(child_text(item, ("title",))))
        url = normalize_whitespace(child_text(item, ("link", "guid")))
        raw_summary = child_text(item, ("description", "summary", "encoded"))
        summary = summarize_text(raw_summary)
        published_at = parse_datetime(child_text(item, ("pubDate", "published", "updated", "date")))

        if not headline or not url or not is_memory_related(headline, summary):
            continue

        tags = match_tags(headline, summary)
        articles.append(
            {
                "id": article_id(url),
                "headline": headline,
                "summary": summary,
                "url": url,
                "source": source["name"],
                "source_id": source["id"],
                "published_at": published_at,
                "tags": tags,
            }
        )

    return articles


def fetch_url(url: str, timeout: int = 25) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/rss+xml, application/xml, text/xml, */*",
            "User-Agent": "Mozilla/5.0 investing-research/1.0",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def fetch_articles(sources: list[dict[str, str]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    articles: list[dict[str, Any]] = []
    source_status: list[dict[str, Any]] = []

    for source in sources:
        try:
            parsed_articles = parse_rss_feed(fetch_url(source["url"]), source)
        except Exception as exc:  # noqa: BLE001 - keep the batch alive when one feed fails.
            source_status.append({**source, "status": "error", "error": str(exc), "article_count": 0})
            continue

        articles.extend(parsed_articles)
        source_status.append({**source, "status": "ok", "article_count": len(parsed_articles)})

    return dedupe_articles(articles), source_status


def dedupe_articles(articles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_url: dict[str, dict[str, Any]] = {}
    for article in articles:
        key = canonical_url(str(article.get("url", "")))
        previous = by_url.get(key)
        if previous is None or str(article.get("published_at", "")) > str(previous.get("published_at", "")):
            by_url[key] = article

    return sorted(
        by_url.values(),
        key=lambda article: str(article.get("published_at", "")),
        reverse=True,
    )


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--limit", type=int, default=80)
    args = parser.parse_args(argv)

    output_dir = Path(args.output_dir)
    articles, source_status = fetch_articles(DEFAULT_SOURCES)
    limited_articles = articles[: args.limit]
    generated_at = datetime.now(timezone.utc).isoformat()

    write_json(
        output_dir / "articles.json",
        {
            "generated_at": generated_at,
            "article_count": len(limited_articles),
            "articles": limited_articles,
        },
    )
    write_json(
        output_dir / "sources.json",
        {
            "generated_at": generated_at,
            "sources": source_status,
        },
    )

    error_count = sum(1 for source in source_status if source["status"] != "ok")
    print(
        f"wrote {len(limited_articles)} memory-news articles from "
        f"{len(source_status) - error_count}/{len(source_status)} sources"
    )
    return 1 if error_count == len(source_status) else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
