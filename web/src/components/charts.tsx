import { useInView } from "motion/react";
import { useEffect, useLayoutEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode, type RefObject } from "react";

/* ------------------------------------------------------------------ scales */

function niceStep(range: number, count: number): number {
  const raw = range / Math.max(1, count);
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const norm = raw / mag;
  return (norm >= 7.5 ? 10 : norm >= 3.5 ? 5 : norm >= 1.5 ? 2 : 1) * mag;
}

export function linearTicks(min: number, max: number, count = 5): number[] {
  if (!(max > min)) max = min + 1;
  const step = niceStep(max - min, count);
  const out: number[] = [];
  for (let v = Math.floor(min / step) * step; v <= max + step * 1e-6; v += step) out.push(Number(v.toPrecision(12)));
  return out;
}

export function logTicks(min: number, max: number): number[] {
  const lo = Math.floor(Math.log10(min));
  const hi = Math.ceil(Math.log10(max));
  const mult = hi - lo <= 2 ? [1, 2, 5] : [1];
  const out: number[] = [];
  for (let e = lo; e <= hi; e++) for (const m of mult) out.push(m * Math.pow(10, e));
  return out.filter((v) => v >= min / 1.0001 && v <= max * 1.0001);
}

interface Scale { (v: number): number; ticks: number[] }

function scale(domain: [number, number], range: [number, number], log = false, tickCount = 5): Scale {
  let [d0, d1] = domain;
  if (log) {
    d0 = Math.max(d0, 1e-9);
    d1 = Math.max(d1, d0 * 1.0001);
    const l0 = Math.log10(d0), l1 = Math.log10(d1);
    const f = ((v: number) => range[0] + ((Math.log10(Math.max(v, 1e-12)) - l0) / (l1 - l0)) * (range[1] - range[0])) as Scale;
    f.ticks = logTicks(d0, d1);
    return f;
  }
  const ticks = linearTicks(d0, d1, tickCount);
  const t0 = Math.min(d0, ticks[0]), t1 = Math.max(d1, ticks[ticks.length - 1]);
  const f = ((v: number) => range[0] + ((v - t0) / (t1 - t0 || 1)) * (range[1] - range[0])) as Scale;
  f.ticks = ticks;
  return f;
}

function padLog(min: number, max: number): [number, number] {
  return [min / 1.6, max * 1.6];
}

/** Axis tick formatting gets the whole tick list, so it can keep one unit across the axis. */
export type AxisFormat = (ticks: number[]) => (v: number) => string;

const ticksFor = (px: number, per = 90) => Math.max(2, Math.min(6, Math.floor(px / per)));

/* ------------------------------------------------------------- utilities */

