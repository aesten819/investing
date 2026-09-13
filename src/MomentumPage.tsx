import { useEffect, useMemo, useState } from "react";
import {
  ArrowDownLeft,
  ArrowDownRight,
  ArrowUpLeft,
  ArrowUpRight,
  Check,
  ChevronLeft,
  ChevronRight,
  ExternalLink,
  Globe2,
  Info,
  RefreshCw,
  Search,
} from "lucide-react";
import MomentumMap from "./MomentumMap";
import {
  fetchManifest,
  fetchProfile,
  fmt,
  groupLabels,
  liquidityLabel,
  pointColor,
  quadrantLabels,
  signed,
  statusLabel,
  type Manifest,
  type Profile,
  type ProfileEntry,
  type Point,
} from "./momentumData";
import "./momentum.css";

function useHash() {
  const [hash, setHash] = useState(window.location.hash);
  useEffect(() => {
    const change = () => setHash(window.location.hash);
    window.addEventListener("hashchange", change);
    return () => window.removeEventListener("hashchange", change);
  }, []);
  return new URLSearchParams(hash.split("?")[1] || "");
}
function navigate(profile: string, date?: string) {
  const p = new URLSearchParams({ profile });
  if (date) p.set("date", date);
  window.location.hash = `/momentum?${p}`;
}
const status = (s: string) => statusLabel[s] || "확인 필요";
const quadrants = [
  {
    key: "improving",
    label: "턴어라운드",
    Icon: ArrowUpLeft,
    description: "강도 ↓ · 가속 ↑",
  },
  {
    key: "leading",
    label: "리드",
    Icon: ArrowUpRight,
    description: "강도 ↑ · 가속 ↑",
  },
  {
    key: "lagging",
    label: "부진",
    Icon: ArrowDownLeft,
    description: "강도 ↓ · 가속 ↓",
  },
  {
    key: "weakening",
    label: "둔화",
    Icon: ArrowDownRight,
    description: "강도 ↑ · 가속 ↓",
  },
];

