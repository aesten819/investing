import { useMemo, useState, type CSSProperties } from "react";
import {
  Activity,
  BarChart3,
  CircleDollarSign,
  Database,
  ExternalLink,
  LayoutDashboard,
  LineChart,
  Newspaper,
  Rss,
  Scale,
  ServerCog,
} from "lucide-react";
import EChart, { type ChartOption } from "./EChart";
import {
  aggregateSeries,
  formatBillions,
  latestAggregate,
  latestQuarter,
  latestTickerRows,
  metricDefinition,
  metricDefinitions,
  quarters,
  tickerBreakdown,
  tickers,
  type MetricKey,
  type Ticker,
} from "./data";
import {
  articleHeadline,
  articleSummary,
  articleTags,
  formatNewsDate,
  memoryNewsArticles,
  memoryNewsGeneratedAt,
  memoryNewsSourceFilters,
  memoryNewsSources,
  memoryNewsTags,
  type MemoryNewsArticle,
} from "./memoryNews";
import {
  hyperscalerNewsArticles,
  hyperscalerNewsGeneratedAt,
  hyperscalerNewsSourceFilters,
  hyperscalerNewsSources,
  hyperscalerNewsTags,
  type HyperscalerNewsArticle,
} from "./hyperscalerNews";

const tickerColors: Record<Ticker, string> = {
  MSFT: "#37a2ff",
  AMZN: "#ffb000",
  GOOGL: "#7bd88f",
  META: "#b983ff",
  ORCL: "#ff5d5d",
};

const metricIcons: Record<MetricKey, typeof Activity> = {
  capex: BarChart3,
  fcf: LineChart,
  cashAssets: CircleDollarSign,
  totalDebt: Scale,
};

type PageKey = "hyperscaler" | "memoryNews" | "infraNews";

const navItems: Array<{ key: PageKey; label: string; kicker: string; icon: typeof Activity }> = [
  {
    key: "hyperscaler",
    label: "Hyperscaler",
    kicker: "financials",
    icon: LayoutDashboard,
  },
  {
    key: "memoryNews",
    label: "메모리 뉴스",
    kicker: "semis",
    icon: Newspaper,
  },
  {
    key: "infraNews",
    label: "데이터센터 뉴스",
    kicker: "infra",
    icon: ServerCog,
  },
];

function aggregateOption(metric: MetricKey): ChartOption {
  const definition = metricDefinition(metric);

  return {
    backgroundColor: "transparent",
    color: [definition.accent],
    dataZoom: [
      {
        bottom: 0,
        height: 20,
        borderColor: "#2a2f34",
        fillerColor: "rgba(255, 176, 0, 0.16)",
        handleStyle: { color: definition.accent },
        moveHandleStyle: { color: definition.accent },
        textStyle: { color: "#7d858d" },
        type: "slider",
      },
      { type: "inside" },
    ],
    grid: {
      bottom: 46,
      containLabel: true,
      left: 8,
      right: 18,
      top: 22,
    },
    tooltip: {
      trigger: "axis",
      backgroundColor: "#111418",
      borderColor: "#343a40",
      textStyle: { color: "#f2f4f5" },
      valueFormatter: (value) => `${formatBillions(Number(value))}`,
    },
    xAxis: {
      axisLabel: { color: "#87909a", fontSize: 11 },
      axisLine: { lineStyle: { color: "#2a2f34" } },
      axisTick: { show: false },
      data: aggregateSeries.map((point) => point.quarter),
      type: "category",
    },
    yAxis: {
      axisLabel: {
        color: "#87909a",
        formatter: (value: number) => `${value}`,
      },
      axisLine: { show: false },
      splitLine: { lineStyle: { color: "#22272d" } },
      type: "value",
    },
    series: [
      {
        data: aggregateSeries.map((point) => Number(point[metric].toFixed(2))),
        lineStyle: { color: definition.accent, width: 2 },
        name: definition.shortLabel,
        showSymbol: false,
        smooth: 0.25,
        symbol: "circle",
        type: "line",
      },
    ],
  } as ChartOption;
}

