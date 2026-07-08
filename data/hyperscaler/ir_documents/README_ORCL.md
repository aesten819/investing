# Oracle IR Document Archive

Local-only archive of Oracle quarterly earnings releases, financial table files, and official 10-K/10-Q filings matching the financial panel period.

Generated: 2026-07-05T12:26:44.658978Z

Downloaded files: 59
Missing rows: 1
Error rows: 0

## Downloaded By Document Kind

- earnings_release_pdf: 12
- financial_tables_pdf: 12
- financial_tables_xlsx: 12
- sec_filing_html: 12
- sec_filing_pdf: 11

## Layout

- `originals/ORCL/earnings_release_pdf/`: Oracle IR earnings release PDFs.
- `originals/ORCL/financial_tables_pdf/`: Oracle IR detailed financial table PDFs.
- `originals/ORCL/financial_tables_xlsx/`: Oracle IR detailed financial table workbooks.
- `originals/ORCL/sec_filing_pdf/`: Oracle IR linked 10-K/10-Q PDFs where the feed exposes direct PDF URLs.
- `originals/ORCL/sec_filing_html/`: SEC EDGAR 10-K/10-Q primary HTML filings.
- `manifest_ORCL.csv` and `manifest_ORCL.json`: metadata, source URLs, local paths, file sizes, and hashes.
- `source/`: raw Oracle Q4 feed and SEC submissions metadata used to discover documents.

## Sources

- Oracle financials: https://investor.oracle.com/financials/default.aspx
- SEC submissions JSON: https://data.sec.gov/submissions/CIK0001341439.json
