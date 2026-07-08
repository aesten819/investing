#!/usr/bin/env python3
"""Archive Amazon quarterly earnings release and filing documents locally."""

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
DEFAULT_OUTPUT_DIR = Path("data/hyperscaler/ir_documents")

TICKER = "AMZN"
CIK = "0001018724"
SEC_CIK_PATH = "1018724"
AMZN_BASE_URL = "https://ir.aboutamazon.com"
AMZN_QUARTERLY_RESULTS_URL = "https://ir.aboutamazon.com/quarterly-results/default.aspx"
SEC_SUBMISSIONS_URL = f"https://data.sec.gov/submissions/CIK{CIK}.json"
SEC_ARCHIVES_BASE = f"https://www.sec.gov/Archives/edgar/data/{SEC_CIK_PATH}"
USER_AGENT = "investing-research/0.1 pkh876@example.com"

Q4_REPORT_TYPES = {
    "First Quarter": 1,
    "Second Quarter": 2,
    "Third Quarter": 3,
    "Fourth Quarter": 4,
}

MANIFEST_FIELDS = [
    "ticker",
    "quarter",
    "report_period",
    "fiscal_period",
    "document_kind",
    "form_type",
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
    "accession_number",
    "filing_date",
]


def request_url(url: str) -> urllib.request.Request:
    return urllib.request.Request(
        url,
        headers={
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/pdf,*/*;q=0.8",
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


def load_amzn_targets(panel_path: Path) -> dict[str, dict[str, str]]:
    rows = read_json(panel_path)
    targets: dict[str, dict[str, str]] = {}

    for row in rows:
        if row["ticker"] != TICKER:
            continue
        targets[row["fiscal_period"]] = {
            "ticker": row["ticker"],
            "quarter": row["quarter"],
            "report_period": row["report_period"],
            "fiscal_period": row["fiscal_period"],
        }

    return targets


def fetch_url_json(url: str) -> dict[str, Any]:
    with urllib.request.urlopen(request_url(url), timeout=90) as response:
        return json.loads(response.read().decode("utf-8"))


def amzn_financial_report_url() -> str:
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
    return f"{AMZN_BASE_URL}/feed/FinancialReport.svc/GetFinancialReportList?{urllib.parse.urlencode(params)}"


def expected_form_type(fiscal_period: str) -> str:
    return "10-K" if fiscal_period.endswith("-Q4") else "10-Q"


def resolve_amzn_url(path_or_url: str) -> str:
    url = urllib.parse.urljoin(AMZN_BASE_URL, path_or_url)
    parsed = urllib.parse.urlparse(url)
    if parsed.netloc == "ir.aboutamazon.com" and parsed.scheme == "http":
        url = urllib.parse.urlunparse(parsed._replace(scheme="https"))
    return url


def collect_amzn_feed_documents(
    targets: dict[str, dict[str, str]],
    source_dir: Path,
) -> list[dict[str, str]]:
    response = fetch_url_json(amzn_financial_report_url())
    write_json(source_dir / "amzn_q4_financial_reports.json", response)

    by_fiscal_period: dict[str, dict[str, Any]] = {}
    for report in response.get("GetFinancialReportListResult", []):
        quarter = Q4_REPORT_TYPES.get(report.get("ReportSubType"))
        year = report.get("ReportYear")
        if not quarter or not year:
            continue
        by_fiscal_period[f"{int(year)}-Q{quarter}"] = report

    documents: list[dict[str, str]] = []
    for fiscal_period, target in sorted(targets.items()):
        report = by_fiscal_period.get(fiscal_period)
        if not report:
            documents.extend(
                [
                    missing_document(target, "earnings_release_html", "", "no Amazon report row found"),
                    missing_document(target, "sec_filing_pdf", expected_form_type(fiscal_period), "no Amazon report row found"),
                ]
            )
            continue

        docs = report.get("Documents", [])
        news_doc = find_amzn_document(docs, "news")
        filing_doc = find_amzn_document(docs, "tenk" if expected_form_type(fiscal_period) == "10-K" else "tenq")

        if news_doc:
            documents.append(
                {
                    **target,
                    "document_kind": "earnings_release_html",
                    "form_type": "",
                    "title": news_doc.get("DocumentTitle") or f"Amazon {fiscal_period} earnings release",
                    "official_page_url": AMZN_QUARTERLY_RESULTS_URL,
                    "source_url": resolve_amzn_url(news_doc["DocumentPath"]),
                    "note": "",
                    "accession_number": "",
                    "filing_date": "",
                }
            )
        else:
            documents.append(missing_document(target, "earnings_release_html", "", "no earnings release HTML link found"))

        if filing_doc:
            form_type = expected_form_type(fiscal_period)
            documents.append(
                {
                    **target,
                    "document_kind": "sec_filing_pdf",
                    "form_type": form_type,
                    "title": filing_doc.get("DocumentTitle") or form_type,
                    "official_page_url": AMZN_QUARTERLY_RESULTS_URL,
                    "source_url": resolve_amzn_url(filing_doc["DocumentPath"]),
                    "note": "",
                    "accession_number": "",
                    "filing_date": "",
                }
            )
        else:
            documents.append(
                missing_document(
                    target,
                    "sec_filing_pdf",
                    expected_form_type(fiscal_period),
                    f"no Amazon {expected_form_type(fiscal_period)} PDF link found",
                )
            )

    return documents


def find_amzn_document(documents: list[dict[str, Any]], category: str) -> dict[str, Any] | None:
    for document in documents:
        if document.get("DocumentCategory") == category and document.get("DocumentPath"):
            return document
    return None


def collect_sec_html_documents(
    targets: dict[str, dict[str, str]],
    source_dir: Path,
) -> list[dict[str, str]]:
    response = fetch_url_json(SEC_SUBMISSIONS_URL)
    write_json(source_dir / f"sec_submissions_CIK{CIK}.json", response)

    recent = response.get("filings", {}).get("recent", {})
    by_report_period: dict[str, dict[str, str]] = {}
    forms = recent.get("form", [])
    for index, form in enumerate(forms):
        if form not in {"10-K", "10-Q"}:
            continue
        report_period = get_recent_value(recent, "reportDate", index)
        if not report_period:
            continue
        by_report_period[report_period] = {
            "accession_number": get_recent_value(recent, "accessionNumber", index),
            "filing_date": get_recent_value(recent, "filingDate", index),
            "form_type": form,
            "primary_document": get_recent_value(recent, "primaryDocument", index),
            "primary_doc_description": get_recent_value(recent, "primaryDocDescription", index),
        }

    documents: list[dict[str, str]] = []
    for fiscal_period, target in sorted(targets.items()):
        expected_form = expected_form_type(fiscal_period)
        filing = by_report_period.get(target["report_period"])
        if not filing:
            documents.append(missing_document(target, "sec_filing_html", expected_form, "no SEC filing matched report date"))
            continue
        if filing["form_type"] != expected_form:
            documents.append(
                missing_document(
                    target,
                    "sec_filing_html",
                    expected_form,
                    f"SEC filing form mismatch: found {filing['form_type']}",
                )
            )
            continue
        if not filing["accession_number"] or not filing["primary_document"]:
            documents.append(missing_document(target, "sec_filing_html", expected_form, "SEC filing missing primary document"))
            continue

        accession_no_dash = filing["accession_number"].replace("-", "")
        source_url = f"{SEC_ARCHIVES_BASE}/{accession_no_dash}/{filing['primary_document']}"
        documents.append(
            {
                **target,
                "document_kind": "sec_filing_html",
                "form_type": filing["form_type"],
                "title": filing["primary_doc_description"] or filing["form_type"],
                "official_page_url": SEC_SUBMISSIONS_URL,
                "source_url": source_url,
                "note": "",
                "accession_number": filing["accession_number"],
                "filing_date": filing["filing_date"],
            }
        )

    return documents


def get_recent_value(recent: dict[str, list[Any]], key: str, index: int) -> str:
    values = recent.get(key, [])
    if index >= len(values):
        return ""
    return str(values[index] or "")


def missing_document(
    target: dict[str, str],
    document_kind: str,
    form_type: str,
    note: str,
) -> dict[str, str]:
    return {
        **target,
        "document_kind": document_kind,
        "form_type": form_type,
        "title": "",
        "official_page_url": AMZN_QUARTERLY_RESULTS_URL,
        "source_url": "",
        "final_url": "",
        "file_name": "",
        "local_path": "",
        "content_type": "",
        "bytes": "",
        "sha256": "",
        "status": "missing",
        "note": note,
        "accession_number": "",
        "filing_date": "",
    }


def extension_from_response(source_url: str, final_url: str, content_type: str, body: bytes) -> str:
    path = urllib.parse.urlparse(final_url or source_url).path
    suffix = Path(path).suffix.lower()
    stripped = body.lstrip()[:64].lower()
    if body.startswith(b"%PDF") or suffix == ".pdf" or "pdf" in content_type:
        return ".pdf"
    if suffix in {".html", ".htm"}:
        return ".html"
    if stripped.startswith(b"<!doctype html") or stripped.startswith(b"<html") or "html" in content_type:
        return ".html"
    return suffix or ".bin"


def archive_document(document: dict[str, str], output_dir: Path) -> dict[str, Any]:
    if document.get("status") == "missing":
        return document

    ticker = document["ticker"]
    quarter = document["quarter"]
    fiscal_period = document["fiscal_period"]
    document_kind = document["document_kind"]
    source_url = document["source_url"]

    try:
        body, final_url, content_type = download_document_body(source_url)
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
    descriptor = document["title"] or document["form_type"] or document_kind
    file_name = f"{ticker}_{quarter}_{fiscal_period}_{document_kind}_{slugify(descriptor)}{extension}"
    local_path = output_dir / "originals" / ticker / document_kind / file_name
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


def download_document_body(source_url: str) -> tuple[bytes, str, str]:
    errors: list[Exception] = []
    for candidate_url in download_candidates(source_url):
        try:
            with urllib.request.urlopen(request_url(candidate_url), timeout=90) as response:
                body = response.read()
                final_url = response.geturl()
                content_type = response.headers.get("Content-Type", "").split(";")[0]
                return body, final_url, content_type
        except urllib.error.HTTPError as error:
            errors.append(error)
            if error.code != 404:
                raise
    if errors:
        raise errors[-1]
    raise urllib.error.URLError("no download candidates")


def download_candidates(source_url: str) -> list[str]:
    candidates = [source_url]
    normalized = source_url.replace("Amazon.com-Announces-", "Amazon-com-Announces-")
    if normalized != source_url:
        candidates.append(normalized)
    return candidates


def collect_documents(targets: dict[str, dict[str, str]], source_dir: Path) -> list[dict[str, str]]:
    documents = collect_amzn_feed_documents(targets, source_dir)
    time.sleep(0.2)
    documents.extend(collect_sec_html_documents(targets, source_dir))
    return documents


def write_readme(output_dir: Path, manifest_rows: list[dict[str, Any]]) -> None:
    downloaded = sum(1 for row in manifest_rows if row.get("status") == "downloaded")
    missing = sum(1 for row in manifest_rows if row.get("status") == "missing")
    errored = sum(1 for row in manifest_rows if row.get("status") == "error")
    by_kind: dict[str, int] = {}
    for row in manifest_rows:
        if row.get("status") == "downloaded":
            by_kind[row["document_kind"]] = by_kind.get(row["document_kind"], 0) + 1

    counts = "\n".join(f"- {kind}: {count}" for kind, count in sorted(by_kind.items()))
    text = f"""# Amazon IR Document Archive

Local-only archive of Amazon quarterly earnings release HTML pages and official 10-K/10-Q filings matching the financial panel period.

Generated: {datetime.now(UTC).isoformat().replace("+00:00", "Z")}

Downloaded files: {downloaded}
Missing rows: {missing}
Error rows: {errored}

## Downloaded By Document Kind

{counts}

## Layout

- `originals/AMZN/earnings_release_html/`: Amazon IR earnings release HTML pages.
- `originals/AMZN/sec_filing_pdf/`: Amazon IR linked 10-K/10-Q PDF files.
- `originals/AMZN/sec_filing_html/`: SEC EDGAR 10-K/10-Q primary HTML filings.
- `manifest.csv` and `manifest.json`: metadata, source URLs, local paths, file sizes, and hashes.
- `source/`: raw Amazon Q4 feed and SEC submissions metadata used to discover documents.

## Sources

- Amazon quarterly results: {AMZN_QUARTERLY_RESULTS_URL}
- SEC submissions JSON: {SEC_SUBMISSIONS_URL}
"""
    (output_dir / "README.md").write_text(text, encoding="utf-8")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel-path", type=Path, default=DEFAULT_PANEL_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    targets = load_amzn_targets(args.panel_path)
    if not targets:
        print(f"No {TICKER} rows found in {args.panel_path}", file=sys.stderr)
        return 1

    source_dir = args.output_dir / "source"
    documents = collect_documents(targets, source_dir)
    manifest_rows = [archive_document(document, args.output_dir) for document in documents]

    manifest_rows = sorted(
        manifest_rows,
        key=lambda row: (row["report_period"], row["document_kind"], row.get("form_type", "")),
    )
    write_json(args.output_dir / "manifest.json", manifest_rows)
    write_csv(args.output_dir / "manifest.csv", manifest_rows)
    write_readme(args.output_dir, manifest_rows)

    downloaded = sum(1 for row in manifest_rows if row.get("status") == "downloaded")
    missing = sum(1 for row in manifest_rows if row.get("status") == "missing")
    errored = sum(1 for row in manifest_rows if row.get("status") == "error")
    print(f"Wrote Amazon IR document archive manifest to {args.output_dir}")
    print(f"Downloaded: {downloaded}; missing: {missing}; errors: {errored}")
    return 1 if errored else 0


if __name__ == "__main__":
    raise SystemExit(main())
