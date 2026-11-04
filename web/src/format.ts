export function fmtNum(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "–";
  return v.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

/** Energy in joules with a sensible unit: mJ below 1 J, kJ from 1 kJ. */
export function fmtEnergy(j: number | null | undefined): string {
  if (j === null || j === undefined || !Number.isFinite(j)) return "–";
  const a = Math.abs(j);
  if (a >= 1000) return `${fmtNum(j / 1000, a >= 10_000 ? 1 : 2)} kJ`;
  if (a >= 100) return `${fmtNum(j, 0)} J`;
  if (a >= 1) return `${fmtNum(j, 2)} J`;
  return `${fmtNum(j * 1000, a >= 0.01 ? 0 : 1)} mJ`;
}

export function fmtDuration(s: number | null | undefined): string {
  if (s === null || s === undefined || !Number.isFinite(s)) return "–";
  if (s >= 120) return `${Math.floor(s / 60)} min ${Math.round(s % 60)} s`;
  if (s >= 10) return `${fmtNum(s, 1)} s`;
  if (s >= 1) return `${fmtNum(s, 2)} s`;
  return `${fmtNum(s * 1000, 0)} ms`;
}

/** Rough durations ("about 4 min") for estimates. */
export function fmtEstimate(s: number): string {
  if (s >= 5400) return `${fmtNum(s / 3600, 1)} h`;
  if (s >= 90) return `${Math.round(s / 60)} min`;
  return `${Math.max(1, Math.round(s))} s`;
}

/** Fewest decimals that represent every tick exactly. */
function tickDecimals(values: number[]): number {
  for (let d = 0; d <= 3; d++) {
    if (values.every((v) => Math.abs(v - Number(v.toFixed(d))) < 1e-9 * Math.max(1, Math.abs(v)))) return d;
  }
  return 3;
}

/** One unit for a whole axis (never "500 mJ" next to "1.00 J"). */
export function energyAxis(ticks: number[]): (v: number) => string {
  const max = Math.max(...ticks.map(Math.abs));
  const [div, unit] = max >= 1000 ? [1000, "kJ"] : max >= 1 ? [1, "J"] : [0.001, "mJ"];
  const d = tickDecimals(ticks.map((t) => t / div));
  return (v) => `${fmtNum(v / div, d)} ${unit}`;
}

export function durationAxis(ticks: number[]): (v: number) => string {
  const max = Math.max(...ticks.map(Math.abs));
  const [div, unit] = max >= 1 ? [1, "s"] : [0.001, "ms"];
  const d = tickDecimals(ticks.map((t) => t / div));
  return (v) => `${fmtNum(v / div, d)} ${unit}`;
}

export function fmtPct(v: number | null | undefined, signed = true): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "–";
  const digits = Math.abs(v) >= 10 ? 0 : 1;
  const s = v.toFixed(digits);
  return `${signed && v > 0 ? "+" : ""}${s}%`;
}

export function fmtCompact(v: number): string {
  if (!Number.isFinite(v)) return "–";
  const a = Math.abs(v);
  if (a >= 1e6) return `${(v / 1e6).toFixed(1)}M`;
  if (a >= 1e4) return `${(v / 1e3).toFixed(1)}K`;
  return v.toLocaleString("en-US", { maximumFractionDigits: a < 10 ? 2 : 0 });
}

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "–";
  const d = new Date(iso);
  return d.toLocaleString("en-GB", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
}

export function fmtP(p: number | null | undefined): string {
  if (p === null || p === undefined || !Number.isFinite(p)) return "–";
  if (p < 0.001) return "< 0.001";
  return p.toFixed(3);
}

export const STATE_LABELS: Record<string, string> = {
  preparing: "Preparing data",
  "idle-baseline": "Measuring idle power",
  "warm-up": "Warm-up runs",
  running: "Measuring",
  analysing: "Analysing",
  completed: "Completed",
  cancelled: "Cancelled",
  interrupted: "Interrupted",
  unknown: "Unknown",
};

export const ACTIVE = new Set(["preparing", "idle-baseline", "warm-up", "running", "analysing"]);
