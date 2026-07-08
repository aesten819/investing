#!/usr/bin/env python3
"""Archive Oracle quarterly earnings, financial tables, and filing documents locally."""

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

TICKER = "ORCL"
CIK = "0001341439"
SEC_CIK_PATH = "1341439"
ORCL_BASE_URL = "https://investor.oracle.com"
ORCL_FINANCIALS_URL = "https://investor.oracle.com/financials/default.aspx"
SEC_SUBMISSIONS_URL = f"https://data.sec.gov/submissions/CIK{CIK}.json"
SEC_ARCHIVES_BASE = f"https://www.sec.gov/Archives/edgar/data/{SEC_CIK_PATH}"
USER_AGENT = "investing-research/0.1 pkh876@example.com"

Q4_REPORT_TYPES = {
    "First Quarter": 1,
    "Second Quarter": 2,
    "Third Quarter": 3,
    "Fourth Quarter": 4,
}

ORCL_DOCUMENTS = {
    "news": "earnings_release_pdf",
    "financials": "financial_tables_pdf",
    "finxls": "financial_tables_xlsx",
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
            "Accept": "application/json,text/html,application/xhtml+xml,application/xml;q=0.9,application/pdf,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,*/*;q=0.8",
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


def load_orcl_targets(panel_path: Path) -> dict[str, dict[str, str]]:
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


def orcl_financial_report_url() -> str:
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
    return f"{ORCL_BASE_URL}/feed/FinancialReport.svc/GetFinancialReportList?{urllib.parse.urlencode(params)}"


def expected_form_type(fiscal_period: str) -> str:
    return "10-K" if fiscal_period.endswith("-Q4") else "10-Q"


def collect_orcl_feed_documents(
    targets: dict[str, dict[str, str]],
    source_dir: Path,
) -> list[dict[str, str]]:
    response = fetch_url_json(orcl_financial_report_url())
    write_json(source_dir / "orcl_q4_financial_reports.json", response)

    by_fiscal_period: dict[str, dict[str, Any]] = {}
    for report in response.get("GetFinancialReportListResult", []):
        quarter = Q4_REPORT_TYPES.get(report.get("ReportSubType"))
        year = report.get("ReportYear")
        if not quarter or not year or not report.get("Documents"):
            continue
        by_fiscal_period.setdefault(f"{int(year)}-Q{quarter}", report)

    documents: list[dict[str, str]] = []
    for fiscal_period, target in sorted(targets.items()):
        report = by_fiscal_period.get(fiscal_period)
        if not report:
            for document_kind in ORCL_DOCUMENTS.values():
                documents.append(missing_document(target, document_kind, "", "no Oracle IR report row found"))
            documents.append(missing_document(target, "sec_filing_pdf", expected_form_type(fiscal_period), "no Oracle IR report row found"))
            continue

        docs_by_category = {
            str(doc.get("DocumentCategory") or ""): doc
            for doc in report.get("Documents", [])
            if doc.get("DocumentPath")
        }
        for category, document_kind in ORCL_DOCUMENTS.items():
            doc = docs_by_category.get(category)
            if not doc:
                documents.append(missing_document(target, document_kind, "", f"no {category} document found in Oracle IR feed"))
                continue
            documents.append(
                {
                    **target,
                    "document_kind": document_kind,
                    "form_type": "",
                    "title": doc.get("DocumentTitle") or document_kind,
                    "official_page_url": ORCL_FINANCIALS_URL,
                    "source_url": doc["DocumentPath"],
                    "note": "",
                    "accession_number": "",
                    "filing_date": "",
                }
            )

        form_doc = docs_by_category.get("tenk") or docs_by_category.get("tenq")
        if form_doc and str(form_doc.get("DocumentPath", "")).lower().endswith(".pdf"):
            documents.append(
                {
                    **target,
                    "document_kind": "sec_filing_pdf",
                    "form_type": expected_form_type(fiscal_period),
                    "title": form_doc.get("DocumentTitle") or expected_form_type(fiscal_period),
                    "official_page_url": ORCL_FINANCIALS_URL,
                    "source_url": form_doc["DocumentPath"],
                    "note": "",
                    "accession_number": "",
                    "filing_date": "",
                }
            )
        else:
            note = "Oracle IR feed did not expose a direct filing PDF"
            if form_doc:
                note = f"Oracle IR feed points to non-PDF filing target: {form_doc.get('DocumentPath')}"
            documents.append(missing_document(target, "sec_filing_pdf", expected_form_type(fiscal_period), note))

    return documents


def collect_sec_html_documents(
    targets: dict[str, dict[str, str]],
    source_dir: Path,
) -> list[dict[str, str]]:
    response = fetch_url_json(SEC_SUBMISSIONS_URL)
    write_json(source_dir / f"sec_submissions_CIK{CIK}.json", response)

    filings = list(iter_sec_records(response.get("filings", {}).get("recent", {})))
    for file_info in response.get("filings", {}).get("files", []):
        name = file_info.get("name")
        if not name:
            continue
        historical_url = f"https://data.sec.gov/submissions/{name}"
        historical = fetch_url_json(historical_url)
        write_json(source_dir / name, historical)
        filings.extend(iter_sec_records(historical))
        time.sleep(0.1)

    by_report_period = {
        filing["report_period"]: filing
        for filing in filings
        if filing["form_type"] in {"10-K", "10-Q"} and filing["report_period"]
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


def iter_sec_records(filing_block: dict[str, list[Any]]) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    for index, form in enumerate(filing_block.get("form", [])):
        records.append(
            {
                "form_type": str(form or ""),
                "report_period": get_index_value(filing_block, "reportDate", index),
                "accession_number": get_index_value(filing_block, "accessionNumber", index),
                "filing_date": get_index_value(filing_block, "filingDate", index),
                "primary_document": get_index_value(filing_block, "primaryDocument", index),
                "primary_doc_description": get_index_value(filing_block, "primaryDocDescription", index),
            }
        )
    return records


def get_index_value(values_by_key: dict[str, list[Any]], key: str, index: int) -> str:
    values = values_by_key.get(key, [])
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
        "official_page_url": ORCL_FINANCIALS_URL,
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
    if suffix in {".xlsx", ".xls"}:
        return suffix
    if suffix in {".html", ".htm"}:
        return ".html"
    if stripped.startswith(b"<!doctype html") or stripped.startswith(b"<html") or "html" in content_type:
        return ".html"
    if body.startswith(b"PK") and "spreadsheetml.sheet" in content_type:
        return ".xlsx"
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
        with urllib.request.urlopen(request_url(source_url), timeout=90) as response:
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


def collect_documents(targets: dict[str, dict[str, str]], source_dir: Path) -> list[dict[str, str]]:
    documents = collect_orcl_feed_documents(targets, source_dir)
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
    text = f"""# Oracle IR Document Archive

Local-only archive of Oracle quarterly earnings releases, financial table files, and official 10-K/10-Q filings matching the financial panel period.

Generated: {datetime.now(UTC).isoformat().replace("+00:00", "Z")}

Downloaded files: {downloaded}
Missing rows: {missing}
Error rows: {errored}

## Downloaded By Document Kind

{counts}

## Layout

- `originals/ORCL/earnings_release_pdf/`: Oracle IR earnings release PDFs.
- `originals/ORCL/financial_tables_pdf/`: Oracle IR detailed financial table PDFs.
- `originals/ORCL/financial_tables_xlsx/`: Oracle IR detailed financial table workbooks.
- `originals/ORCL/sec_filing_pdf/`: Oracle IR linked 10-K/10-Q PDFs where the feed exposes direct PDF URLs.
- `originals/ORCL/sec_filing_html/`: SEC EDGAR 10-K/10-Q primary HTML filings.
- `manifest_ORCL.csv` and `manifest_ORCL.json`: metadata, source URLs, local paths, file sizes, and hashes.
- `source/`: raw Oracle Q4 feed and SEC submissions metadata used to discover documents.

## Sources

- Oracle financials: {ORCL_FINANCIALS_URL}
- SEC submissions JSON: {SEC_SUBMISSIONS_URL}
"""
    (output_dir / "README_ORCL.md").write_text(text, encoding="utf-8")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel-path", type=Path, default=DEFAULT_PANEL_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    targets = load_orcl_targets(args.panel_path)
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
    write_json(args.output_dir / "manifest_ORCL.json", manifest_rows)
    write_csv(args.output_dir / "manifest_ORCL.csv", manifest_rows)
    write_readme(args.output_dir, manifest_rows)

    downloaded = sum(1 for row in manifest_rows if row.get("status") == "downloaded")
    missing = sum(1 for row in manifest_rows if row.get("status") == "missing")
    errored = sum(1 for row in manifest_rows if row.get("status") == "error")
    print(f"Wrote Oracle IR document archive manifest to {args.output_dir}")
    print(f"Downloaded: {downloaded}; missing: {missing}; errors: {errored}")
    return 1 if errored else 0


if __name__ == "__main__":
    raise SystemExit(main())