function useWidth<T extends HTMLElement>(): [RefObject<T | null>, number] {
  const ref = useRef<T | null>(null);
  const [w, setW] = useState(0);
  useLayoutEffect(() => {
    if (!ref.current) return;
    setW(ref.current.getBoundingClientRect().width);
    const ro = new ResizeObserver((e) => setW(e[0].contentRect.width));
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);
  return [ref, w];
}

/** True once the chart has scrolled into view: its marks animate in from then on (see charts.css). */
function useDrawn(ref: RefObject<HTMLElement | null>): string {
  return useInView(ref, { once: true, margin: "0px 0px -40px 0px" }) ? "chart drawn" : "chart";
}

/** Entrance-animation order (--i) and resting opacity (--o) for one mark. */
const anim = (i: number, o = 1) => ({ "--i": i, "--o": o }) as CSSProperties;

interface Tip { x: number; y: number; content: ReactNode }

function Tooltip({ tip, width }: { tip: Tip | null; width: number }) {
  const ref = useRef<HTMLDivElement>(null);
  const [tw, setTw] = useState(220);
  useEffect(() => {
    if (ref.current) setTw(ref.current.offsetWidth);
  }, [tip]);
  if (!tip) return null;
  const left = tip.x + 14 + tw > width ? Math.max(0, tip.x - tw - 14) : tip.x + 14;
  return (
    <div ref={ref} className="chart-tip" style={{ left, top: Math.max(0, tip.y - 12) }}>
      {tip.content}
    </div>
  );
}

export function Legend({ items }: { items: { name: string; color: string; shape?: "dot" | "line" | "square" }[] }) {
  return (
    <div className="legend">
      {items.map((it) => (
        <span key={it.name} className="legend-item">
          {it.shape === "line" ? (
            <svg width="18" height="10"><line x1="1" y1="5" x2="17" y2="5" stroke={it.color} strokeWidth="2" strokeLinecap="round" /><circle cx="9" cy="5" r="3" fill={it.color} /></svg>
          ) : it.shape === "square" ? (
            <svg width="12" height="12"><rect width="12" height="12" rx="3" fill={it.color} /></svg>
          ) : (
            <svg width="10" height="10"><circle cx="5" cy="5" r="5" fill={it.color} /></svg>
          )}
          {it.name}
        </span>
      ))}
    </div>
  );
}

function XAxis({ s, y, x0, x1, fmt, label }: { s: Scale; y: number; x0: number; x1: number; fmt: AxisFormat; label?: string }) {
  const f = fmt(s.ticks);
  return (
    <g className="axis">
      <line x1={x0} x2={x1} y1={y} y2={y} stroke="var(--axis)" />
      {s.ticks.map((t) => (
        <text key={t} x={s(t)} y={y + 18} textAnchor="middle">{f(t)}</text>
      ))}
      {label && <text x={x1} y={y + 38} textAnchor="end" className="axis-title">{label}</text>}
    </g>
  );
}

function YGrid({ s, x0, x1, fmt, label }: { s: Scale; x0: number; x1: number; fmt: AxisFormat; label?: string }) {
  const f = fmt(s.ticks);
  return (
    <g className="axis">
      {s.ticks.map((t) => (
        <g key={t}>
          <line x1={x0} x2={x1} y1={s(t)} y2={s(t)} stroke="var(--grid)" />
          <text x={x0 - 8} y={s(t) + 4} textAnchor="end">{f(t)}</text>
        </g>
      ))}
      {label && <text x={0} y={8} textAnchor="start" className="axis-title">{label}</text>}
    </g>
  );
}

type Box = { x0: number; x1: number; y0: number; y1: number };
type LabelPos = { x: number; y: number; anchor: "start" | "end" | "middle" };

/** Greedy label placement: try right, left, above, below; skip a label rather than overlap. */
function placeLabels(items: { key: string; x: number; y: number; text: string; priority: number }[], bounds: Box, r: number) {
  const hit = (a: Box, b: Box) => a.x0 < b.x1 && b.x0 < a.x1 && a.y0 < b.y1 && b.y0 < a.y1;
  const dots: Box[] = items.map((p) => ({ x0: p.x - r - 2, x1: p.x + r + 2, y0: p.y - r - 2, y1: p.y + r + 2 }));
  const placed: Box[] = [];
  const out = new Map<string, LabelPos>();
  for (const p of [...items].sort((a, b) => b.priority - a.priority)) {
    const w = p.text.length * 6.6 + 4, h = 14;
    const options: [Box, LabelPos][] = [
      [{ x0: p.x + 9, x1: p.x + 9 + w, y0: p.y - 8, y1: p.y + 6 }, { x: p.x + 10, y: p.y + 4, anchor: "start" }],
      [{ x0: p.x - 9 - w, x1: p.x - 9, y0: p.y - 8, y1: p.y + 6 }, { x: p.x - 10, y: p.y + 4, anchor: "end" }],
      [{ x0: p.x - w / 2, x1: p.x + w / 2, y0: p.y - 12 - h, y1: p.y - 12 }, { x: p.x, y: p.y - 15, anchor: "middle" }],
      [{ x0: p.x - w / 2, x1: p.x + w / 2, y0: p.y + 12, y1: p.y + 12 + h }, { x: p.x, y: p.y + 23, anchor: "middle" }],
    ];
    for (const [box, pos] of options) {
      const inside = box.x0 >= bounds.x0 && box.x1 <= bounds.x1 && box.y0 >= bounds.y0 && box.y1 <= bounds.y1;
      if (inside && !placed.some((b) => hit(b, box)) && !dots.some((d) => hit(d, box))) {
        placed.push(box);
        out.set(p.key, pos);
        break;
      }
    }
  }
  return out;
}

/* --------------------------------------------------- distribution dot plot */

export interface DotRow {
  key: string;
  label: string;
  sub?: string;
  values: number[];
  median: number;
  lo: number;
  hi: number;
  baseline?: boolean;
  tooltip?: ReactNode;
}

/** One row per configuration: every repetition as a dot, the median as a ringed marker, its 95 % CI as a band. */
export function DotPlot({ rows, axisFmt, axisLabel, color = "var(--series-1)" }: {
  rows: DotRow[]; axisFmt: AxisFormat; axisLabel: string; color?: string;
}) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [tip, setTip] = useState<Tip | null>(null);
  const rowH = 44;
  const labelW = Math.min(250, Math.max(140, width * 0.34));
  const x0 = labelW + 12, x1 = Math.max(x0 + 60, width - 24);
  const height = rows.length * rowH + 44;
  const all = rows.flatMap((r) => [...r.values, r.lo, r.hi]);
  const s = scale([Math.min(0, ...all), Math.max(...all)], [x0, x1], false, ticksFor(x1 - x0));
  const base = rows.find((r) => r.baseline);
  const cls = useDrawn(ref);
  return (
    <div ref={ref} className={cls} onMouseLeave={() => setTip(null)}>
      {width > 0 && (
        <svg width={width} height={height} role="img" aria-label={`${axisLabel} per configuration`}>
          {s.ticks.map((t) => <line key={t} x1={s(t)} x2={s(t)} y1={4} y2={height - 36} stroke="var(--grid)" />)}
          {base && <line x1={s(base.median)} x2={s(base.median)} y1={4} y2={height - 36} stroke="var(--chart-ref)" strokeDasharray="3 4" />}
          {rows.map((r, i) => {
            const cy = i * rowH + rowH / 2 + 4;
            const c = r.baseline ? "var(--chart-baseline)" : color;
            return (
              <g key={r.key}>
                <text x={0} y={cy - (r.sub ? 2 : -4)} className={`row-label${r.baseline ? " strong" : ""}`}>{r.label}</text>
                {r.sub && <text x={0} y={cy + 14} className="row-sub">{r.sub}</text>}
                <rect x={s(r.lo)} y={cy - 4} width={Math.max(2, s(r.hi) - s(r.lo))} height={8} rx={4} fill={c} className="a-fade" style={anim(i, 0.22)} />
                {r.values.map((v, j) => (
                  <circle key={j} cx={s(v)} cy={cy + (((j * 7919) % 11) - 5) * 1.3} r={3} fill={c} className="a-dot" style={anim(i * 3 + j, 0.55)} />
                ))}
                <circle cx={s(r.median)} cy={cy} r={6} fill={c} stroke="var(--chart-ring)" strokeWidth={2} className="a-dot" style={anim(i * 3 + 8)} />
                <rect x={0} y={cy - rowH / 2} width={width} height={rowH} fill="transparent"
                  onMouseMove={(e) => setTip({ x: e.nativeEvent.offsetX, y: cy, content: r.tooltip ?? <b>{r.label}</b> })} />
              </g>
            );
          })}
          <XAxis s={s} y={height - 36} x0={x0} x1={x1} fmt={axisFmt} label={axisLabel} />
        </svg>
      )}
      <Tooltip tip={tip} width={width} />
    </div>
  );
}

