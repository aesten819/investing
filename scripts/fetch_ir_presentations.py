#!/usr/bin/env python3
"""Archive official hyperscaler IR presentation materials locally."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_PANEL_PATH = Path("data/hyperscaler/panel/quarterly_hyperscaler_financials.json")
DEFAULT_OUTPUT_DIR = Path("data/hyperscaler/ir_presentations")
USER_AGENT = "investing-research/0.1"

Q4_REPORT_TYPES = {
    "First Quarter": 1,
    "Second Quarter": 2,
    "Third Quarter": 3,
    "Fourth Quarter": 4,
}

Q4_COMPANIES = {
    "AMZN": {
        "base_url": "https://ir.aboutamazon.com",
        "official_page_url": "https://ir.aboutamazon.com/quarterly-results/default.aspx",
    },
    "GOOGL": {
        "base_url": "https://abc.xyz",
        "official_page_url": "https://abc.xyz/investor/earnings/",
    },
    "META": {
        "base_url": "https://investor.atmeta.com",
        "official_page_url": "https://investor.atmeta.com/financials/",
    },
    "ORCL": {
        "base_url": "https://investor.oracle.com",
        "official_page_url": "https://investor.oracle.com/financials/default.aspx",
    },
}

MANIFEST_FIELDS = [
    "ticker",
    "quarter",
    "report_period",
    "fiscal_period",
    "document_kind",
    "title",
    "official_page_url",
    "source_url",
    "final_url",
    "file_name",
    "local_path",
    "content_type",
    "bytes",
    "sha256",
    "status",
    "note",
]


def request_url(url: str, timeout: int = 60) -> urllib.request.Request:
    return urllib.request.Request(
        url,
        headers={
            "Accept": "*/*",
            "User-Agent": USER_AGENT,
        },
    )


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=MANIFEST_FIELDS)
        writer.writeheader()
        writer.writerows([{field: row.get(field, "") for field in MANIFEST_FIELDS} for row in rows])


def slugify(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", value).strip("-").lower()
    return slug or "document"


def fiscal_year_quarter(fiscal_period: str) -> tuple[int, int] | None:
    match = re.fullmatch(r"(\d{4})-Q([1-4])", fiscal_period)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def load_targets(panel_path: Path) -> dict[str, dict[str, dict[str, str]]]:
    rows = read_json(panel_path)
    targets: dict[str, dict[str, dict[str, str]]] = {}

    for row in rows:
        targets.setdefault(row["ticker"], {})[row["fiscal_period"]] = {
            "ticker": row["ticker"],
            "quarter": row["quarter"],
            "report_period": row["report_period"],
            "fiscal_period": row["fiscal_period"],
        }

    return targets


def fetch_url_json(url: str) -> dict[str, Any]:
    with urllib.request.urlopen(request_url(url), timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_url_text(url: str) -> str:
    with urllib.request.urlopen(request_url(url), timeout=60) as response:
        return response.read().decode("utf-8", errors="replace")


def q4_financial_report_url(base_url: str) -> str:
    report_types = "|".join(Q4_REPORT_TYPES)
    params = {
        "LanguageId": 1,
        "pageSize": -1,
        "pageNumber": 0,
        "tagList": "",
        "includeTags": "true",
        "year": -1,
        "excludeSelection": 1,
        "reportTypes": report_types,
        "reportSubType": report_types,
        "reportSubTypeList": report_types,
    }
    return f"{base_url}/feed/FinancialReport.svc/GetFinancialReportList?{urllib.parse.urlencode(params)}"


def is_presentation_doc(doc: dict[str, Any]) -> bool:
    category = str(doc.get("DocumentCategory") or "").lower()
    title = str(doc.get("DocumentTitle") or "").lower()
    path = str(doc.get("DocumentPath") or "").lower()
    if not doc.get("DocumentPath"):
        return False
    return (
        category == "presentation"
        or "earnings slides" in title
        or "presentation" in title
        or "/presentation/" in path
    )


def collect_q4_company_documents(
    ticker: str,
    target_by_fiscal_period: dict[str, dict[str, str]],
    source_dir: Path,
) -> list[dict[str, str]]:
    config = Q4_COMPANIES[ticker]
    url = q4_financial_report_url(config["base_url"])
    response = fetch_url_json(url)
    write_json(source_dir / "q4_financial_reports" / f"{ticker}.json", response)

    by_fiscal_period: dict[str, dict[str, Any]] = {}
    for report in response.get("GetFinancialReportListResult", []):
        quarter = Q4_REPORT_TYPES.get(report.get("ReportSubType"))
        year = report.get("ReportYear")
        if not quarter or not year:
            continue
        fiscal_period = f"{int(year)}-Q{quarter}"
        if fiscal_period in by_fiscal_period:
            existing_docs = by_fiscal_period[fiscal_period].get("Documents", [])
            new_docs = report.get("Documents", [])
            if not any(is_presentation_doc(doc) for doc in existing_docs) and any(
                is_presentation_doc(doc) for doc in new_docs
            ):
                by_fiscal_period[fiscal_period] = report
        else:
            by_fiscal_period[fiscal_period] = report

    documents: list[dict[str, str]] = []
    for fiscal_period, target in sorted(target_by_fiscal_period.items()):
        report = by_fiscal_period.get(fiscal_period)
        if not report:
            documents.append(missing_document(target, config["official_page_url"], "no official report row found"))
            continue

        docs = [doc for doc in report.get("Documents", []) if is_presentation_doc(doc)]
        if not docs:
            documents.append(missing_document(target, config["official_page_url"], "no presentation/slides document found"))
            continue

        doc = docs[0]
        documents.append(
            {
                **target,
                "document_kind": "earnings_presentation",
                "title": doc.get("DocumentTitle") or f"{ticker} {fiscal_period} earnings presentation",
                "official_page_url": config["official_page_url"],
                "source_url": doc["DocumentPath"],
                "note": "",
            }
        )

    return documents


def microsoft_earnings_page_url(fiscal_period: str) -> str:
    fiscal = fiscal_year_quarter(fiscal_period)
    if not fiscal:
        raise ValueError(f"Unexpected Microsoft fiscal period: {fiscal_period}")
    fiscal_year, fiscal_quarter = fiscal
    return f"https://www.microsoft.com/en-us/investor/earnings/fy-{fiscal_year}-q{fiscal_quarter}/press-release-webcast"


def extract_microsoft_slide_url(page_html: str, fiscal_year: int, fiscal_quarter: int) -> str | None:
    yy = str(fiscal_year)[2:]
    patterns = [
        rf"https://view\.officeapps\.live\.com/op/view\.aspx\?src=([^\"<> ]*SlidesFY{yy}Q{fiscal_quarter}[^\"<> ]*)",
        rf"https://cdn-[^\"<> ]*SlidesFY{yy}Q{fiscal_quarter}[^\"<> ]*",
        rf"https://aka\.ms/slidesfy{yy}q{fiscal_quarter}",
    ]

    for pattern in patterns:
        match = re.search(pattern, page_html, re.IGNORECASE)
        if not match:
            continue
        if match.lastindex:
            return urllib.parse.unquote(match.group(1))
        return match.group(0)

    return None


def collect_microsoft_documents(
    target_by_fiscal_period: dict[str, dict[str, str]],
    source_dir: Path,
) -> list[dict[str, str]]:
    documents: list[dict[str, str]] = []
    page_cache: dict[str, str] = {}

    for fiscal_period, target in sorted(target_by_fiscal_period.items()):
        fiscal = fiscal_year_quarter(fiscal_period)
        if not fiscal:
            documents.append(missing_document(target, "", "unexpected fiscal period"))
            continue
        fiscal_year, fiscal_quarter = fiscal
        page_url = microsoft_earnings_page_url(fiscal_period)

        try:
            page_html = fetch_url_text(page_url)
            page_cache[fiscal_period] = page_html
            source_url = extract_microsoft_slide_url(page_html, fiscal_year, fiscal_quarter)
        except (urllib.error.URLError, TimeoutError) as error:
            documents.append(missing_document(target, page_url, f"could not fetch Microsoft page: {error}"))
            continue

        if not source_url:
            documents.append(missing_document(target, page_url, "no earnings slide deck link found"))
            continue

        documents.append(
            {
                **target,
                "document_kind": "earnings_presentation",
                "title": f"Microsoft FY{str(fiscal_year)[2:]} Q{fiscal_quarter} Earnings Call Slides",
                "official_page_url": page_url,
                "source_url": source_url,
                "note": "",
            }
        )

        time.sleep(0.1)

    write_json(
        source_dir / "microsoft_pages" / "page_lengths.json",
        {fiscal_period: len(page_html) for fiscal_period, page_html in page_cache.items()},
    )
    return documents


def missing_document(target: dict[str, str], official_page_url: str, note: str) -> dict[str, str]:
    return {
        **target,
        "document_kind": "earnings_presentation",
        "title": "",
        "official_page_url": official_page_url,
        "source_url": "",
        "final_url": "",
        "file_name": "",
        "local_path": "",
        "content_type": "",
        "bytes": "",
        "sha256": "",
        "status": "missing",
        "note": note,
    }


def extension_from_response(source_url: str, final_url: str, content_type: str, body: bytes) -> str:
    path = urllib.parse.urlparse(final_url or source_url).path
    suffix = Path(path).suffix.lower()
    if suffix in {".pdf", ".ppt", ".pptx", ".pps", ".ppsx"}:
        return suffix
    if body.startswith(b"%PDF"):
        return ".pdf"
    if "presentationml.presentation" in content_type:
        return ".pptx"
    if body.startswith(b"PK"):
        return ".pptx"
    return suffix or ".bin"


def archive_document(document: dict[str, str], output_dir: Path) -> dict[str, Any]:
    if document.get("status") == "missing":
        return document

    ticker = document["ticker"]
    fiscal_period = document["fiscal_period"]
    quarter = document["quarter"]
    source_url = document["source_url"]

    try:
        with urllib.request.urlopen(request_url(source_url), timeout=90) as response:
            body = response.read()
            final_url = response.geturl()
            content_type = response.headers.get("Content-Type", "").split(";")[0]
        if content_type == "text/html" and "view.officeapps.live.com/op/view.aspx" in final_url:
            parsed = urllib.parse.urlparse(final_url)
            actual_sources = urllib.parse.parse_qs(parsed.query).get("src", [])
            if actual_sources:
                with urllib.request.urlopen(request_url(actual_sources[0]), timeout=90) as response:
                    body = response.read()
                    final_url = response.geturl()
                    content_type = response.headers.get("Content-Type", "").split(";")[0]
    except (urllib.error.URLError, TimeoutError) as error:
        return {
            **document,
            "final_url": "",
            "file_name": "",
            "local_path": "",
            "content_type": "",
            "bytes": "",
            "sha256": "",
            "status": "error",
            "note": f"download failed: {error}",
        }

    extension = extension_from_response(source_url, final_url, content_type, body)
    file_name = f"{ticker}_{quarter}_{fiscal_period}_{slugify(document['title'])}{extension}"
    local_path = output_dir / "originals" / ticker / file_name
    local_path.parent.mkdir(parents=True, exist_ok=True)
    local_path.write_bytes(body)

    return {
        **document,
        "final_url": final_url,
        "file_name": file_name,
        "local_path": str(local_path),
        "content_type": content_type,
        "bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
        "status": "downloaded",
    }


def collect_documents(targets: dict[str, dict[str, dict[str, str]]], source_dir: Path) -> list[dict[str, str]]:
    documents: list[dict[str, str]] = []
    for ticker, target_by_fiscal_period in sorted(targets.items()):
        if ticker == "MSFT":
            documents.extend(collect_microsoft_documents(target_by_fiscal_period, source_dir))
        elif ticker in Q4_COMPANIES:
            documents.extend(collect_q4_company_documents(ticker, target_by_fiscal_period, source_dir))
    return documents


def write_readme(output_dir: Path, manifest_rows: list[dict[str, Any]]) -> None:
    downloaded = sum(1 for row in manifest_rows if row.get("status") == "downloaded")
    missing = sum(1 for row in manifest_rows if row.get("status") == "missing")
    errored = sum(1 for row in manifest_rows if row.get("status") == "error")
    by_ticker: dict[str, int] = {}
    for row in manifest_rows:
        if row.get("status") == "downloaded":
            by_ticker[row["ticker"]] = by_ticker.get(row["ticker"], 0) + 1

    counts = "\n".join(f"- {ticker}: {count}" for ticker, count in sorted(by_ticker.items()))
    text = f"""# Hyperscaler IR Presentation Archive

