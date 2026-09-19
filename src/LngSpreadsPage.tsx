import { useEffect, useMemo, useState } from "react";
import { Download, ExternalLink, Flame, RefreshCw } from "lucide-react";
import EChart, { type ChartOption } from "./EChart";
import { money, parseLngSnapshot, rangeRows, type LngSnapshot, type LngRow, type SpreadKey } from "./lngData";
import "./lng.css";

const series = [
  { key: "ttf_spread", label: "유럽–미국", short: "TTF−HH", color: "#579cff", className: "ttf" },
  { key: "jkm_spread", label: "동북아–미국", short: "JKM−HH", color: "#ffb043", className: "jkm" },
] as const;
const periods = [{ months: 1, label: "1개월" }, { months: 3, label: "3개월" }, { months: 6, label: "6개월" }, { months: 12, label: "1년" }, { months: 36, label: "3년" }];

function chartOption(rows: LngRow[], visible: SpreadKey[]): ChartOption {
  return {
    animation: false,
    backgroundColor: "transparent",
    grid: { left: 12, right: 18, top: 35, bottom: 64, containLabel: true },
    tooltip: {
      trigger: "axis", confine: true, backgroundColor: "#151a20", borderColor: "#39434e",
      textStyle: { color: "#f4f1e8", fontSize: 13 },
      valueFormatter: value => `${money(value == null ? null : Number(value), true)} / MMBtu`,
    },
    xAxis: {
      type: "category", boundaryGap: false, data: rows.map(row => row.date),
      axisLine: { lineStyle: { color: "#39434e" } }, axisTick: { show: false },
      axisLabel: { color: "#aab4bf", hideOverlap: true, fontSize: 11 },
    },
    yAxis: {
      type: "value", name: "$/MMBtu", nameTextStyle: { color: "#aab4bf", align: "left" },
      axisLabel: { color: "#aab4bf", formatter: (value: number) => `$${value}` },
      splitLine: { lineStyle: { color: "#252d36", type: "dashed" } },
    },
    dataZoom: [{ type: "slider", bottom: 4, height: 22, borderColor: "#303944", textStyle: { color: "#aab4bf" },
      fillerColor: "rgba(87,156,255,.12)", handleStyle: { color: "#579cff" } }],
    series: series.filter(item => visible.includes(item.key)).map(item => ({
      name: `${item.label} (${item.short})`, type: "line", showSymbol: false, connectNulls: false,
      smooth: false, color: item.color, lineStyle: { color: item.color, width: 2 },
      emphasis: { focus: "series" }, data: rows.map(row => row[item.key]),
    })),
  };
}

function SpreadCard({ data, index }: { data: LngSnapshot; index: number }) {
  const item = series[index];
  const latest = data.latest;
  const price = item.key === "ttf_spread" ? latest.ttf_usd : latest.jkm;
  return <article className={`lng-stat ${item.className}`}>
    <div className="lng-stat-label"><span className="lng-line-key" />{item.label} <span>({item.short})</span></div>
    <div className="lng-value">{money(latest[item.key], true)}</div>
    <div className="lng-unit">$/MMBtu</div>
    <dl className="lng-changes">
      {([ ["day", "전일"], ["week", "1주"], ["month", "1개월"] ] as const).map(([key, label]) => {
        const change = data.changes[item.key][key];
        return <div key={key} title={change.date ? `${change.date} 대비 · $/MMBtu` : "비교 데이터 없음"}>
          <dt>{label}</dt><dd className={change.value === null || change.value === 0 ? "" : change.value > 0 ? "lng-up" : "lng-down"}>
            {money(change.value, true)}
          </dd>
        </div>;
      })}
    </dl>
    <p className="lng-ratio">HH 대비 <strong>{price !== null && latest.hh ? (price / latest.hh).toFixed(1) : "—"}배</strong></p>
  </article>;
}