/* ------------------------------------------------------------ line chart */

export interface LineSeries {
  name: string;
  color: string;
  points: { x: number; y: number; lo?: number; hi?: number }[];
}

export function LineChart({ series, xTicks, xFormat, yFormat, yAxisFmt, xLog, yLog, xLabel, yLabel, height = 260 }: {
  series: LineSeries[]; xTicks: number[]; xFormat: (v: number) => string; yFormat: (v: number) => string;
  yAxisFmt: AxisFormat; xLog?: boolean; yLog?: boolean; xLabel: string; yLabel: string; height?: number;
}) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const left = 64, top = 20, bottom = 44;
  const pts = series.flatMap((s) => s.points);
  const ys = pts.flatMap((p) => [p.y, p.lo ?? p.y, p.hi ?? p.y]).filter((v) => !yLog || v > 0);
  const yDom: [number, number] = yLog ? padLog(Math.min(...ys), Math.max(...ys)) : [Math.min(0, ...ys), Math.max(...ys) * 1.08];
  const xDom: [number, number] = [Math.min(...xTicks), Math.max(...xTicks)];
  const sy = scale(yDom, [height - bottom, top], yLog, ticksFor(height - top - bottom, 48));
  // End labels only when they cannot collide; the legend always carries identity.
  const ends = series.map((s) => [...s.points].sort((a, b) => a.x - b.x).pop()).map((p) => (p ? sy(p.y) : 0));
  const endLabels = series.length > 1 && ends.every((y, i) => ends.every((z, j) => i === j || Math.abs(y - z) >= 16));
  const right = endLabels ? 104 : 24;
  const sx = scale(xDom, [left, Math.max(left + 40, width - right)], xLog);
  sx.ticks = xTicks;
  const tipX = hover !== null ? sx(hover) : 0;
  const cls = useDrawn(ref);
  return (
    <div ref={ref} className={cls} onMouseLeave={() => setHover(null)}>
      {series.length > 1 && <Legend items={series.map((s) => ({ name: s.name, color: s.color, shape: "line" }))} />}
      {width > 0 && (
        <svg width={width} height={height} role="img" aria-label={`${yLabel} by ${xLabel}`}
          onMouseMove={(e) => {
            const mx = e.nativeEvent.offsetX;
            setHover(xTicks.reduce((b, t) => (Math.abs(sx(t) - mx) < Math.abs(sx(b) - mx) ? t : b), xTicks[0]));
          }}>
          <YGrid s={sy} x0={left} x1={width - right} fmt={yAxisFmt} label={yLabel} />
          <XAxis s={sx} y={height - bottom} x0={left} x1={width - right} fmt={() => xFormat} label={xLabel} />
          {hover !== null && <line x1={tipX} x2={tipX} y1={top} y2={height - bottom} stroke="var(--chart-ref)" />}
          {series.map((s, si) => {
            const sorted = [...s.points].sort((a, b) => a.x - b.x);
            const d = sorted.map((p, i) => `${i ? "L" : "M"}${sx(p.x)},${sy(p.y)}`).join("");
            const last = sorted[sorted.length - 1];
            return (
              <g key={s.name}>
                {sorted.map((p, pi) => p.lo !== undefined && p.hi !== undefined && (
                  <g key={`ci${p.x}`} stroke={s.color} strokeWidth={1.5} className="a-fade" style={anim(si * 4 + pi, 0.6)}>
                    <line x1={sx(p.x)} x2={sx(p.x)} y1={sy(p.lo)} y2={sy(p.hi)} />
                    <line x1={sx(p.x) - 4} x2={sx(p.x) + 4} y1={sy(p.lo)} y2={sy(p.lo)} />
                    <line x1={sx(p.x) - 4} x2={sx(p.x) + 4} y1={sy(p.hi)} y2={sy(p.hi)} />
                  </g>
                ))}
                <path d={d} pathLength={1} fill="none" stroke={s.color} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" className="a-line" />
                {sorted.map((p, pi) => <circle key={p.x} cx={sx(p.x)} cy={sy(p.y)} r={4.5} fill={s.color} stroke="var(--chart-ring)" strokeWidth={2} className="a-dot" style={anim(si * 4 + pi + 6)} />)}
                {endLabels && last && <text x={sx(last.x) + 10} y={sy(last.y) + 4} className="end-label a-fade" style={anim(20 + si)}>{s.name}</text>}
              </g>
            );
          })}
        </svg>
      )}
      {hover !== null && width > 0 && (
        <Tooltip width={width} tip={{
          x: tipX, y: top + 20,
          content: (
            <>
              <b>{xFormat(hover)}</b>
              {series.map((s) => {
                const p = s.points.find((q) => q.x === hover);
                return p && (
                  <div key={s.name} className="tip-row">
                    <span className="sw" style={{ background: s.color }} />{s.name}: <b>{yFormat(p.y)}</b>
                    {p.lo !== undefined && <span className="muted"> [{yFormat(p.lo)} – {yFormat(p.hi!)}]</span>}
                  </div>
                );
              })}
            </>
          ),
        }} />
      )}
    </div>
  );
}

