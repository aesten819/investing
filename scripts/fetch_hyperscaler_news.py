#!/usr/bin/env python3
"""Fetch hyperscaler and data-center investment news cards."""

from __future__ import annotations

import argparse
import hashlib
import html as html_lib
import json
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from xml.etree import ElementTree


DEFAULT_OUTPUT_DIR = Path("data/hyperscaler-news")

DEFAULT_SOURCES: list[dict[str, Any]] = [
    {
        "id": "aws_news_blog",
        "name": "AWS News Blog",
        "url": "https://aws.amazon.com/blogs/aws/feed/",
        "type": "rss",
    },
    {
        "id": "amazon_company_news",
        "name": "About Amazon",
        "url": "https://www.aboutamazon.com/news/company-news/rss",
        "type": "rss",
    },
    {
        "id": "google_infrastructure_cloud",
        "name": "Google Infrastructure & Cloud",
        "url": "https://blog.google/innovation-and-ai/infrastructure-and-cloud/rss/",
        "type": "rss",
    },
    {
        "id": "google_cloud",
        "name": "Google Cloud",
        "url": "https://blog.google/products/google-cloud/rss/",
        "type": "rss",
    },
    {
        "id": "microsoft_on_issues",
        "name": "Microsoft On the Issues",
        "url": "https://blogs.microsoft.com/on-the-issues/feed/",
        "type": "rss",
    },
    {
        "id": "microsoft_blog",
        "name": "Microsoft Blog",
        "url": "https://blogs.microsoft.com/feed/",
        "type": "rss",
    },
    {
        "id": "meta_data_centers",
        "name": "Meta Data Centers",
        "url": "https://about.fb.com/news/tag/data-centers/feed/",
        "type": "rss",
    },
    {
        "id": "datacenter_dynamics",
        "name": "Data Center Dynamics",
        "url": "https://www.datacenterdynamics.com/rss/",
        "type": "rss",
    },
    {
        "id": "data_center_knowledge",
        "name": "Data Center Knowledge",
        "url": "https://www.datacenterknowledge.com/rss.xml",
        "type": "rss",
    },
    {
        "id": "synergy_research",
        "name": "Synergy Research",
        "url": "https://www.srgresearch.com/articles",
        "type": "html_links",
        "max_items": 10,
    },
    {
        "id": "oracle_ai_data_centers",
        "name": "Oracle AI Data Centers",
        "url": "https://www.oracle.com/data-centers/",
        "type": "html_links",
        "max_items": 8,
    },
    {
        "id": "data_center_frontier",
        "name": "Data Center Frontier",
        "url": "https://www.datacenterfrontier.com/",
        "type": "html_links",
        "max_items": 12,
    },
]

TAG_KEYWORDS: dict[str, tuple[str, ...]] = {
    "AWS": ("aws", "amazon web services"),
    "Azure": ("azure", "microsoft"),
    "Google Cloud": ("google cloud", "gcp", "google"),
    "Meta": ("meta", "facebook"),
    "Oracle": ("oracle", "oci"),
    "AI Infrastructure": (
        "ai infrastructure",
        "ai data center",
        "ai datacenter",
        "artificial intelligence infrastructure",
        "supercomputing",
        "gpu cluster",
        "ai factory",
    ),
    "Data Center": (
        "data center",
        "data centers",
        "datacenter",
        "datacenters",
        "data centre",
        "data centres",
        "datacentre",
        "datacentres",
        "campus",
    ),
    "Capacity": (
        "capacity",
        "availability zone",
        "cloud region",
        "region",
        "megawatt",
        "mw",
        "gigawatt",
        "gw",
    ),
    "Capex": ("capex", "capital expenditure", "investment", "spending", "spend"),
    "Power": (
        "power",
        "grid",
        "electricity",
        "energy",
        "renewable",
        "nuclear",
        "water",
        "cooling",
        "liquid cooling",
    ),
    "Colocation": ("colocation", "colo", "lease", "leased", "hyperscale"),
    "Financing": ("financing", "m&a", "private equity", "debt", "bond", "committed capital"),
    "Neocloud": ("neocloud", "neo cloud"),
}

