import rawPanelRows from "../data/hyperscaler/panel/quarterly_hyperscaler_financials.json";
import metadata from "../data/hyperscaler/metadata.json";

export type Ticker = "MSFT" | "AMZN" | "GOOGL" | "META" | "ORCL";

export type RawFinancialRow = {
  ticker: Ticker;
  quarter: string;
  report_period: string;
  fiscal_period: string;
  period: string;
  currency: string;
  capital_expenditure?: number | string | null;
  free_cash_flow?: number | string | null;
  cash_and_equivalents?: number | string | null;
  current_investments?: number | string | null;
  total_debt?: number | string | null;
  revenue?: number | string | null;
  operating_income?: number | string | null;
  net_income?: number | string | null;
  [key: string]: number | string | null | undefined;
};

export type MetricKey = "capex" | "fcf" | "cashAssets" | "totalDebt";

export type MetricDefinition = {
  key: MetricKey;
  label: string;
  shortLabel: string;
  accent: string;
  source: string;
};

export type AggregatePoint = {
  quarter: string;
  capex: number;
  fcf: number;
  cashAssets: number;
  totalDebt: number;
};

export type TickerPoint = {
  quarter: string;
  ticker: Ticker;
  capex: number;
  fcf: number;
  cashAssets: number;
  totalDebt: number;
  revenue: number;
  netIncome: number;
};

export const tickers = metadata.tickers as Ticker[];

export const metricDefinitions: MetricDefinition[] = [
  {
    key: "capex",
    label: "Aggregate Capex",
    shortLabel: "Capex",
    accent: "#ffb000",
    source: "capital_expenditure, absolute value",
  },
  {
    key: "fcf",
    label: "Aggregate Free Cash Flow",
    shortLabel: "FCF",
    accent: "#00d18f",
    source: "net_cash_flow_from_operations - abs(capital_expenditure)",
  },
  {
    key: "cashAssets",
    label: "Cash-Like Assets",
    shortLabel: "Cash Assets",
    accent: "#37a2ff",
    source: "cash_and_equivalents + current_investments",
  },
  {
    key: "totalDebt",
    label: "Cash-Like Liabilities",
    shortLabel: "Debt",
    accent: "#ff5d5d",
    source: "total_debt",
  },
];

const panelRows = rawPanelRows as RawFinancialRow[];

function numericValue(value: number | string | null | undefined): number {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }

  if (typeof value === "string" && value.trim() !== "") {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : 0;
  }

  return 0;
}

function toBillions(value: number): number {
  return value / 1_000_000_000;
}

function rowMetric(row: RawFinancialRow, metric: MetricKey): number {
  if (metric === "capex") {
    return Math.abs(toBillions(numericValue(row.capital_expenditure)));
  }

  if (metric === "fcf") {
    return toBillions(numericValue(row.free_cash_flow));
  }

  if (metric === "cashAssets") {
    return toBillions(
      numericValue(row.cash_and_equivalents) + numericValue(row.current_investments),
    );
  }

  return toBillions(numericValue(row.total_debt));
}

function tickerPoint(row: RawFinancialRow): TickerPoint {
  return {
    quarter: row.quarter,
    ticker: row.ticker,
    capex: rowMetric(row, "capex"),
    fcf: rowMetric(row, "fcf"),
    cashAssets: rowMetric(row, "cashAssets"),
    totalDebt: rowMetric(row, "totalDebt"),
    revenue: toBillions(numericValue(row.revenue)),
    netIncome: toBillions(numericValue(row.net_income)),
  };
}

export const tickerSeries = panelRows
  .map(tickerPoint)
  .sort((a, b) => a.quarter.localeCompare(b.quarter) || a.ticker.localeCompare(b.ticker));

export const quarters = Array.from(new Set(tickerSeries.map((row) => row.quarter))).sort();

export const aggregateSeries: AggregatePoint[] = quarters.map((quarter) => {
  const rows = tickerSeries.filter((row) => row.quarter === quarter);

  return {
    quarter,
    capex: rows.reduce((sum, row) => sum + row.capex, 0),
    fcf: rows.reduce((sum, row) => sum + row.fcf, 0),
    cashAssets: rows.reduce((sum, row) => sum + row.cashAssets, 0),
    totalDebt: rows.reduce((sum, row) => sum + row.totalDebt, 0),
  };
});

export const latestQuarter = quarters.at(-1) ?? "";

export const latestAggregate = aggregateSeries.at(-1) ?? {
  quarter: "",
  capex: 0,
  fcf: 0,
  cashAssets: 0,
  totalDebt: 0,
};

export const latestTickerRows = tickerSeries.filter((row) => row.quarter === latestQuarter);

export function formatBillions(value: number): string {
  const abs = Math.abs(value);
  const precision = abs >= 100 ? 0 : abs >= 10 ? 1 : 2;
  return `${value.toLocaleString("en-US", {
    maximumFractionDigits: precision,
    minimumFractionDigits: precision,
  })}B`;
}

export function metricDefinition(key: MetricKey): MetricDefinition {
  return metricDefinitions.find((metric) => metric.key === key) ?? metricDefinitions[0];
}

export function tickerBreakdown(metric: MetricKey, selectedTickers: Ticker[]): Array<Record<string, number | string>> {
  return quarters.map((quarter) => {
    const point: Record<string, number | string> = { quarter };
    for (const ticker of selectedTickers) {
      const row = tickerSeries.find((item) => item.quarter === quarter && item.ticker === ticker);
      point[ticker] = row ? row[metric] : 0;
    }
    return point;
  });
}

export function latestContribution(metric: MetricKey): Array<{ ticker: Ticker; value: number }> {
  return latestTickerRows
    .map((row) => ({ ticker: row.ticker, value: row[metric] }))
    .sort((a, b) => b.value - a.value);
}
