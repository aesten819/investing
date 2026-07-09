#!/usr/bin/env python3
"""Translate hyperscaler and data-center investment news cards to Korean."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


DEFAULT_ARTICLES_PATH = Path("data/hyperscaler-news/articles.json")
DEFAULT_CACHE_PATH = Path("data/hyperscaler-news/translation_cache.json")
DEFAULT_MODEL = "deepseek-v4-flash"
DEFAULT_BASE_URL = "https://api.deepseek.com"

GLOSSARY_TERMS = [
    "AWS",
    "Azure",
    "Google Cloud",
    "GCP",
    "Meta",
    "Oracle",
    "OCI",
    "hyperscaler",
    "hyperscale",
    "data center",
    "AI infrastructure",
    "cloud region",
    "availability zone",
    "capacity",
    "capex",
    "MW",
    "GW",
    "colocation",
    "neocloud",
    "liquid cooling",
    "power grid",
]


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def translation_cache_key(article: dict[str, Any]) -> str:
    basis = {
        "id": article.get("id", ""),
        "headline": article.get("headline", ""),
        "summary": article.get("summary", ""),
        "tags": article.get("tags", []),
    }
    raw = json.dumps(basis, sort_keys=True, ensure_ascii=True)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def build_translation_messages(article: dict[str, Any]) -> list[dict[str, str]]:
    article_payload = {
        "headline": article.get("headline", ""),
        "summary": article.get("summary", ""),
        "tags": article.get("tags", []),
        "source": article.get("source", ""),
    }
    system_prompt = (
        "You translate hyperscaler and data-center investment news cards for a Korean investment "
        "research page. Return JSON only. Keep company names, service names, ticker-like terms, "
        "units, and these terms in English when natural: "
        f"{', '.join(GLOSSARY_TERMS)}. "
        "Do not add claims not present in the source. Write concise, neutral Korean."
    )
    user_prompt = (
        "Translate this card. Return exactly this JSON shape: "
        '{"headline_ko": string, "summary_ko": string, "tags_ko": string[]}. '
        "The summary_ko should be one Korean sentence suitable for a card news summary.\n\n"
        f"{json.dumps(article_payload, ensure_ascii=False, indent=2)}"
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def parse_translation_content(content: str) -> dict[str, Any]:
    cleaned = content.strip()
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", cleaned, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        cleaned = fenced.group(1).strip()

    payload = json.loads(cleaned)
    headline_ko = str(payload.get("headline_ko", "")).strip()
    summary_ko = str(payload.get("summary_ko", "")).strip()
    tags_ko = payload.get("tags_ko", [])

    if not headline_ko or not summary_ko:
        raise ValueError("translation response must include headline_ko and summary_ko")
    if not isinstance(tags_ko, list):
        raise ValueError("translation response tags_ko must be a list")

    return {
        "headline_ko": headline_ko,
        "summary_ko": summary_ko,
        "tags_ko": [str(tag).strip() for tag in tags_ko if str(tag).strip()],
    }


def merge_translation(article: dict[str, Any], translation: dict[str, Any]) -> dict[str, Any]:
    merged = dict(article)
    merged["headline_ko"] = translation["headline_ko"]
    merged["summary_ko"] = translation["summary_ko"]
    merged["tags_ko"] = translation["tags_ko"]
    return merged


def translate_with_deepseek(
    article: dict[str, Any],
    api_key: str,
    model: str = DEFAULT_MODEL,
    base_url: str = DEFAULT_BASE_URL,
    timeout: int = 60,
) -> dict[str, Any]:
    body = {
        "model": model,
        "messages": build_translation_messages(article),
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "investing-research/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"DeepSeek API HTTP {exc.code}: {error_body}") from exc

    content = payload["choices"][0]["message"]["content"]
    return parse_translation_content(content)


def translate_articles(
    articles: list[dict[str, Any]],
    cache: dict[str, dict[str, Any]],
    client: Callable[[dict[str, Any]], dict[str, Any]],
    limit: int | None = None,
    force: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], dict[str, int]]:
    translated_articles: list[dict[str, Any]] = []
    updated_cache = dict(cache)
    stats = {"cached": 0, "translated": 0, "skipped": 0}

    for article in articles:
        key = translation_cache_key(article)
        existing_translation = None if force else updated_cache.get(key)
        if existing_translation is not None:
            translated_articles.append(merge_translation(article, existing_translation))
            stats["cached"] += 1
            continue

        if limit is not None and stats["translated"] >= limit:
            translated_articles.append(article)
            stats["skipped"] += 1
            continue

        translation = client(article)
        updated_cache[key] = translation
        translated_articles.append(merge_translation(article, translation))
        stats["translated"] += 1

    return translated_articles, updated_cache, stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--articles", default=str(DEFAULT_ARTICLES_PATH))
    parser.add_argument("--cache", default=str(DEFAULT_CACHE_PATH))
    parser.add_argument("--model", default=os.environ.get("DEEPSEEK_MODEL", DEFAULT_MODEL))
    parser.add_argument("--base-url", default=os.environ.get("DEEPSEEK_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--limit", type=int, default=None, help="Translate at most N uncached articles.")
    parser.add_argument("--force", action="store_true", help="Retranslate even when cache entries exist.")
    args = parser.parse_args(argv)

    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        print("DEEPSEEK_API_KEY is required.", file=sys.stderr)
        return 2

    articles_path = Path(args.articles)
    cache_path = Path(args.cache)
    payload = load_json(articles_path, {})
    articles = payload.get("articles", [])
    cache = load_json(cache_path, {})

    def client(article: dict[str, Any]) -> dict[str, Any]:
        return translate_with_deepseek(
            article,
            api_key=api_key,
            model=args.model,
            base_url=args.base_url,
        )

    translated_articles, updated_cache, stats = translate_articles(
        articles,
        cache,
        client,
        limit=args.limit,
        force=args.force,
    )
    output_payload = dict(payload)
    output_payload["articles"] = translated_articles
    output_payload["translation"] = {
        "provider": "deepseek",
        "model": args.model,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cached": stats["cached"],
        "translated": stats["translated"],
        "skipped": stats["skipped"],
    }
    write_json(articles_path, output_payload)
    write_json(cache_path, updated_cache)
    print(
        f"translated={stats['translated']} cached={stats['cached']} "
        f"skipped={stats['skipped']} model={args.model}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
