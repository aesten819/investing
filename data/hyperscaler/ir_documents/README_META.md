# Meta IR Document Archive

Local-only archive of Meta quarterly earnings releases, earnings slides, downloadable statement files when available, and official 10-K/10-Q filings matching the financial panel period.

Generated: 2026-07-04T19:51:44.734974Z

Downloaded files: 43
Missing rows: 35
Error rows: 0

## Downloaded By Document Kind

- balance_sheet_xlsx: 1
- earnings_release_pdf: 13
- earnings_slides_pdf: 13
- income_statement_xlsx: 1
- sec_filing_html: 13
- sec_filing_pdf: 2

## Layout

- `originals/META/earnings_release_pdf/`: Meta IR earnings release PDFs.
- `originals/META/earnings_slides_pdf/`: Meta IR earnings slide PDFs.
- `originals/META/balance_sheet_xlsx/`: Meta IR downloadable balance sheet workbooks, where the IR feed provides them.
- `originals/META/income_statement_xlsx/`: Meta IR downloadable income statement workbooks, where the IR feed provides them.
- `originals/META/sec_filing_pdf/`: Meta IR linked 10-K/10-Q PDFs where the feed exposes direct PDF URLs.
- `originals/META/sec_filing_html/`: SEC EDGAR 10-K/10-Q primary HTML filings.
- `manifest_META.csv` and `manifest_META.json`: metadata, source URLs, local paths, file sizes, and hashes.
- `source/`: raw Meta Q4 feed and SEC submissions metadata used to discover documents.

## Sources

- Meta financials: https://investor.atmeta.com/financials/
- SEC submissions JSON: https://data.sec.gov/submissions/CIK0001326801.json
