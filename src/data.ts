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
  gross_profit?: number | string | null;
  operating_income?: number | string | null;
  net_income?: number | string | null;
  [key: string]: number | string | null | undefined;
};

export type MetricKey =
  | "capex"
  | "fcf"
  | "cashAssets"
  | "totalDebt"
  | "revenue"
  | "grossMargin"
  | "operatingIncome"
  | "operatingMargin";

export type MetricUnit = "billions" | "percent";

export type MetricDefinition = {
  key: MetricKey;
  label: string;
  shortLabel: string;
  accent: string;
  source: string;
  unit: MetricUnit;
};

export type AggregatePoint = {
  quarter: string;
  capex: number;
  fcf: number;
  cashAssets: number;
  totalDebt: number;
  revenue: number;
  grossMargin: number;
  operatingIncome: number;
  operatingMargin: number;
};

export type TickerPoint = {
  quarter: string;
  ticker: Ticker;
  capex: number;
  fcf: number;
  cashAssets: number;
  totalDebt: number;
  revenue: number;
  grossProfit: number;
  grossMargin: number;
  operatingIncome: number;
  operatingMargin: number;
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
    unit: "billions",
  },
  {
    key: "fcf",
    label: "Aggregate Free Cash Flow",
    shortLabel: "FCF",
    accent: "#00d18f",
    source: "net_cash_flow_from_operations - abs(capital_expenditure)",
    unit: "billions",
  },
  {
    key: "cashAssets",
    label: "Cash-Like Assets",
    shortLabel: "Cash Assets",
    accent: "#37a2ff",
    source: "cash_and_equivalents + current_investments",
    unit: "billions",
  },
  {
    key: "totalDebt",
    label: "Cash-Like Liabilities",
    shortLabel: "Debt",
    accent: "#ff5d5d",
    source: "total_debt",
    unit: "billions",
  },
  {
    key: "revenue",
    label: "Aggregate Revenue",
    shortLabel: "Revenue",
    accent: "#9ecbff",
    source: "revenue",
    unit: "billions",
  },
  {
    key: "grossMargin",
    label: "Aggregate Gross Margin",
    shortLabel: "Gross Margin",
    accent: "#2dd4bf",
    source: "gross_profit / revenue",
    unit: "percent",
  },
  {
    key: "operatingIncome",
    label: "Aggregate Operating Income",
    shortLabel: "Op Income",
    accent: "#ff8c42",
    source: "operating_income",
    unit: "billions",
  },
  {
    key: "operatingMargin",
    label: "Aggregate Operating Margin",
    shortLabel: "Op Margin",
    accent: "#f472b6",
    source: "operating_income / revenue",
    unit: "percent",
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

function percent(numerator: number, denominator: number): number {
  return denominator === 0 ? 0 : (numerator / denominator) * 100;
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

  if (metric === "totalDebt") {
    return toBillions(numericValue(row.total_debt));
  }

  if (metric === "revenue") {
    return toBillions(numericValue(row.revenue));
  }

  if (metric === "grossMargin") {
    return percent(numericValue(row.gross_profit), numericValue(row.revenue));
  }

  if (metric === "operatingIncome") {
    return toBillions(numericValue(row.operating_income));
  }

  return percent(numericValue(row.operating_income), numericValue(row.revenue));
}

function tickerPoint(row: RawFinancialRow): TickerPoint {
  const revenue = rowMetric(row, "revenue");
  const grossProfit = toBillions(numericValue(row.gross_profit));
  const operatingIncome = rowMetric(row, "operatingIncome");

  return {
    quarter: row.quarter,
    ticker: row.ticker,
    capex: rowMetric(row, "capex"),
    fcf: rowMetric(row, "fcf"),
    cashAssets: rowMetric(row, "cashAssets"),
    totalDebt: rowMetric(row, "totalDebt"),
    revenue,
    grossProfit,
    grossMargin: rowMetric(row, "grossMargin"),
    operatingIncome,
    operatingMargin: rowMetric(row, "operatingMargin"),
    netIncome: toBillions(numericValue(row.net_income)),
  };
}

export const tickerSeries = panelRows
  .map(tickerPoint)
  .sort((a, b) => a.quarter.localeCompare(b.quarter) || a.ticker.localeCompare(b.ticker));

export const quarters = Array.from(new Set(tickerSeries.map((row) => row.quarter))).sort();
export const commonQuarters = quarters.filter((quarter) =>
  tickers.every((ticker) => tickerSeries.some((row) => row.quarter === quarter && row.ticker === ticker)),
);

export const aggregateSeries: AggregatePoint[] = commonQuarters.map((quarter) => {
  const rows = tickerSeries.filter((row) => row.quarter === quarter);
  const revenue = rows.reduce((sum, row) => sum + row.revenue, 0);
  const grossProfit = rows.reduce((sum, row) => sum + row.grossProfit, 0);
  const operatingIncome = rows.reduce((sum, row) => sum + row.operatingIncome, 0);

  return {
    quarter,
    capex: rows.reduce((sum, row) => sum + row.capex, 0),
    fcf: rows.reduce((sum, row) => sum + row.fcf, 0),
    cashAssets: rows.reduce((sum, row) => sum + row.cashAssets, 0),
    totalDebt: rows.reduce((sum, row) => sum + row.totalDebt, 0),
    revenue,
    grossMargin: percent(grossProfit, revenue),
    operatingIncome,
    operatingMargin: percent(operatingIncome, revenue),
  };
});

export const latestQuarter = commonQuarters.at(-1) ?? "";

export const latestAggregate = aggregateSeries.at(-1) ?? {
  quarter: "",
  capex: 0,
  fcf: 0,
  cashAssets: 0,
  totalDebt: 0,
  revenue: 0,
  grossMargin: 0,
  operatingIncome: 0,
  operatingMargin: 0,
};

export const latestTickerRows = tickerSeries.filter((row) => row.quarter === latestQuarter);
export const latestQuarterByTicker = Object.fromEntries(
  tickers.map((ticker) => {
    const tickerRows = tickerSeries.filter((row) => row.ticker === ticker);
    return [ticker, tickerRows.at(-1)?.quarter ?? ""];
  }),
) as Record<Ticker, string>;

export function formatBillions(value: number): string {
  const abs = Math.abs(value);
  const precision = abs >= 100 ? 0 : abs >= 10 ? 1 : 2;
  return `${value.toLocaleString("en-US", {
    maximumFractionDigits: precision,
    minimumFractionDigits: precision,
  })}B`;
}

export function formatPercent(value: number): string {
  const precision = Math.abs(value) >= 10 ? 1 : 2;
  return `${value.toLocaleString("en-US", {
    maximumFractionDigits: precision,
    minimumFractionDigits: precision,
  })}%`;
}

export function formatMetricValue(metric: MetricKey, value: number): string {
  return metricDefinition(metric).unit === "percent" ? formatPercent(value) : formatBillions(value);
}

export function formatMetricDelta(metric: MetricKey, value: number): string {
  const sign = value >= 0 ? "+" : "";
  return metricDefinition(metric).unit === "percent"
    ? `${sign}${value.toLocaleString("en-US", {
        maximumFractionDigits: 1,
        minimumFractionDigits: 1,
      })}pp`
    : `${sign}${formatBillions(value)}`;
}

export function metricDefinition(key: MetricKey): MetricDefinition {
  return metricDefinitions.find((metric) => metric.key === key) ?? metricDefinitions[0];
}

export function tickerBreakdown(metric: MetricKey, selectedTickers: Ticker[]): Array<Record<string, number | string>> {
  return commonQuarters.map((quarter) => {
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
