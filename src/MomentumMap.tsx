import { useEffect, useRef, useState } from "react";
import {
  groupColors,
  groupLabels,
  pointColor,
  signed,
  type Profile,
  type Point,
  type Day,
} from "./momentumData";

type Props = {
  profile: Profile;
  day: Day;
  selected: string | null;
  onSelect: (key: string) => void;
  levels: number[];
  labels: boolean;
  query: string;
};
export default function MomentumMap({
  profile,
  day,
  selected,
  onSelect,
  levels,
  labels,
  query,
}: Props) {
  const root = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(900);
  useEffect(() => {
    const observer = new ResizeObserver(([e]) =>
      setWidth(Math.max(280, e.contentRect.width)),
    );
    if (root.current) observer.observe(root.current);
    return () => observer.disconnect();
  }, []);
  const compact = width < 560;
  const height = compact ? 470 : 580;
  const pad = { left: compact ? 49 : 62, right: 24, top: 40, bottom: 60 };
  const w = width - pad.left - pad.right,
    h = height - pad.top - pad.bottom;
  const assets = Object.fromEntries(profile.assets.map((a) => [a.key, a]));
  const points = day.points.filter((p) => p.x !== null && p.y !== null);
  const envelopes = day.envelopes.filter((e) => levels.includes(e.coverage));
  const boundX =
    Math.max(
      1,
      ...points.map((p) => Math.abs(p.x!)),
      ...day.envelopes.map((e) => e.x),
    ) * 1.2;
  const boundY =
    Math.max(
      1,
      ...points.map((p) => Math.abs(p.y!)),
      ...day.envelopes.map((e) => e.y),
    ) * 1.2;
  const x = (v: number) => pad.left + (w * (v / boundX + 1)) / 2;
  const y = (v: number) => pad.top + (h * (1 - v / boundY)) / 2;
  const metric = (p: Point) =>
    profile.kind === "us" ? p.turnover : p.volatility;
  const maxSize = Math.max(0.00001, ...points.map((p) => metric(p) || 0));
  const radius = (p: Point) =>
    Math.max(5, (compact ? 19 : 26) * Math.sqrt((metric(p) || 0) / maxSize));
  const shown = points.filter(
    (p) =>
      !query ||
      `${assets[p.key].label} ${assets[p.key].ticker}`
        .toLowerCase()
        .includes(query.toLowerCase()),
  );
  const matches = new Set(shown.map((p) => p.key));
  // Place short labels without overlapping already placed labels or plot edges.
  const placed: { left: number; top: number; right: number; bottom: number }[] =
    [];
  const labelPositions = new Map<string, { left: number; top: number }>();
  const order = [...shown].sort((a, b) =>
    a.key === selected
      ? -1
      : b.key === selected
        ? 1
        : (a.rank ?? 100) - (b.rank ?? 100),
  );
  for (const p of order) {
    if (!labels && p.key !== selected) continue;
    if (compact && p.key !== selected && (p.rank === null || p.rank > 5))
      continue;
    const labelWidth = assets[p.key].ticker.length * 7 + 6;
    const r = radius(p) + 6;
    for (const [dx, dy] of [
      [r, -7],
      [r, 14],
      [-labelWidth - r, -7],
      [-labelWidth - r, 14],
      [-labelWidth / 2, -r - 10],
      [-labelWidth / 2, r + 16],
    ]) {
      const left = x(p.x!) + dx,
        top = y(p.y!) + dy;
      const box = {
        left,
        top: top - 12,
        right: left + labelWidth,
        bottom: top + 3,
      };
      if (
        box.left < pad.left ||
        box.right > width - pad.right ||
        box.top < pad.top ||
        box.bottom > height - pad.bottom
      )
        continue;
      if (
        placed.some(
          (b) =>
            box.left < b.right + 3 &&
            box.right > b.left - 3 &&
            box.top < b.bottom + 3 &&
            box.bottom > b.top - 3,
        )
      )
        continue;
      if (
        points.some((other) => {
          if (other.key === p.key) return false;
          const cx = x(other.x!),
            cy = y(other.y!);
          const dx = Math.max(box.left, Math.min(cx, box.right)) - cx;
          const dy = Math.max(box.top, Math.min(cy, box.bottom)) - cy;
          return Math.hypot(dx, dy) < radius(other) + 2;
        })
      )
        continue;
      placed.push(box);
      labelPositions.set(p.key, { left, top });
      break;
    }
  }
  const ticks = [-1, -0.5, 0, 0.5, 1];
  const boundaryColors: Record<string, string> = {
    "0.8": "#59b99b",
    "0.95": "#e5b358",
    "0.99": "#cb8292",
  };
  const number = (v: number) =>
    Math.abs(v) >= 100 ? v.toFixed(0) : v.toFixed(1);
  return (
    <div className="mm-plot" ref={root}>
      <svg
        width="100%"
        height={height}
        viewBox={`0 0 ${width} ${height}`}
        role="group"
        aria-label={`${day.date} ${profile.label} 모멘텀 산점도. 점을 선택하면 상세 수치를 표시합니다.`}
      >
        <title>
          {day.date} {profile.label} 모멘텀 맵
        </title>
        <desc>
          오른쪽은 추세 또는 상대강도가 높고, 위쪽은 가속도가 높습니다. 모든
          수치는 아래 자산 표에서도 확인할 수 있습니다.
        </desc>
        <rect
          x={pad.left}
          y={pad.top}
          width={w / 2}
          height={h / 2}
          fill="#163a39"
          opacity=".19"
        />
        <rect
          x={x(0)}
          y={pad.top}
          width={w / 2}
          height={h / 2}
          fill="#42351b"
          opacity=".15"
        />
        <rect
          x={pad.left}
          y={y(0)}
          width={w / 2}
          height={h / 2}
          fill="#202d49"
          opacity=".16"
        />
        <rect
          x={x(0)}
          y={y(0)}
          width={w / 2}
          height={h / 2}
          fill="#3c2836"
          opacity=".15"
        />
        {ticks.map((t) => (
          <g key={t} className="mm-grid">
            <line
              x1={x(t * boundX)}
              x2={x(t * boundX)}
              y1={pad.top}
              y2={height - pad.bottom}
            />
            <line
              x1={pad.left}
              x2={width - pad.right}
              y1={y(t * boundY)}
              y2={y(t * boundY)}
            />
            <text
              x={x(t * boundX)}
              y={height - pad.bottom + 22}
              textAnchor="middle"
            >
              {number(t * boundX)}
            </text>
            <text x={pad.left - 10} y={y(t * boundY) + 4} textAnchor="end">
              {number(t * boundY)}
            </text>
          </g>
        ))}
        {envelopes.map((e) => (
          <rect
            key={e.coverage}
            className="mm-envelope"
            x={x(-e.x)}
            y={y(e.y)}
            width={x(e.x) - x(-e.x)}
            height={y(-e.y) - y(e.y)}
            stroke={boundaryColors[e.coverage]}
            strokeDasharray={
              e.coverage === 0.8
                ? undefined
                : e.coverage === 0.95
                  ? "7 5"
                  : "2 5"
            }
          />
        ))}
        <path
          d={`M ${x(0)} ${pad.top} V ${height - pad.bottom} M ${pad.left} ${y(0)} H ${width - pad.right}`}
          className="mm-origin"
        />
        <g className="mm-quadrant">
          <text x={pad.left + 12} y={pad.top + 20} fill="#81baa9">
            턴어라운드
          </text>
          <text
            x={width - pad.right - 12}
            y={pad.top + 20}
            textAnchor="end"
            fill="#d8ba7e"
          >
            리드
          </text>
          <text x={pad.left + 12} y={height - pad.bottom - 12} fill="#90a8ca">
            부진
          </text>
          <text
            x={width - pad.right - 12}
            y={height - pad.bottom - 12}
            textAnchor="end"
            fill="#c79eb4"
          >
            둔화
          </text>
        </g>
        {[...points]
          .sort((a, b) =>
            a.key === selected
              ? 1
              : b.key === selected
                ? -1
                : radius(b) - radius(a),
          )
          .map((p) => {
            const a = assets[p.key],
              active = p.key === selected;
            const unknown =
              profile.kind === "us" &&
              p.liquidity_status !== "complete_candidate";
            const failed = profile.kind === "us" && p.above_threshold === false;
            return (
              <g
                key={p.key}
                role="button"
                tabIndex={0}
                className={`mm-point ${active ? "selected" : ""}`}
                aria-pressed={active}
                aria-label={`${a.label}, ${a.ticker}, X ${signed(p.x)}, Y ${signed(p.y)}, ${p.rank ? `${p.rank}위` : "순위 없음"}`}
                onClick={() => onSelect(p.key)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    onSelect(p.key);
                  }
                }}
                opacity={matches.has(p.key) ? 1 : 0.15}
              >
                <title>
                  {a.label} · X {signed(p.x)} · Y {signed(p.y)}
                </title>
                <circle
                  className="mm-hit"
                  cx={x(p.x!)}
                  cy={y(p.y!)}
                  r={Math.max(13, radius(p))}
                  fill="transparent"
                />
                <circle
                  cx={x(p.x!)}
                  cy={y(p.y!)}
                  r={radius(p)}
                  fill={
                    unknown || failed
                      ? "#11161e"
                      : pointColor(p, a, profile.kind)
                  }
                  fillOpacity=".9"
                  stroke={active ? "#fff5d5" : pointColor(p, a, profile.kind)}
                  strokeWidth={active || a.role === "benchmark" ? 3 : 1.4}
                  strokeDasharray={unknown ? "3 3" : undefined}
                />
                {(unknown || failed) && (
                  <path
                    d={`M${x(p.x!) - 4} ${y(p.y!) - 4}l8 8m0-8l-8 8`}
                    stroke={pointColor(p, a, profile.kind)}
                    strokeWidth="1.5"
                  />
                )}
                <circle
                  className="mm-focus-ring"
                  cx={x(p.x!)}
                  cy={y(p.y!)}
                  r={radius(p) + 5}
                />
              </g>
            );
          })}
        <g aria-hidden="true">
          {Array.from(labelPositions).map(([key, label]) => (
            <text
              key={key}
              x={label.left}
              y={label.top}
              className="mm-point-label"
              fill={key === selected ? "#fff5d5" : "#cdd6df"}
            >
              {assets[key].ticker}
            </text>
          ))}
        </g>
        <text
          className="mm-axis-title"
          x={pad.left + w / 2}
          y={height - 9}
          textAnchor="middle"
        >
          {profile.kind === "us"
            ? "20일 상대강도 · SPY 대비 (%p)"
            : "20일 추세 / 변동성"}
        </text>
        <text
          className="mm-axis-title"
          transform={`translate(14 ${pad.top + h / 2}) rotate(-90)`}
          textAnchor="middle"
        >
          {profile.kind === "us"
            ? "섹터 대비 가속도 (bps/거래일)"
            : "추세 가속도 / 변동성"}
        </text>
      </svg>
      {profile.kind === "global" ? (
        <div className="mm-color-legend">
          {Object.entries(groupLabels)
            .filter(([key]) => profile.assets.some((a) => a.group === key))
            .map(([key, label]) => (
              <span key={key}>
                <i style={{ background: groupColors[key] }} />
                {label}
              </span>
            ))}
        </div>
      ) : (
        <div className="mm-color-legend">
          <span>점수 −3</span>
          <span className="mm-score-gradient" />
          <span>+3</span>
          <span>테두리 강조: SPY</span>
          <span>×: 유동성 미확인·미달</span>
        </div>
      )}
      <p className="mm-chart-note">
        원 면적:{" "}
        {profile.kind === "us"
          ? "최근 20거래일 평균 거래대금"
          : "20개 관측일 연율 변동성"}{" "}
        · 날짜별 크기 정규화, 최소 표시 크기 적용
        {compact ? " · 작은 화면은 상위 5개·선택 자산 라벨 표시" : ""}
      </p>
    </div>
  );
}
