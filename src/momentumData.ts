export type Asset = {
  key: string;
  ticker: string;
  label: string;
  group: string;
  role: string;
  basis: string;
  currency: string | null;
  source: { name: string; url: string };
};
export type Point = {
  key: string;
  x: number | null;
  y: number | null;
  score: number | null;
  rank: number | null;
  status: string;
  quadrant: string | null;
  liquidity_status: string | null;
  turnover: number | null;
  above_threshold: boolean | null;
  volatility: number | null;
};
export type Envelope = {
  coverage: number;
  x: number;
  y: number;
  samples: number;
  empirical: number;
};
export type Day = {
  date: string;
  score_status: string;
  envelope_status: string;
  history: {
    start: string | null;
    end: string | null;
    sessions: number;
    samples: number;
    expected_samples: number;
    run_id: string | null;
  };
  points: Point[];
  envelopes: Envelope[];
};
export type Profile = {
  schema_version: number;
  id: string;
  label: string;
  kind: "us" | "global";
  description: string;
  run_id: string;
  method_version: string;
  assets: Asset[];
  days: Day[];
};
export type ProfileEntry = {
  id: string;
  label: string;
  kind: "us" | "global";
  description: string;
  file: string;
  sha256: string;
  dates: number;
  latest_date: string;
  latest_ranked_date: string | null;
  default_date: string;
};
export type Manifest = {
  schema_version: number;
  exported_at: string;
  candidate_only: boolean;
  profiles: ProfileEntry[];
};
export const statusLabel: Record<string, string> = {
  complete_candidate: "산출 완료",
  incomplete_population: "전체 순위 보류",
  zero_mad: "점수 분산 부족",
  incomplete_window: "계산 기간 자료 부족",
  missing_source: "원천 자료 없음",
  not_observed_today: "휴장·비관측일",
  zero_volatility: "변동성 부족",
  calendar_unreviewed: "공표·관측일 확인 대기",
  insufficient_history: "252일 이력 부족",
  incomplete_history: "과거 좌표 결측",
  not_built: "경계 미산출",
  zero_scale: "경계 척도 부족",
  partial: "좌표 일부 부족",
  unavailable: "자료 없음",
  incomplete: "완결성 미확인",
  not_implemented: "미산출",
};
export const groupLabels: Record<string, string> = {
  us_equity: "미국 주식",
  kr_equity: "한국 주식",
  commodity: "원자재",
  crypto: "암호자산",
  currency: "통화",
  bond: "채권",
  context: "참고 자산",
};
export const groupColors: Record<string, string> = {
  us_equity: "#76acff",
  kr_equity: "#ff8787",
  commodity: "#edbc62",
  crypto: "#b89aff",
  currency: "#6dd1b4",
  bond: "#b5beca",
  context: "#b5beca",
};
export const quadrantLabels: Record<string, string> = {
  leading: "리드",
  improving: "턴어라운드",
  weakening: "둔화",
  lagging: "부진",
  axis: "중립축",
};
export function fmt(n: number | null, digits = 2) {
  return n === null
    ? "—"
    : n.toLocaleString("ko-KR", {
        minimumFractionDigits: digits,
        maximumFractionDigits: digits,
      });
}
export function signed(n: number | null) {
  return n === null ? "—" : `${n > 0 ? "+" : ""}${fmt(n)}`;
}
export function liquidityLabel(p: Point) {
  return p.liquidity_status !== "complete_candidate"
    ? "유동성 미확인"
    : p.above_threshold
      ? "유동성 기준 충족"
      : "유동성 기준 미달";
}
export function pointColor(p: Point, a: Asset, kind: string) {
  if (kind === "global") return groupColors[a.group] || "#b5beca";
  if (p.score === null) return "#c2c9d1";
  // Fixed score scale across dates, with a visible neutral center.
  const t = Math.min(1, Math.abs(p.score) / 3);
  const end = p.score >= 0 ? [251, 105, 111] : [100, 144, 245];
  const rgb = end.map((v, i) =>
    Math.round([198, 204, 213][i] * (1 - t) + v * t),
  );
  return `rgb(${rgb.join(",")})`;
}
export async function fetchManifest(signal: AbortSignal): Promise<Manifest> {
  const r = await fetch(`${import.meta.env.BASE_URL}momentum/manifest.json`, {
    signal,
    cache: "no-cache",
  });
  if (!r.ok) throw new Error("모멘텀 데이터 목록을 불러오지 못했습니다.");
  const m = await r.json();
  if (
    m.schema_version !== 1 ||
    !Array.isArray(m.profiles) ||
    m.profiles.length !== 3
  )
    throw new Error("지원하지 않는 데이터 목록입니다.");
  return m;
}
const cache = new Map<string, Profile>();
export async function fetchProfile(
  entry: ProfileEntry,
  signal: AbortSignal,
): Promise<Profile> {
  if (!/^[a-z_]+-[a-f0-9]{12}\.json$/.test(entry.file))
    throw new Error("잘못된 데이터 경로입니다.");
  if (cache.has(entry.file)) return cache.get(entry.file)!;
  const r = await fetch(`${import.meta.env.BASE_URL}momentum/${entry.file}`, {
    signal,
  });
  if (!r.ok) throw new Error("모멘텀 이력을 불러오지 못했습니다.");
  const body = await r.arrayBuffer();
  const hash = Array.from(
    new Uint8Array(await crypto.subtle.digest("SHA-256", body)),
  )
    .map((n) => n.toString(16).padStart(2, "0"))
    .join("");
  if (hash !== entry.sha256)
    throw new Error("데이터 버전이 일치하지 않습니다. 새로고침해 주세요.");
  const data: Profile = JSON.parse(new TextDecoder().decode(body));
  if (
    data.schema_version !== 1 ||
    data.id !== entry.id ||
    data.kind !== entry.kind ||
    !data.days.length ||
    data.assets.length !== (data.kind === "us" ? 31 : 13)
  )
    throw new Error("모멘텀 데이터 구성이 올바르지 않습니다.");
  cache.set(entry.file, data);
  return data;
}