Local-only archive of official investor-relations presentation materials matching the financial panel period.

Generated: {datetime.now(UTC).isoformat().replace("+00:00", "Z")}

Downloaded files: {downloaded}
Missing rows: {missing}
Error rows: {errored}

## Downloaded By Ticker

{counts}

## Layout

- `originals/<TICKER>/`: local-only original files. This folder is ignored by git.
- `manifest.csv` and `manifest.json`: metadata, source URLs, local paths, file sizes, and hashes.
- `source/`: raw API/page metadata used to discover documents.

## Notes

- Microsoft slide decks are archived in their original PowerPoint format when that is what Microsoft provides.
- Amazon, Alphabet, and Meta publish quarterly earnings slides as PDFs via official IR/Q4 CDN pages.
- Oracle has no separate presentation/slides document in the current target fiscal periods found via the official IR financial report feed; those rows are retained as `missing` in the manifest.
"""
    (output_dir / "README.md").write_text(text, encoding="utf-8")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel-path", type=Path, default=DEFAULT_PANEL_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    targets = load_targets(args.panel_path)
    source_dir = args.output_dir / "source"
    documents = collect_documents(targets, source_dir)
    manifest_rows = [archive_document(document, args.output_dir) for document in documents]

    manifest_rows = sorted(
        manifest_rows,
        key=lambda row: (row["ticker"], row["report_period"], row.get("title", "")),
    )
    write_json(args.output_dir / "manifest.json", manifest_rows)
    write_csv(args.output_dir / "manifest.csv", manifest_rows)
    write_readme(args.output_dir, manifest_rows)

    downloaded = sum(1 for row in manifest_rows if row.get("status") == "downloaded")
    missing = sum(1 for row in manifest_rows if row.get("status") == "missing")
    errored = sum(1 for row in manifest_rows if row.get("status") == "error")
    print(f"Wrote IR presentation archive manifest to {args.output_dir}")
    print(f"Downloaded: {downloaded}; missing: {missing}; errors: {errored}")
    return 1 if errored else 0


if __name__ == "__main__":
    raise SystemExit(main())
