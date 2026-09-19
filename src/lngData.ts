export type SpreadKey = "ttf_spread" | "jkm_spread";
export type LngRow = {
  date: string;
  hh: number | null;
  ttf_eur: number | null;
  eurusd: number | null;
  ttf_usd: number | null;
  jkm: number | null;
  ttf_spread: number | null;
  jkm_spread: number | null;
};
type Change = { date: string | null; value: number | null };
export type LngSnapshot = {
  schema_version: number;
  generated_at: string;
  as_of: string;
  common_observations: number;
  latest: LngRow;
  changes: Record<SpreadKey, Record<"day" | "week" | "month", Change>>;
  sources: Record<string, { name: string; symbol: string; unit: string; url: string; latest_date: string }>;
  rows: LngRow[];
};

export function parseLngSnapshot(input: unknown): LngSnapshot {
  const data = input as LngSnapshot;
  const numericKeys = ["hh", "ttf_eur", "eurusd", "ttf_usd", "jkm", "ttf_spread", "jkm_spread"] as const;
  if (data?.schema_version !== 1 || !Array.isArray(data.rows) || data.rows.length === 0 ||
      !Number.isFinite(Date.parse(data.generated_at)) || !/^\d{4}-\d{2}-\d{2}$/.test(data.as_of)) {
    throw new Error("LNG 데이터 형식을 확인할 수 없습니다.");
  }
  if (data.rows.some((row, i) => !/^\d{4}-\d{2}-\d{2}$/.test(row.date) ||
      (i > 0 && row.date <= data.rows[i - 1].date) ||
      numericKeys.some(key => row[key] !== null && !Number.isFinite(row[key])))) {
    throw new Error("LNG 시계열에 올바르지 않은 값이 있습니다.");
  }
  const latest = data.rows.find(row => row.date === data.as_of);
  if (!latest || !data.latest || numericKeys.some(key => latest[key] === null || latest[key] !== data.latest[key])) {
    throw new Error("LNG 기준일과 요약 가격이 일치하지 않습니다.");
  }
  for (const key of ["ttf_spread", "jkm_spread"] as const) {
    for (const period of ["day", "week", "month"] as const) {
      const change = data.changes?.[key]?.[period];
      if (!change || (change.value !== null && !Number.isFinite(change.value))) {
        throw new Error("LNG 변화량을 확인할 수 없습니다.");
      }
    }
  }
  for (const key of ["hh", "ttf", "jkm", "eurusd"]) {
    if (!data.sources?.[key]?.symbol) throw new Error("LNG 출처 정보가 없습니다.");
  }
  return data;
}

export function money(value: number | null, signed = false): string {
  if (value === null) return "—";
  return `${value < 0 ? "−" : signed && value > 0 ? "+" : ""}$${Math.abs(value).toFixed(2)}`;
}

export function rangeRows(data: LngSnapshot, months: number): LngRow[] {
  const end = new Date(`${data.as_of}T00:00:00Z`);
  const start = new Date(Date.UTC(end.getUTCFullYear(), end.getUTCMonth() - months, 1));
  const lastDay = new Date(Date.UTC(start.getUTCFullYear(), start.getUTCMonth() + 1, 0)).getUTCDate();
  start.setUTCDate(Math.min(end.getUTCDate(), lastDay));
  return data.rows.filter(row => row.date >= start.toISOString().slice(0, 10) && row.date <= data.as_of);
}