function breakdownOption(metric: MetricKey, selectedTickers: Ticker[]): ChartOption {
  const definition = metricDefinition(metric);
  const data = tickerBreakdown(metric, selectedTickers);

  return {
    backgroundColor: "transparent",
    color: selectedTickers.map((ticker) => tickerColors[ticker]),
    grid: {
      bottom: 30,
      containLabel: true,
      left: 8,
      right: 16,
      top: 34,
    },
    legend: {
      icon: "roundRect",
      itemHeight: 8,
      itemWidth: 16,
      right: 8,
      textStyle: { color: "#a7afb8", fontSize: 11 },
      top: 0,
    },
    tooltip: {
      trigger: "axis",
      axisPointer: { type: "shadow" },
      backgroundColor: "#111418",
      borderColor: "#343a40",
      textStyle: { color: "#f2f4f5" },
      valueFormatter: (value) => `${formatBillions(Number(value))}`,
    },
    xAxis: {
      axisLabel: { color: "#87909a", fontSize: 11 },
      axisLine: { lineStyle: { color: "#2a2f34" } },
      axisTick: { show: false },
      data: data.map((point) => point.quarter),
      type: "category",
    },
    yAxis: {
      axisLabel: { color: "#87909a" },
      axisLine: { show: false },
      splitLine: { lineStyle: { color: "#22272d" } },
      type: "value",
    },
    series: selectedTickers.map((ticker) => ({
      barMaxWidth: 22,
      data: data.map((point) => Number(point[ticker])),
      emphasis: { focus: "series" },
      name: ticker,
      stack: definition.key,
      type: "bar",
    })),
  } as ChartOption;
}

function metricDelta(metric: MetricKey): number {
  const current = aggregateSeries.at(-1)?.[metric] ?? 0;
  const previous = aggregateSeries.at(-2)?.[metric] ?? 0;
  return current - previous;
}

function MetricButton({
  metric,
  selected,
  onSelect,
}: {
  metric: MetricKey;
  selected: boolean;
  onSelect: (metric: MetricKey) => void;
}) {
  const definition = metricDefinition(metric);
  const Icon = metricIcons[metric];

  return (
    <button
      className={`metric-button ${selected ? "active" : ""}`}
      onClick={() => onSelect(metric)}
      style={{ "--metric-accent": definition.accent } as CSSProperties}
      title={definition.source}
      type="button"
    >
      <Icon aria-hidden="true" size={16} />
      <span>{definition.shortLabel}</span>
    </button>
  );
}

function StatCell({ metric }: { metric: MetricKey }) {
  const definition = metricDefinition(metric);
  const delta = metricDelta(metric);
  const positive = delta >= 0;

  return (
    <div className="stat-cell">
      <div className="stat-label">{definition.shortLabel}</div>
      <div className="stat-value">{formatBillions(latestAggregate[metric])}</div>
      <div className={positive ? "stat-delta positive" : "stat-delta negative"}>
        {positive ? "+" : ""}
        {formatBillions(delta)} QoQ
      </div>
    </div>
  );
}

function TickerToggle({
  ticker,
  selected,
  onToggle,
}: {
  ticker: Ticker;
  selected: boolean;
  onToggle: (ticker: Ticker) => void;
}) {
  return (
    <button
      className={`ticker-toggle ${selected ? "active" : ""}`}
      onClick={() => onToggle(ticker)}
      style={{ "--ticker-color": tickerColors[ticker] } as CSSProperties}
      title={`${ticker} toggle`}
      type="button"
    >
      {ticker}
    </button>
  );
}