CORE_INFRA_KEYWORDS = (
    "hyperscale",
    "hyperscaler",
    "data center",
    "data centers",
    "datacenter",
    "datacenters",
    "data centre",
    "data centres",
    "datacentre",
    "datacentres",
    "ai infrastructure",
    "ai data center",
    "ai data centers",
    "ai datacenter",
    "ai datacenters",
    "cloud region",
    "availability zone",
    "capacity",
    "capex",
    "capital expenditure",
    "investment",
    "spending",
    "buildout",
    "campus",
    "megawatt",
    "mw",
    "gigawatt",
    "gw",
    "power",
    "grid",
    "electricity",
    "energy",
    "cooling",
    "liquid cooling",
    "colocation",
    "lease",
    "neocloud",
    "ai factory",
    "gpu cluster",
    "supercomputing",
)

NOISE_KEYWORDS = (
    "sdk",
    "template",
    "templates",
    "workspace",
    "observability",
    "developer tool",
    "application update",
    "security patch",
    "jobs",
    "podcast",
    "virtual event",
    "trends summit",
    "pinterest",
    "newsletter",
    "dcd studio",
    "sponsored",
    "project manager",
    "tours",
    "quickchat",
    "security agent",
    "threat modeling",
    "plugin",
    "kiro",
    "robotics",
)

UTM_PARAMS = {"fbclid", "gclid", "mc_cid", "mc_eid"}


def normalize_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def strip_html(value: str) -> str:
    without_scripts = re.sub(r"<(script|style).*?</\1>", " ", value, flags=re.IGNORECASE | re.DOTALL)
    without_tags = re.sub(r"<[^>]+>", " ", without_scripts)
    return normalize_whitespace(html_lib.unescape(without_tags))


def summarize_text(value: str, max_length: int = 190) -> str:
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


def child_url(element: ElementTree.Element) -> str:
    for child in list(element):
        if local_name(child.tag) == "link":
            return child.text or child.attrib.get("href", "")
    return child_text(element, ("guid", "id"))


def contains_keyword(text: str, keyword: str) -> bool:
    escaped = re.escape(keyword.lower()).replace(r"\ ", r"\s+")
    return re.search(rf"(?<![a-z0-9-]){escaped}(?![a-z0-9])", text) is not None


def match_tags(title: str, summary: str) -> list[str]:
    haystack = f"{title} {summary}".lower()
    tags = [
        tag
        for tag, keywords in TAG_KEYWORDS.items()
        if any(contains_keyword(haystack, keyword) for keyword in keywords)
    ]
    return tags


def is_hyperscaler_infra_related(title: str, summary: str) -> bool:
    haystack = f"{title} {summary}".lower()
    if any(contains_keyword(haystack, keyword) for keyword in NOISE_KEYWORDS):
        return False
    return any(contains_keyword(haystack, keyword) for keyword in CORE_INFRA_KEYWORDS)


def iter_feed_items(root: ElementTree.Element) -> list[ElementTree.Element]:
    items = root.findall(".//item")
    if items:
        return items
    return [element for element in root.iter() if local_name(element.tag) == "entry"]


def parse_rss_feed(xml_bytes: bytes, source: dict[str, Any]) -> list[dict[str, Any]]:
    root = ElementTree.fromstring(xml_bytes)
    articles: list[dict[str, Any]] = []

    for item in iter_feed_items(root):
        headline = normalize_whitespace(html_lib.unescape(child_text(item, ("title",))))
        raw_url = normalize_whitespace(child_url(item))
        url = urllib.parse.urljoin(source["url"], raw_url)
        raw_summary = child_text(item, ("description", "summary", "content", "encoded"))
        summary = summarize_text(raw_summary)
        published_at = parse_datetime(child_text(item, ("pubDate", "published", "updated", "date")))

        if not headline or not url or not is_hyperscaler_infra_related(headline, summary):
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


class AnchorExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._active_href = ""
        self._active_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a" or self._active_href:
            return

        attr_map = {key.lower(): value for key, value in attrs if value is not None}
        href = attr_map.get("href", "")
        if href:
            self._active_href = href
            self._active_text = []

    def handle_data(self, data: str) -> None:
        if self._active_href:
            self._active_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or not self._active_href:
            return

        text = normalize_whitespace(" ".join(self._active_text))
        if text:
            self.links.append((self._active_href, text))
        self._active_href = ""
        self._active_text = []


def parse_html_links(
    html_bytes: bytes,
    source: dict[str, Any],
    fetched_at: str,
) -> list[dict[str, Any]]:
    parser = AnchorExtractor()
    parser.feed(html_bytes.decode("utf-8", errors="replace"))
    max_items = int(source.get("max_items", 12))
    articles: list[dict[str, Any]] = []

    for href, text in parser.links:
        headline = normalize_whitespace(html_lib.unescape(text))
        if len(headline) < 24 or not is_hyperscaler_infra_related(headline, ""):
            continue

        url = urllib.parse.urljoin(source["url"], href)
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme not in {"http", "https"}:
            continue

        tags = match_tags(headline, "")
        articles.append(
            {
                "id": article_id(url),
                "headline": headline,
                "summary": headline,
                "url": url,
                "source": source["name"],
                "source_id": source["id"],
                "published_at": fetched_at,
                "tags": tags,
            }
        )

    return dedupe_articles(articles)[:max_items]


def fetch_url(url: str, timeout: int = 25) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/rss+xml, application/xml, text/xml, text/html, */*",
            "User-Agent": "Mozilla/5.0 investing-research/1.0",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def fetch_articles(sources: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    articles: list[dict[str, Any]] = []
    source_status: list[dict[str, Any]] = []
    fetched_at = datetime.now(timezone.utc).isoformat()

    for source in sources:
        try:
            body = fetch_url(source["url"])
            if source.get("type") == "html_links":
                parsed_articles = parse_html_links(body, source, fetched_at)
            else:
                parsed_articles = parse_rss_feed(body, source)
        except Exception as exc:  # noqa: BLE001 - keep the batch alive when one source fails.
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


def load_existing_articles(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []

    payload = json.loads(path.read_text(encoding="utf-8"))
    articles = payload.get("articles", [])
    return articles if isinstance(articles, list) else []


def merge_existing_articles(
    fresh_articles: list[dict[str, Any]],
    existing_articles: list[dict[str, Any]],
    limit: int,
) -> list[dict[str, Any]]:
    relevant_existing_articles = [
        article
        for article in existing_articles
        if is_hyperscaler_infra_related(
            str(article.get("headline", "")),
            str(article.get("summary", "")),
        )
    ]
    existing_by_url = {
        canonical_url(str(article.get("url", ""))): article
        for article in relevant_existing_articles
    }
    merged_fresh: list[dict[str, Any]] = []
    for article in fresh_articles:
        merged_article = dict(article)
        previous = existing_by_url.get(canonical_url(str(article.get("url", ""))))
        if previous:
            for field in ("headline_ko", "summary_ko", "tags_ko", "published_at"):
                if field in previous:
                    merged_article[field] = previous[field]
        merged_fresh.append(merged_article)

    return dedupe_articles([*merged_fresh, *relevant_existing_articles])[:limit]


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--limit", type=int, default=160)
    parser.add_argument(
        "--no-merge-existing",
        action="store_true",
        help="Do not preserve articles from the previous articles.json.",
    )
    args = parser.parse_args(argv)

    output_dir = Path(args.output_dir)
    articles_path = output_dir / "articles.json"
    articles, source_status = fetch_articles(DEFAULT_SOURCES)
    existing_articles = [] if args.no_merge_existing else load_existing_articles(articles_path)
    limited_articles = merge_existing_articles(articles, existing_articles, args.limit)
    generated_at = datetime.now(timezone.utc).isoformat()

    write_json(
        articles_path,
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
        f"wrote {len(limited_articles)} hyperscaler-news articles from "
        f"{len(source_status) - error_count}/{len(source_status)} sources"
    )
    return 1 if error_count == len(source_status) else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