/* --------------------------------------------------------------- scatter */

export interface ScatterPoint {
  key: string;
  x: number;
  y: number;
  label?: string;
  color: string;
  pareto?: boolean;
  priority?: number;
  tooltip?: ReactNode;
}

export function ScatterPlot({ points, xAxisFmt, yAxisFmt, xLabel, yLabel, height = 300, xLog, yLog, frontier, diagonal, r = 5 }: {
  points: ScatterPoint[]; xAxisFmt: AxisFormat; yAxisFmt: AxisFormat; xLabel: string; yLabel: string;
  height?: number; xLog?: boolean; yLog?: boolean; frontier?: boolean; diagonal?: boolean; r?: number;
}) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [tip, setTip] = useState<Tip | null>(null);
  const left = 64, right = 24, top = 24, bottom = 46;
  const xs = points.map((p) => p.x).filter((v) => !xLog || v > 0);
  const ys = points.map((p) => p.y).filter((v) => !yLog || v > 0);
  const lo = diagonal ? Math.min(...xs, ...ys) : 0;
  const hi = diagonal ? Math.max(...xs, ...ys) : 0;
  const xDom: [number, number] = diagonal ? padLog(lo, hi) : xLog ? padLog(Math.min(...xs), Math.max(...xs)) : [0, Math.max(...xs) * 1.12];
  const yDom: [number, number] = diagonal ? padLog(lo, hi) : yLog ? padLog(Math.min(...ys), Math.max(...ys)) : [0, Math.max(...ys) * 1.12];
  const sx = scale(xDom, [left, Math.max(left + 40, width - right)], xLog, ticksFor(width - left - right));
  const sy = scale(yDom, [height - bottom, top], yLog, ticksFor(height - top - bottom, 48));
  const front = useMemo(() => points.filter((p) => p.pareto).sort((a, b) => a.x - b.x), [points]);
  const labels = width > 0 ? placeLabels(
    points.filter((p) => p.label).map((p) => ({ key: p.key, x: sx(p.x), y: sy(p.y), text: p.label!, priority: p.priority ?? (p.pareto ? 1 : 0) })),
    { x0: left, x1: width - 4, y0: 0, y1: height - bottom - 2 }, r) : new Map<string, LabelPos>();
  const cls = useDrawn(ref);
  return (
    <div ref={ref} className={cls} onMouseLeave={() => setTip(null)}>
      {width > 0 && (
        <svg width={width} height={height} role="img" aria-label={`${yLabel} against ${xLabel}`}>
          <YGrid s={sy} x0={left} x1={width - right} fmt={yAxisFmt} label={yLabel} />
          <XAxis s={sx} y={height - bottom} x0={left} x1={width - right} fmt={xAxisFmt} label={xLabel} />
          {diagonal && <line x1={sx(xDom[0])} y1={sy(yDom[0])} x2={sx(xDom[1])} y2={sy(yDom[1])} stroke="var(--chart-ref)" strokeDasharray="3 4" />}
          {frontier && front.length > 1 && (
            <path d={front.map((p, i) => `${i ? "L" : "M"}${sx(p.x)},${sy(p.y)}`).join("")} pathLength={1} fill="none"
              stroke="var(--frontier)" strokeWidth={2} strokeLinejoin="round" className="a-line" />
          )}
          {points.map((p, i) => {
            const cx = sx(p.x), cy = sy(p.y);
            const lab = labels.get(p.key);
            return (
              <g key={p.key} onMouseMove={() => setTip({ x: cx, y: cy, content: p.tooltip ?? p.label })}>
                <circle cx={cx} cy={cy} r={Math.max(12, r + 6)} fill="transparent" />
                <circle cx={cx} cy={cy} r={r} fill={p.color} stroke="var(--chart-ring)" strokeWidth={2} className="a-dot" style={anim(Math.min(i, 120))} />
                {lab && <text x={lab.x} y={lab.y} textAnchor={lab.anchor} className="point-label a-fade" style={anim(i + 4)}>{p.label}</text>}
              </g>
            );
          })}
        </svg>
      )}
      <Tooltip tip={tip} width={width} />
    </div>
  );
}