export default function MomentumPage() {
  const params = useHash();
  const [manifest, setManifest] = useState<Manifest | null>(null);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  const [selected, setSelected] = useState<string | null>(null);
  const [levels, setLevels] = useState([0.8, 0.95, 0.99]);
  const [labels, setLabels] = useState(true);
  const [query, setQuery] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    setError("");
    fetchManifest(controller.signal)
      .then(setManifest)
      .catch((e) => {
        if (e.name !== "AbortError") setError(e.message);
      });
    return () => controller.abort();
  }, [retry]);
  const requested = params.get("profile");
  const entry =
    manifest?.profiles.find((p) => p.id === requested) ||
    manifest?.profiles.find((p) => p.id === "global_binance");
  useEffect(() => {
    if (!entry) return;
    const controller = new AbortController();
    setError("");
    setProfile(null);
    setSelected(null);
    setQuery("");
    fetchProfile(entry, controller.signal)
      .then((p) => {
        if (!controller.signal.aborted) setProfile(p);
      })
      .catch((e) => {
        if (e.name !== "AbortError") setError(e.message);
      });
    return () => controller.abort();
  }, [entry?.file, retry]);
  const requestedDate = params.get("date");
  const day =
    profile?.days.find((d) => d.date === requestedDate) ||
    profile?.days.find((d) => d.date === entry?.default_date) ||
    profile?.days.at(-1);
  const assets = useMemo(
    () => Object.fromEntries((profile?.assets || []).map((a) => [a.key, a])),
    [profile],
  );
  const chosen = day?.points.find((p) => p.key === selected);
  const chosenAsset = chosen ? assets[chosen.key] : null;
  const filtered =
    day?.points.filter((p) =>
      `${assets[p.key].label} ${assets[p.key].ticker}`
        .toLowerCase()
        .includes(query.toLowerCase()),
    ) || [];
  const ranked = [...filtered]
    .filter((p) => p.rank !== null)
    .sort(
      (a, b) =>
        a.rank! - b.rank! ||
        assets[a.key].ticker.localeCompare(assets[b.key].ticker),
    );
  const valid =
    day?.points.filter((p) => p.status === "complete_candidate") || [];
  const withheld =
    day?.points.filter((p) => p.status !== "complete_candidate") || [];
  const carried = day?.points.filter((p) => p.carried) || [];
  const index = profile && day ? profile.days.indexOf(day) : -1;
  const changeProfile = (p: ProfileEntry) =>
    navigate(
      p.id,
      profile?.days.some((d) => d.date === requestedDate)
        ? requestedDate!
        : undefined,
    );
  function renderMetric(p: Point) {
    return profile?.kind === "us"
      ? p.turnover === null
        ? "—"
        : `$${fmt(p.turnover / 1e6, 1)}M`
      : p.volatility === null
        ? "—"
        : `${fmt(p.volatility * 100)}%`;
  }
  return (
    <section className="mm-page" aria-labelledby="momentum-title">
      <header className="mm-header">
        <div>
          <div className="eyebrow">MARKET ROTATION / MOMENTUM</div>
          <h1 id="momentum-title">
            모멘텀 맵<span className="mm-beta">리서치</span>
          </h1>
          <p>강도와 가속도로 읽는 자산의 현재 위치</p>
        </div>
        <div className="mm-published">
          <span className="mm-live-dot" />
          검증된 역사 데이터
          <span>
            데이터 생성{" "}
            {manifest?.exported_at
              ? new Date(manifest.exported_at).toLocaleDateString("ko-KR", {
                  timeZone: "Asia/Seoul",
                })
              : "확인 중"}
          </span>
        </div>
      </header>
      <div className="mm-controls">
        <div className="mm-tabs" role="group" aria-label="맵 종류">
          <button
            type="button"
            aria-pressed={entry?.kind === "global"}
            onClick={() => {
              const e = manifest?.profiles.find(
                (p) => p.id === "global_binance",
              );
              if (e) changeProfile(e);
            }}
          >
            <Globe2 size={16} aria-hidden="true" />
            글로벌 자산군
          </button>
          <button
            type="button"
            aria-pressed={entry?.kind === "us"}
            onClick={() => {
              const e = manifest?.profiles.find((p) => p.id === "us_etf");
              if (e) changeProfile(e);
            }}
          >
            미국 ETF
          </button>
        </div>
        {entry?.kind === "global" && (
          <label className="mm-field">
            암호자산 기준
            <select
              value={entry.id}
              onChange={(e) => {
                const next = manifest?.profiles.find(
                  (p) => p.id === e.target.value,
                );
                if (next) changeProfile(next);
              }}
              aria-label="암호자산 기준"
            >
              <option value="global_binance">Binance · USDT</option>
              <option value="global_coinbase">Coinbase · USD</option>
            </select>
          </label>
        )}
        <div className="mm-date-control">
          <label className="mm-field">
            관측일
            <select
              aria-label="관측일"
              disabled={!profile}
              value={day?.date || ""}
              onChange={(e) => navigate(entry!.id, e.target.value)}
            >
              {profile ? (
                [...profile.days].reverse().map((d) => (
                  <option key={d.date} value={d.date}>
                    {d.date}
                    {d.score_status !== "complete_candidate"
                      ? " · 순위 보류"
                      : ""}
                  </option>
                ))
              ) : (
                <option>불러오는 중</option>
              )}
            </select>
          </label>
          <button
            className="mm-icon-button"
            type="button"
            aria-label="이전 관측일"
            disabled={index <= 0}
            onClick={() => navigate(entry!.id, profile!.days[index - 1].date)}
          >
            <ChevronLeft size={18} />
          </button>
          <button
            className="mm-icon-button"
            type="button"
            aria-label="다음 관측일"
            disabled={!profile || index >= profile.days.length - 1}
            onClick={() => navigate(entry!.id, profile!.days[index + 1].date)}
          >
            <ChevronRight size={18} />
          </button>
        </div>
      </div>
      {error ? (
        <div className="mm-state" role="alert">
          <h2>데이터를 불러오지 못했습니다</h2>
          <p>{error}</p>
          <button type="button" onClick={() => setRetry((n) => n + 1)}>
            <RefreshCw size={16} aria-hidden="true" />
            다시 시도
          </button>
        </div>
      ) : !profile || !day ? (
        <div className="mm-state" role="status">
          <RefreshCw size={22} aria-hidden="true" />
          <p>모멘텀 이력을 불러오는 중입니다.</p>
        </div>
      ) : (
        <>
          <div className="mm-context" aria-live="polite">
            <span>
              <strong>{day.date}</strong> 관측 · 좌표 {valid.length}/
              {profile.assets.length}개 · 전체 순위 최신{" "}
              <strong>{entry?.latest_ranked_date || "없음"}</strong>
              {valid.some((p) => p.quadrant === "axis") &&
                ` · 중립축 ${valid.filter((p) => p.quadrant === "axis").length}개`}
            </span>
            <button
              type="button"
              onClick={() => navigate(entry!.id, entry!.latest_date)}
            >
              최신 관측일 {entry?.latest_date}
              <ChevronRight size={14} />
            </button>
          </div>
          {requestedDate && requestedDate !== day.date && (
            <p className="mm-notice" role="status">
              요청한 날짜의 자료가 없어 {day.date}를 표시합니다.
            </p>
          )}
          {profile.kind === "global" && (
            <p className="mm-source-note">
              <Info size={15} aria-hidden="true" />
              {profile.id === "global_binance"
                ? "BTC·ETH는 Binance USDT 기준입니다. USD로 환산하지 않았습니다."
                : "BTC·ETH는 Coinbase USD 기준입니다. 거래 중단 시점의 결측을 그대로 보존합니다."}{" "}
              원화는 값이 높을수록 강세 방향입니다.
            </p>
          )}
          {carried.length > 0 && (
            <p className="mm-source-note" role="status">
              <Info size={15} aria-hidden="true" />
              연준 최신 관측값 사용 · {carried.map((p) =>
                `${assets[p.key].label} ${p.source_date} (${p.source_age_days}일 전)`
              ).join(" · ")}. 새 공표 전까지 해당 모멘텀을 유지하고 순위는 선택일 기준으로 다시 계산합니다.
            </p>
          )}
          {withheld.length > 0 && (
            <div className="mm-notice">
              <strong>전체 순위 보류</strong>
              <span>
                {withheld
                  .map((p) => `${assets[p.key].ticker}: ${status(p.status)}`)
                  .join(" · ")}
                . 유효 좌표만 표시합니다. 비공표일의 연준 자료 외에 수집 결측은 이전 값으로 채우지 않습니다.
              </span>
            </div>
          )}
          <div className="mm-quadrant-strip">
            {quadrants.map(({ key, label, Icon, description }) => (
              <div key={key} className={`mm-quadrant-stat ${key}`}>
                <Icon size={19} aria-hidden="true" />
                <div>
                  <span>{label}</span>
                  <small>{description}</small>
                </div>
                <strong>
                  {valid.filter((p) => p.quadrant === key).length}
                  <small>개</small>
                </strong>
              </div>
            ))}
          </div>
          <div className="mm-workspace">
            <section
              className="mm-panel mm-chart-panel"
              aria-labelledby="map-heading"
            >
              <div className="mm-panel-heading">
                <div>
                  <span className="section-kicker">
                    {profile.kind === "us"
                      ? "RELATIVE STRENGTH"
                      : "ABSOLUTE TREND"}
                  </span>
                  <h2 id="map-heading">
                    {profile.kind === "us"
                      ? "미국 ETF 상대 모멘텀"
                      : "글로벌 자산 모멘텀"}
                  </h2>
                </div>
                <label className="mm-check">
                  <input
                    type="checkbox"
                    checked={labels}
                    onChange={(e) => setLabels(e.target.checked)}
                  />
                  자산명
                </label>
              </div>
              <div
                className="mm-envelope-controls"
                role="group"
                aria-label="역사적 경계 표시"
              >
                <span>역사적 경계</span>
                {[0.8, 0.95, 0.99].map((n, i) => (
                  <button
                    type="button"
                    key={n}
                    className={`level-${i}`}
                    aria-pressed={levels.includes(n)}
                    disabled={!day.envelopes.length}
                    onClick={() =>
                      setLevels((v) =>
                        v.includes(n) ? v.filter((x) => x !== n) : [...v, n],
                      )
                    }
                  >
                    {levels.includes(n) && (
                      <Check size={12} aria-hidden="true" />
                    )}
                    {n * 100}%
                  </button>
                ))}
                <small>
                  {day.envelope_status === "complete_candidate"
                    ? `${day.history.sessions}일 · ${day.history.samples.toLocaleString()}개 표본`
                    : status(day.envelope_status)}
                </small>
              </div>
              <MomentumMap
                profile={profile}
                day={day}
                selected={selected}
                onSelect={setSelected}
                levels={levels}
                labels={labels}
                query={query}
              />
              <div className="mm-detail" aria-live="polite">
                {chosen && chosenAsset ? (
                  <>
                    <div className="mm-detail-name">
                      <span
                        className="mm-dot"
                        style={{
                          background: pointColor(
                            chosen,
                            chosenAsset,
                            profile.kind,
                          ),
                        }}
                      />
                      <strong>{chosenAsset.ticker}</strong>
                      <span>{chosenAsset.label}</span>
                      <button type="button" onClick={() => setSelected(null)}>
                        선택 해제
                      </button>
                    </div>
                    <div className="mm-detail-values">
                      <span>
                        X <strong>{signed(chosen.x)}</strong>
                      </span>
                      <span>
                        Y <strong>{signed(chosen.y)}</strong>
                      </span>
                      <span>
                        점수 <strong>{signed(chosen.score)}</strong>
                      </span>
                      <span>
                        {chosen.quadrant
                          ? quadrantLabels[chosen.quadrant]
                          : status(chosen.status)}
                      </span>
                    </div>
                    <p>
                      {profile.kind === "us"
                        ? liquidityLabel(chosen)
                        : groupLabels[chosenAsset.group]}{" "}
                      ·{" "}
                      {profile.kind === "us" ? "평균 거래대금" : "연율 변동성"}{" "}
                      {renderMetric(chosen)} ·{" "}
                      {profile.kind === "global" && chosen.source_date && (
                        <span>원천 관측일 {chosen.source_date}{chosen.carried ? ` (${chosen.source_age_days}일 전 · 최신값 유지)` : ""} · </span>
                      )}
                      <a
                        href={chosenAsset.source.url}
                        target="_blank"
                        rel="noreferrer"
                      >
                        {chosenAsset.source.name}
                        <ExternalLink size={12} aria-hidden="true" />
                      </a>
                    </p>
                  </>
                ) : (
                  <>
                    <Info size={18} aria-hidden="true" />
                    <span>
                      맵의 점이나 오른쪽 자산을 선택하면 상세 수치를 확인할 수
                      있습니다.
                    </span>
                  </>
                )}
              </div>
            </section>
            <aside
              className="mm-panel mm-ranking"
              aria-labelledby="rank-heading"
            >
              <div className="mm-panel-heading">
                <div>
                  <span className="section-kicker">OBSERVATION RANK</span>
                  <h2 id="rank-heading">모멘텀 순위</h2>
                </div>
                <span className="mm-count">
                  {profile.kind === "us" ? 26 : 13}개
                </span>
              </div>
              <label className="mm-search">
                <Search size={16} aria-hidden="true" />
                <input
                  type="search"
                  placeholder="자산명 또는 티커 검색"
                  aria-label="자산 검색"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                />
              </label>
              <p className="mm-ranking-caption">
                관측 점수 순위 · 매매 자격과 별도
              </p>
              {day.score_status !== "complete_candidate" ? (
                <div className="mm-empty">
                  <Info size={23} aria-hidden="true" />
                  <strong>{status(day.score_status)}</strong>
                  <p>모집단의 유효한 좌표가 모두 있어야 순위를 계산합니다.</p>
                  {entry?.latest_ranked_date && (
                    <button
                      type="button"
                      onClick={() =>
                        navigate(entry.id, entry.latest_ranked_date!)
                      }
                    >
                      전체 순위 최신일 보기
                    </button>
                  )}
                </div>
              ) : ranked.length === 0 ? (
                <p className="mm-empty">검색 결과가 없습니다.</p>
              ) : (
                <ol className="mm-rank-list">
                  {ranked.map((p) => {
                    const a = assets[p.key];
                    return (
                      <li key={p.key}>
                        <button
                          type="button"
                          onClick={() => setSelected(p.key)}
                          aria-pressed={selected === p.key}
                        >
                          <span className="mm-rank-num">{p.rank}</span>
                          <span
                            className="mm-dot"
                            style={{
                              background: pointColor(p, a, profile.kind),
                            }}
                          />
                          <span className="mm-rank-asset">
                            <strong>{a.ticker}</strong>
                            <small>{a.label}{p.carried ? ` · ${p.source_date} 기준` : ""}</small>
                          </span>
                          <span
                            className={`mm-rank-score ${p.score! >= 0 ? "positive" : "negative"}`}
                          >
                            {signed(p.score)}
                          </span>
                        </button>
                      </li>
                    );
                  })}
                </ol>
              )}
              <div className="mm-rank-footer">
                X 70% + Y 30%
                <br />
                <span>중앙값·MAD 표준화 후 ±3 제한</span>
              </div>
            </aside>
          </div>
          <details className="mm-panel mm-table-panel">
            <summary>
              전체 자산 수치{" "}
              <span>{filtered.length}개 · 좌표·순위·자료 상태 확인</span>
            </summary>
            <div
              className="mm-table-scroll"
              tabIndex={0}
              role="region"
              aria-label="전체 자산 수치 표, 좁은 화면에서는 좌우 스크롤"
            >
              <table>
                <thead>
                  <tr>
                    <th scope="col">자산</th>
                    <th scope="col">순위</th>
                    <th scope="col">X{profile.kind === "us" ? " (%p)" : ""}</th>
                    <th scope="col">
                      Y{profile.kind === "us" ? " (bps/거래일)" : ""}
                    </th>
                    <th scope="col">점수</th>
                    <th scope="col">
                      {profile.kind === "us" ? "평균 거래대금" : "연율 변동성"}
                    </th>
                    <th scope="col">자료 상태</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((p) => (
                    <tr key={p.key}>
                      <th scope="row">
                        <button
                          type="button"
                          onClick={() => setSelected(p.key)}
                        >
                          {assets[p.key].ticker}
                          <small>{assets[p.key].label}</small>
                        </button>
                      </th>
                      <td>{p.rank ?? "—"}</td>
                      <td>{signed(p.x)}</td>
                      <td>{signed(p.y)}</td>
                      <td>{signed(p.score)}</td>
                      <td>{renderMetric(p)}</td>
                      <td>
                        {status(p.status)}
                        {profile.kind === "us" && (
                          <small>{liquidityLabel(p)}</small>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
          <details className="mm-panel mm-method">
            <summary>
              맵 읽는 법과 데이터 출처 <Info size={15} aria-hidden="true" />
            </summary>
            <div className="mm-method-grid">
              <section>
                <h3>좌표와 색상</h3>
                {profile.kind === "us" ? (
                  <p>
                    X는 20거래일 총수익률의 SPY 대비 차이(%p), Y는 그 수익률의
                    5거래일간 변화율에서 11개 섹터 중앙값을 뺀
                    값(bps/거래일)입니다. 색상은 복합 점수, 원 면적은 평균
                    거래대금입니다. 유동성 기준은 $10M이며 미확인과 미달은
                    상세에서 구분합니다. SPY와 참고 자산은 순위에서 제외합니다.
                  </p>
                ) : (
                  <p>
                    최근 20개 로그가격의 OLS 기울기와 5개 관측일 전 기울기 대비
                    가속도를 20개 로그수익률 변동성으로 나눕니다. X·Y는 무차원
                    값이며 실제 Sharpe ratio 자체는 아닙니다. 색상은 자산군, 원
                    면적은 연율 변동성입니다. 자산별 관측일은 다르며 연율화
                    계수는 252로 고정합니다.
                  </p>
                )}
              </section>
              <section>
                <h3>역사적 경계</h3>
                <p>
                  기준일을 제외한 직전 252개{" "}
                  {profile.kind === "us"
                    ? "미국 거래일"
                    : "미국·한국·H.10 공통 관측일"}
                  의 모든 자산 좌표로 계산한 결합 사각형입니다.{" "}
                  {day.history.start && day.history.end
                    ? `선택일의 역사 구간은 ${day.history.start}~${day.history.end}입니다.`
                    : ""}{" "}
                  80/95/99%는 과거 포함률이며 미래 확률이 아닙니다. 결측일을
                  건너뛰지 않습니다.
                </p>
              </section>
              <section>
                <h3>출처와 기준</h3>
                <ul>
                  {Array.from(
                    new Map(
                      profile.assets.map((a) => [a.source.name, a.source]),
                    ).values(),
                  ).map((s) => (
                    <li key={s.name}>
                      <a href={s.url} target="_blank" rel="noreferrer">
                        {s.name}
                        <ExternalLink size={12} aria-hidden="true" />
                      </a>
                    </li>
                  ))}
                </ul>
                <p>
                  현재 확보한 수정본과 고정 모집단을 사용합니다. 과거 당시
                  공개된 정보만으로 수행한 백테스트가 아닙니다. 연준은 주간
                  공표로 최신 관측일에 시차가 있습니다. 새 공표 전에는 최근 실제 관측값 25개로 계산한 연준 모멘텀을 유지하고, 다른 자산의 선택일 좌표와 함께 순위를 다시 계산합니다. 비공표일의 가격을 복제하지 않습니다.
                </p>
              </section>
            </div>
          </details>
          <footer className="mm-footer">
            리서치용 후보 지표 · 관측 순위는 매수·매도 신호가 아닙니다.{" "}
            <span>
              수집·산출 결과를 정적 스냅샷으로 제공하며 실시간 시세가 아닙니다.
            </span>
          </footer>
        </>
      )}
    </section>
  );
}