function HyperscalerPage() {
  const [activeMetric, setActiveMetric] = useState<MetricKey>("capex");
  const [selectedTickers, setSelectedTickers] = useState<Ticker[]>(tickers);

  const selectedDefinition = metricDefinition(activeMetric);
  const topChart = useMemo(() => aggregateOption(activeMetric), [activeMetric]);
  const breakdownChart = useMemo(
    () => breakdownOption(activeMetric, selectedTickers),
    [activeMetric, selectedTickers],
  );

  function toggleTicker(ticker: Ticker) {
    setSelectedTickers((current) => {
      if (current.includes(ticker)) {
        return current.length === 1 ? current : current.filter((item) => item !== ticker);
      }

      return tickers.filter((item) => item === ticker || current.includes(item));
    });
  }

  return (
    <section className="app-shell">
      <header className="top-bar">
        <div>
          <div className="eyebrow">HYPR INFRA</div>
          <h1>Hyperscaler Infrastructure Monitor</h1>
        </div>
        <div className="header-meta">
          <span>{latestQuarter}</span>
          <span>{quarters.length} quarters</span>
          <span>{tickers.length} tickers</span>
        </div>
      </header>

      <section className="hero-grid">
        <div className="primary-panel">
          <div className="panel-header">
            <div>
              <div className="section-kicker">5-company aggregate</div>
              <h2>{selectedDefinition.label}</h2>
            </div>
            <div className="metric-controls">
              {metricDefinitions.map((metric) => (
                <MetricButton
                  key={metric.key}
                  metric={metric.key}
                  onSelect={setActiveMetric}
                  selected={metric.key === activeMetric}
                />
              ))}
            </div>
          </div>
          <EChart className="aggregate-chart" option={topChart} />
        </div>

        <aside className="stat-panel">
          <div className="stat-header">
            <Database aria-hidden="true" size={17} />
            <span>Latest Aggregate</span>
          </div>
          {metricDefinitions.map((metric) => (
            <StatCell key={metric.key} metric={metric.key} />
          ))}
        </aside>
      </section>

      <section className="analysis-grid">
        <div className="secondary-panel">
          <div className="panel-header compact">
            <div>
              <div className="section-kicker">ticker contribution</div>
              <h2>{selectedDefinition.shortLabel} Breakdown</h2>
            </div>
            <div className="ticker-controls">
              {tickers.map((ticker) => (
                <TickerToggle
                  key={ticker}
                  onToggle={toggleTicker}
                  selected={selectedTickers.includes(ticker)}
                  ticker={ticker}
                />
              ))}
            </div>
          </div>
          <EChart className="breakdown-chart" option={breakdownChart} />
        </div>

        <div className="secondary-panel">
          <div className="panel-header compact">
            <div>
              <div className="section-kicker">latest quarter</div>
              <h2>Company Snapshot</h2>
            </div>
          </div>
          <div className="data-table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Ticker</th>
                  <th>Capex</th>
                  <th>FCF</th>
                  <th>Cash Assets</th>
                  <th>Debt</th>
                  <th>Revenue</th>
                  <th>Net Income</th>
                </tr>
              </thead>
              <tbody>
                {latestTickerRows.map((row) => (
                  <tr key={row.ticker}>
                    <td>
                      <span className="ticker-dot" style={{ backgroundColor: tickerColors[row.ticker] }} />
                      {row.ticker}
                    </td>
                    <td>{formatBillions(row.capex)}</td>
                    <td>{formatBillions(row.fcf)}</td>
                    <td>{formatBillions(row.cashAssets)}</td>
                    <td>{formatBillions(row.totalDebt)}</td>
                    <td>{formatBillions(row.revenue)}</td>
                    <td>{formatBillions(row.netIncome)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </section>
    </section>
  );
}

type NewsCardArticle = MemoryNewsArticle | HyperscalerNewsArticle;

function NewsCard({ article }: { article: NewsCardArticle }) {
  const headline = articleHeadline(article);
  const summary = articleSummary(article);
  const tags = articleTags(article);

  return (
    <article className="news-card">
      <div className="news-card-meta">
        <span>{article.source}</span>
        <time dateTime={article.published_at}>{formatNewsDate(article.published_at)}</time>
      </div>
      <h2>{headline}</h2>
      <p>{summary}</p>
      <div className="news-card-footer">
        <div className="news-tags">
          {tags.map((tag) => (
            <span key={tag}>{tag}</span>
          ))}
        </div>
        <a className="news-link" href={article.url} rel="noreferrer" target="_blank">
          <span>원문</span>
          <ExternalLink aria-hidden="true" size={14} />
        </a>
      </div>
    </article>
  );
}

function MemoryNewsPage() {
  const [selectedSource, setSelectedSource] = useState("all");
  const visibleArticles = useMemo(() => {
    if (selectedSource === "all") {
      return memoryNewsArticles;
    }

    return memoryNewsArticles.filter((article) => article.source_id === selectedSource);
  }, [selectedSource]);

  const healthySourceCount = memoryNewsSources.filter((source) => source.status === "ok").length;

  return (
    <section className="app-shell">
      <header className="top-bar">
        <div>
          <div className="eyebrow">MEMORY SEMIS</div>
          <h1>메모리 반도체 뉴스</h1>
        </div>
        <div className="header-meta">
          <span>{formatNewsDate(memoryNewsGeneratedAt)}</span>
          <span>{memoryNewsArticles.length}개 기사</span>
          <span>{healthySourceCount}개 소스</span>
        </div>
      </header>

      <section className="news-control-band">
        <div className="source-filter-row">
          {memoryNewsSourceFilters.map((source) => (
            <button
              className={`source-filter ${source.id === selectedSource ? "active" : ""}`}
              key={source.id}
              onClick={() => setSelectedSource(source.id)}
              type="button"
            >
              {source.name}
            </button>
          ))}
        </div>
        <div className="tag-strip">
          {memoryNewsTags.map((tag) => (
            <span key={tag}>{tag}</span>
          ))}
        </div>
      </section>

      <section className="news-grid">
        {visibleArticles.map((article) => (
          <NewsCard article={article} key={article.id} />
        ))}
      </section>
    </section>
  );
}

function InfraNewsPage() {
  const [selectedSource, setSelectedSource] = useState("all");
  const visibleArticles = useMemo(() => {
    if (selectedSource === "all") {
      return hyperscalerNewsArticles;
    }

    return hyperscalerNewsArticles.filter((article) => article.source_id === selectedSource);
  }, [selectedSource]);

  const healthySourceCount = hyperscalerNewsSources.filter((source) => source.status === "ok").length;

  return (
    <section className="app-shell">
      <header className="top-bar">
        <div>
          <div className="eyebrow">AI INFRA</div>
          <h1>하이퍼스케일러·데이터센터 뉴스</h1>
        </div>
        <div className="header-meta">
          <span>{formatNewsDate(hyperscalerNewsGeneratedAt)}</span>
          <span>{hyperscalerNewsArticles.length}개 기사</span>
          <span>{healthySourceCount}개 소스</span>
        </div>
      </header>

      <section className="news-control-band">
        <div className="source-filter-row">
          {hyperscalerNewsSourceFilters.map((source) => (
            <button
              className={`source-filter ${source.id === selectedSource ? "active" : ""}`}
              key={source.id}
              onClick={() => setSelectedSource(source.id)}
              type="button"
            >
              {source.name}
            </button>
          ))}
        </div>
        <div className="tag-strip">
          {hyperscalerNewsTags.map((tag) => (
            <span key={tag}>{tag}</span>
          ))}
        </div>
      </section>

      <section className="news-grid">
        {visibleArticles.map((article) => (
          <NewsCard article={article} key={article.id} />
        ))}
      </section>
    </section>
  );
}

export default function App() {
  const [activePage, setActivePage] = useState<PageKey>("hyperscaler");

  return (
    <main className="app-layout">
      <aside className="side-bar">
        <div className="side-brand">
          <div className="eyebrow">RESEARCH</div>
          <strong>Investing Desk</strong>
        </div>
        <nav className="side-nav" aria-label="Research pages">
          {navItems.map((item) => {
            const Icon = item.icon;
            return (
              <button
                aria-current={activePage === item.key ? "page" : undefined}
                className={`side-nav-button ${activePage === item.key ? "active" : ""}`}
                key={item.key}
                onClick={() => setActivePage(item.key)}
                type="button"
              >
                <Icon aria-hidden="true" size={18} />
                <span>
                  <small>{item.kicker}</small>
                  {item.label}
                </span>
              </button>
            );
          })}
        </nav>
        <div className="side-status">
          <Rss aria-hidden="true" size={15} />
          <span>{memoryNewsArticles.length + hyperscalerNewsArticles.length}개 뉴스 카드</span>
        </div>
      </aside>

      <div className="page-frame">
        {activePage === "hyperscaler" && <HyperscalerPage />}
        {activePage === "memoryNews" && <MemoryNewsPage />}
        {activePage === "infraNews" && <InfraNewsPage />}
      </div>
    </main>
  );
}