/* --------------------------------------------------- stacked phase bars */

export interface StackRow { key: string; label: string; parts: { name: string; value: number }[] }

export function StackedBars({ rows, colors, format, axisFmt, axisLabel }: {
  rows: StackRow[]; colors: Record<string, string>; format: (v: number) => string; axisFmt: AxisFormat; axisLabel: string;
}) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [tip, setTip] = useState<Tip | null>(null);
  const rowH = 36, barH = 18;
  const labelW = Math.min(250, Math.max(140, width * 0.34));
  const x0 = labelW + 12, x1 = Math.max(x0 + 60, width - 76);
  const totals = rows.map((r) => r.parts.reduce((a, p) => a + Math.max(0, p.value), 0));
  const s = scale([0, Math.max(...totals, 1e-9)], [x0, x1], false, ticksFor(x1 - x0));
  const height = rows.length * rowH + 44;
  const names = Object.keys(colors);
  const cls = useDrawn(ref);
  return (
    <div ref={ref} className={cls} onMouseLeave={() => setTip(null)}>
      <Legend items={names.map((n) => ({ name: n, color: colors[n], shape: "square" }))} />
      {width > 0 && (
        <svg width={width} height={height} role="img" aria-label={`${axisLabel} by phase`}>
          {s.ticks.map((t) => <line key={t} x1={s(t)} x2={s(t)} y1={4} y2={height - 36} stroke="var(--grid)" />)}
          {rows.map((r, i) => {
            const cy = i * rowH + rowH / 2 + 4;
            let acc = 0;
            const parts = r.parts.filter((p) => p.value > 0);
            return (
              <g key={r.key}>
                <text x={0} y={cy + 4} className="row-label">{r.label}</text>
                <g className="a-bar" style={anim(i)}>{parts.map((p, j) => {
                  const xa = s(acc) + (j ? 1 : 0);
                  acc += p.value;
                  const w = Math.max(1, s(acc) - xa - (j < parts.length - 1 ? 1 : 0));
                  const last = j === parts.length - 1;
                  const path = last
                    ? `M${xa},${cy - barH / 2}h${Math.max(0, w - 4)}a4,4 0 0 1 4,4v${barH - 8}a4,4 0 0 1 -4,4h${-Math.max(0, w - 4)}z`
                    : `M${xa},${cy - barH / 2}h${w}v${barH}h${-w}z`;
                  return (
                    <path key={p.name} d={path} fill={colors[p.name] ?? "var(--chart-baseline)"}
                      onMouseMove={(e) => setTip({ x: e.nativeEvent.offsetX, y: cy, content: <><b>{r.label}</b><br />{p.name}: {format(p.value)}</> })} />
                  );
                })}</g>
                <text x={s(totals[i]) + 8} y={cy + 4} className="bar-value a-fade" style={anim(i + 6)}>{format(totals[i])}</text>
              </g>
            );
          })}
          <XAxis s={s} y={height - 36} x0={x0} x1={x1} fmt={axisFmt} label={axisLabel} />
        </svg>
      )}
      <Tooltip tip={tip} width={width} />
    </div>
  );
}

/* ------------------------------------------ inline delta bar for tables */

export function DeltaBar({ pct, lo, hi, max = 100 }: { pct: number; lo?: number; hi?: number; max?: number }) {
  const w = 120, mid = w / 2;
  const sx = (v: number) => mid + (Math.max(-max, Math.min(max, v)) / max) * mid;
  const good = pct < 0;
  return (
    <svg width={w} height={14} aria-hidden="true" style={{ verticalAlign: "middle" }}>
      <line x1={mid} x2={mid} y1={0} y2={14} stroke="var(--axis)" />
      <rect x={Math.min(sx(pct), mid)} y={4} width={Math.max(1, Math.abs(sx(pct) - mid))} height={6} rx={3}
        fill={good ? "var(--delta-good)" : "var(--delta-bad)"} />
      {lo !== undefined && hi !== undefined && <line x1={sx(lo)} x2={sx(hi)} y1={7} y2={7} stroke="var(--ink)" strokeWidth={1} opacity={0.6} />}
    </svg>
  );
}