function downloadCsv(rows: LngRow[]) {
  const keys = ["date", "hh", "ttf_eur", "eurusd", "ttf_usd", "jkm", "ttf_spread", "jkm_spread"] as const;
  const header = "Date,HH (USD/MMBtu),TTF (EUR/MWh),EURUSD (USD/EUR),TTF (USD/MMBtu),JKM (USD/MMBtu),TTF-HH (USD/MMBtu),JKM-HH (USD/MMBtu)";
  const content = [header, ...rows.map(row => keys.map(key => row[key] ?? "").join(","))].join("\r\n");
  const url = URL.createObjectURL(new Blob(["\uFEFF", content], { type: "text/csv;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url; link.download = `lng-spreads-${rows[0]?.date}-${rows.at(-1)?.date}.csv`;
  document.body.appendChild(link); link.click(); link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function Dashboard({ data }: { data: LngSnapshot }) {
  const [months, setMonths] = useState(36);
  const [visible, setVisible] = useState<SpreadKey[]>(["ttf_spread", "jkm_spread"]);
  const rows = useMemo(() => rangeRows(data, months), [data, months]);
  const option = useMemo(() => chartOption(rows, visible), [rows, visible]);
  const stale = Date.now() - Date.parse(`${data.as_of}T00:00:00Z`) > 7 * 86400000;
  const updated = new Intl.DateTimeFormat("ko-KR", { timeZone: "Asia/Seoul", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date(data.generated_at));
  return <>
    <header className="top-bar">
      <div><div className="eyebrow">ENERGY / NATURAL GAS</div><h1>LNG 가격 스프레드</h1><p className="lng-subtitle">유럽·동북아와 미국 천연가스의 가격차</p></div>
      <div className="header-meta"><span>기준 {data.as_of}</span><span>근월물 일별 종가</span></div>
    </header>
    {stale && <p className="lng-notice" role="status">최신 공통 관측일이 7일 이상 지났습니다. {data.as_of}의 마지막 정상 데이터를 표시합니다.</p>}
    <section className="lng-panel" aria-label="LNG 스프레드 시계열">
      <div className="lng-panel-heading"><p>미국 가스 대비 해외 가격 프리미엄</p><span>액화·운송비 차감 전</span></div>
      <div className="lng-stats">
        <SpreadCard data={data} index={0} /><SpreadCard data={data} index={1} />
        <article className="lng-stat lng-prices">
          <div className="lng-stat-label">기준 가격 <span>({data.as_of})</span></div>
          <dl>
            <div><dt>Henry Hub <small>미국</small></dt><dd>{money(data.latest.hh)}</dd></div>
            <div><dt>TTF <small>유럽 · 환산</small></dt><dd>{money(data.latest.ttf_usd)}</dd></div>
            <div><dt>JKM <small>동북아</small></dt><dd>{money(data.latest.jkm)}</dd></div>
          </dl>
          <div className="lng-unit">$/MMBtu · TTF 원가격 €{data.latest.ttf_eur?.toFixed(2)}/MWh</div>
          <div className="lng-fx">EUR/USD {data.latest.eurusd?.toFixed(4)}</div>
        </article>
      </div>
      <div className="lng-chart-toolbar">
        <div><h2>TTF−HH · JKM−HH</h2><p>{rows[0]?.date} — {rows.at(-1)?.date}</p></div>
        <div className="lng-range-controls" role="group" aria-label="차트 기간">
          {periods.map(period => <button type="button" key={period.months} aria-pressed={months === period.months}
            className={months === period.months ? "active" : ""} onClick={() => setMonths(period.months)}>{period.label}</button>)}
        </div>
      </div>
      <div role="img" aria-label={`${rows[0]?.date}부터 ${data.as_of}까지 LNG 가격차 추이. 최신 TTF-HH ${money(data.latest.ttf_spread)}, JKM-HH ${money(data.latest.jkm_spread)}. 아래 관측값 표와 CSV에서 수치를 확인할 수 있습니다.`}>
        <EChart className="lng-chart" option={option} />
      </div>
      <div className="lng-legend" role="group" aria-label="표시할 스프레드">
        {series.map(item => <button key={item.key} type="button" className={`${item.className} ${visible.includes(item.key) ? "selected" : ""}`}
          aria-pressed={visible.includes(item.key)} onClick={() => setVisible(current => current.includes(item.key)
            ? current.length > 1 ? current.filter(key => key !== item.key) : current : [...current, item.key])}>
          <span className="lng-line-key" />{item.label} ({item.short})
        </button>)}
      </div>
      <footer className="lng-source-note">
        <p>출처: Yahoo Finance 선물 근월물 연속 시계열 · TTF 환산: EUR/MWh × 0.293071 × EUR/USD</p>
        <p>스프레드는 액화비·운송비·재기화비 차감 전 가격차입니다. 종목별 인도월·종가 시각과 롤오버가 달라 실제 거래 마진과 차이가 날 수 있습니다.</p>
        <p>갱신 {updated} KST · 매일 08:40 KST 갱신 시도 · 기준일은 네 원천의 최신 공통 관측일</p>
      </footer>
    </section>
    <section className="lng-details-panel">
      <div className="lng-detail-actions"><div><h2>데이터 확인</h2><p>같은 날짜의 종가와 환율로 계산합니다. 결측값은 채우지 않습니다.</p></div>
        <button className="lng-download" type="button" onClick={() => downloadCsv(rows)}><Download size={15} aria-hidden="true" />선택 기간 CSV</button>
      </div>
      <details><summary>최근 관측값 · 계산 방법 · 출처</summary>
        <div className="data-table-wrap"><table className="data-table lng-table"><caption>최근 10개 관측일 · 단위 $/MMBtu · —는 원천 결측</caption>
          <thead><tr><th scope="col">날짜</th><th scope="col">Henry Hub</th><th scope="col">TTF 환산</th><th scope="col">JKM</th><th scope="col">TTF−HH</th><th scope="col">JKM−HH</th></tr></thead>
          <tbody>{rows.slice(-10).reverse().map(row => <tr key={row.date}><th scope="row">{row.date}</th>{(["hh", "ttf_usd", "jkm", "ttf_spread", "jkm_spread"] as const).map(key => <td key={key}>{money(row[key], key.includes("spread"))}</td>)}</tr>)}</tbody>
        </table></div>
        <div className="lng-method"><p><strong>계산:</strong> TTF−HH = TTF(EUR/MWh) × 0.2930710702 × EUR/USD − HH. JKM−HH = JKM − HH.</p>
          <p><strong>변화량:</strong> 전일은 직전 공통 관측일, 1주·1개월은 각각 7일 전·전월 같은 날짜 또는 그 이전의 가장 가까운 공통 관측일 대비입니다. 비교일에서 7일을 넘겨 소급하지 않습니다. 카드에 마우스를 올리면 비교 기준일을 볼 수 있습니다.</p>
          <p><strong>자료:</strong> 현물 지표의 직접 구독값이 아닌 선물 연속 시계열입니다. 당일 진행 중인 세션은 제외합니다. 원천 누락 시 해당 선을 끊고, 수집 실패 시 마지막 정상 자료를 유지합니다.</p>
          <ul>{Object.values(data.sources).map(source => <li key={source.symbol}><a href={source.url} target="_blank" rel="noreferrer">{source.name} · {source.symbol}<ExternalLink size={12} aria-hidden="true" /></a><span>{source.unit} · 원천 최신일 {source.latest_date}</span></li>)}</ul>
        </div>
      </details>
    </section>
  </>;
}

export default function LngSpreadsPage() {
  const [data, setData] = useState<LngSnapshot | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setError("");
    fetch(`${import.meta.env.BASE_URL}lng/spreads.json`, { signal: controller.signal, cache: "no-cache" })
      .then(response => { if (!response.ok) throw new Error(`데이터 요청 실패 (${response.status})`); return response.json(); })
      .then(value => setData(parseLngSnapshot(value)))
      .catch(error => { if (!controller.signal.aborted) setError(error instanceof Error ? error.message : "데이터를 불러오지 못했습니다."); });
    return () => controller.abort();
  }, [attempt]);
  return <section className="app-shell lng-page">
    {data ? <Dashboard data={data} /> : <div className="lng-loading" role={error ? "alert" : "status"}>
      <Flame size={28} aria-hidden="true" /><h1>LNG 가격 스프레드</h1><p>{error || "LNG 가격 데이터를 불러오는 중입니다."}</p>
      {error && <button type="button" className="lng-download" onClick={() => setAttempt(value => value + 1)}><RefreshCw size={16} aria-hidden="true" />다시 시도</button>}
    </div>}
  </section>;
}
