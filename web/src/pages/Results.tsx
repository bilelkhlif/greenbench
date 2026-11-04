import { ShieldCheckIcon } from "@heroicons/react/24/outline";
import { AnimatePresence, motion } from "motion/react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useApi } from "../api";
import { DeltaBar, DotPlot, Legend, LineChart, ScatterPlot, StackedBars, type DotRow, type LineSeries } from "../components/charts";
import { EASE, reveal } from "../components/motion";
import { RecommendationCard } from "../components/RecommendationCard";
import { PageHeader, Segmented, Skeleton, StatTile, Tabs } from "../components/ui";
import { durationAxis, energyAxis, fmtDuration, fmtEnergy, fmtNum, fmtP, fmtPct } from "../format";
import type { Analysis, CampaignSummary, ConfigAnalysis, StudyAnalysis, StudyGroup } from "../types";

const SERIES = ["var(--series-1)", "var(--series-2)", "var(--series-3)", "var(--series-4)"];
/** Short tab names; the study head shows the full question. */
const TAB_LABELS: Record<string, string> = {
  "join-algorithms": "Joins × threads", "storage-formats": "Storage formats", "text-search": "Scan vs index",
  "streaming-windows": "Streaming windows", indexing: "Indexing",
};
const PHASE_COLORS = ["var(--series-2)", "var(--series-1)", "var(--series-3)"];
type MetricKey = "energy_dyn_j" | "energy_pkg_j" | "energy_model_j";

function groupTitle(g: StudyGroup): string {
  const entries = Object.entries(g.group);
  if (!entries.length) return "";
  return entries.map(([k, v]) => (k === "n_queries"
    ? `${Number(v).toLocaleString("en-US")} quer${Number(v) === 1 ? "y" : "ies"}` : `${k} ${v}`)).join(" · ");
}

function metricOf(c: ConfigAnalysis | undefined, m: MetricKey) {
  return c?.metrics[m] ?? c?.metrics.energy_model_j;
}

function variantColors(study: StudyAnalysis): Record<string, string> {
  const variants = (study.factors.variant as string[] | undefined) ?? [];
  return Object.fromEntries(variants.map((v, i) => [v, SERIES[i % SERIES.length]]));
}

function GroupCharts({ study, g, configs, metric, metricLabel }: {
  study: StudyAnalysis; g: StudyGroup; configs: Map<string, ConfigAnalysis>; metric: MetricKey; metricLabel: string;
}) {
  const colors = variantColors(study);
  const rows = g.rows.filter((r) => !r.skipped && metricOf(configs.get(r.key), metric));
  const base = rows.find((r) => r.is_baseline);
  const baseMed = base ? metricOf(configs.get(base.key), metric)!.median : null;
  const dotRows: DotRow[] = rows.map((r) => {
    const c = configs.get(r.key)!;
    const m = metricOf(c, metric)!;
    const acc = c.accuracy ? Object.entries(c.accuracy).sort((a, b) => b[1].mape - a[1].mape)[0] : null;
    return {
      key: r.key, label: r.label, values: m.values, median: m.median, lo: m.ci_low, hi: m.ci_high, baseline: r.is_baseline,
      sub: r.is_baseline ? "baseline" : acc ? `≈ ${fmtNum(acc[1].mape * 100, 1)}% error on ${acc[0].replace(/_/g, " ")}` : undefined,
      tooltip: (
        <>
          <b>{r.label}</b><br />
          median {fmtEnergy(m.median)} [{fmtEnergy(m.ci_low)} – {fmtEnergy(m.ci_high)}]<br />
          n = {m.n}{m.cv !== null ? ` · CV ${fmtNum(m.cv * 100, 1)}%` : ""}
          {baseMed && !r.is_baseline ? <><br />{fmtPct((m.median / baseMed - 1) * 100)} vs baseline</> : null}
        </>
      ),
    };
  }).sort((a, b) => a.median - b.median);

  const phaseNames = Array.from(new Set(rows.flatMap((r) => Object.keys(configs.get(r.key)!.phases))));
  const phaseColors = Object.fromEntries(phaseNames.map((p, i) => [p, PHASE_COLORS[i % PHASE_COLORS.length]]));
  const phaseKey = metric === "energy_model_j" ? "energy_dyn_j" : metric;
  const stackRows = dotRows.map((d) => {
    const c = configs.get(d.key)!;
    return { key: d.key, label: d.label, parts: phaseNames.map((p) => ({ name: p, value: c.phases[p]?.[phaseKey] ?? c.phases[p]?.energy_pkg_j ?? 0 })) };
  });

  const scatter = rows.map((r) => {
    const c = configs.get(r.key)!;
    return {
      key: r.key, x: c.metrics.duration_s.median, y: metricOf(c, metric)!.median, label: r.label,
      color: study.factors.variant ? colors[r.variant] ?? SERIES[0] : SERIES[0], pareto: r.pareto,
      tooltip: <><b>{r.label}</b><br />{fmtEnergy(metricOf(c, metric)!.median)} in {fmtDuration(c.metrics.duration_s.median)}{r.pareto ? <><br />on the Pareto front</> : null}</>,
    };
  });
  const usedVariants = Array.from(new Set(rows.map((r) => r.variant)));

  return (
    <>
      <div className="grid grid-2">
        <motion.section className="card spot chart-card" {...reveal()}>
          <h3 className="title-m">{metricLabel} per configuration{groupTitle(g) ? ` · ${groupTitle(g)}` : ""}</h3>
          <p className="chart-sub body-s">Each dot is one repetition; the ringed marker is the median, the band its 95% bootstrap CI. Grey row and vertical line: baseline.</p>
          <DotPlot rows={dotRows} axisFmt={energyAxis} axisLabel={metricLabel} />
        </motion.section>
        <motion.section className="card spot chart-card" {...reveal(0.08)}>
          <h3 className="title-m">Energy against time</h3>
          <p className="chart-sub body-s">Medians. The light line joins the Pareto front: no other configuration is both faster and more frugal.</p>
          {study.factors.variant && usedVariants.length > 1 && (
            <Legend items={usedVariants.map((v) => ({ name: rows.find((r) => r.variant === v)!.label.split(" · ")[0], color: colors[v] }))} />
          )}
          <ScatterPlot points={scatter} xAxisFmt={durationAxis} yAxisFmt={energyAxis} xLabel="Duration" yLabel={metricLabel} frontier />
        </motion.section>
      </div>
      <motion.section className="card spot chart-card" {...reveal()}>
        <h3 className="title-m">Where the energy goes</h3>
        <p className="chart-sub body-s">Median energy of each phase of the measured region ({phaseKey === "energy_dyn_j" ? "dynamic" : "package"} energy).</p>
        <StackedBars rows={stackRows} colors={phaseColors} format={fmtEnergy} axisFmt={energyAxis} axisLabel="Energy per run" />
      </motion.section>
    </>
  );
}

function ComparisonTable({ g, configs, metric }: { g: StudyGroup; configs: Map<string, ConfigAnalysis>; metric: MetricKey }) {
  return (
    <div className="table-wrap">
      <table className="data">
        <thead>
          <tr>
            <th>Configuration</th><th className="num">Energy, median [95% CI]</th><th className="num">Δ energy [95% CI]</th><th />
            <th className="num">Duration</th><th className="num">Δ time</th><th className="num">p (Holm)</th><th>Cliff's δ</th>
            <th className="num">Peak memory</th><th className="num">n</th>
          </tr>
        </thead>
        <tbody>
          {g.rows.map((r) => {
            const c = configs.get(r.key);
            const m = metricOf(c, metric);
            if (r.skipped || !c || !m) {
              return <tr key={r.key}><td>{r.label}</td><td colSpan={9} className="muted">{r.skipped ? `Skipped: ${r.skipped}` : "No valid run"}</td></tr>;
            }
            return (
              <tr key={r.key} className={r.is_baseline ? "baseline" : ""}>
                <td style={{ whiteSpace: "nowrap" }}><span className="label-l">{r.label}</span>{r.is_baseline && <span className="chip ghost" style={{ marginLeft: 8 }}>baseline</span>}
                  {r.pareto && <span className="chip green" style={{ marginLeft: 8 }}>Pareto</span>}</td>
                <td className="num">{fmtEnergy(m.median)} <span className="muted">[{fmtEnergy(m.ci_low)}, {fmtEnergy(m.ci_high)}]</span></td>
                <td className="num">{r.energy_change_pct !== undefined ? <>{fmtPct(r.energy_change_pct)} <span className="muted">[{fmtPct(r.energy_change_ci_pct![0])}, {fmtPct(r.energy_change_ci_pct![1])}]</span></> : "–"}</td>
                <td>{r.energy_change_pct !== undefined && <DeltaBar pct={r.energy_change_pct} lo={r.energy_change_ci_pct![0]} hi={r.energy_change_ci_pct![1]} />}</td>
                <td className="num">{fmtDuration(c.metrics.duration_s.median)}</td>
                <td className="num">{fmtPct(r.duration_change_pct)}</td>
                <td className="num">{r.p_adj !== undefined ? <>{fmtP(r.p_adj)}{r.significant ? " ✓" : ""}</> : "–"}</td>
                <td style={{ whiteSpace: "nowrap" }}>{r.cliffs_delta !== undefined ? `${r.cliffs_delta > 0 ? "+" : ""}${fmtNum(r.cliffs_delta, 2)} ${r.magnitude}` : "–"}</td>
                <td className="num">{fmtNum(c.metrics.peak_rss_mb?.median, 0)} MB</td>
                <td className="num">{m.n}{c.n_invalid ? ` (${c.n_invalid} invalid)` : ""}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function ResponseCurves({ study, configs, metric, metricLabel }: { study: StudyAnalysis; configs: Map<string, ConfigAnalysis>; metric: MetricKey; metricLabel: string }) {
  const xKey = study.id === "join-algorithms" ? "threads" : study.id === "text-search" ? "n_queries" : null;
  if (!xKey) return null;
  const colors = variantColors(study);
  const keys = study.groups.flatMap((g) => g.rows.map((r) => r.key));
  const cs = keys.map((k) => configs.get(k)!).filter((c) => c && metricOf(c, metric));
  const variants = Array.from(new Set(cs.map((c) => c.variant)));
  const build = (pick: (c: ConfigAnalysis) => { y: number; lo: number; hi: number }): LineSeries[] =>
    variants.map((v) => ({
      name: cs.find((c) => c.variant === v)!.labels[study.id]?.split(" · ")[0] ?? v,
      color: colors[v],
      points: cs.filter((c) => c.variant === v).map((c) => ({ x: Number(c.params[xKey]), ...pick(c) })),
    }));
  const xTicks = (study.factors[xKey] as number[]).map(Number);
  const log = xKey === "n_queries";
  const xFormat = (v: number) => (xKey === "threads" ? `${v}` : v.toLocaleString("en-US"));
  const xLabel = xKey === "threads" ? "Threads" : "Queries (log scale)";
  return (
    <div className="grid grid-2">
      <motion.section className="card spot chart-card" {...reveal()}>
        <h3 className="title-m">{metricLabel} as {xKey === "threads" ? "threads increase" : "queries accumulate"}</h3>
        <p className="chart-sub body-s">Median with 95% CI whiskers.</p>
        <LineChart series={build((c) => { const m = metricOf(c, metric)!; return { y: m.median, lo: m.ci_low, hi: m.ci_high }; })}
          xTicks={xTicks} xLog={log} yLog={log} xFormat={xFormat} yFormat={fmtEnergy} yAxisFmt={energyAxis} xLabel={xLabel} yLabel={metricLabel} />
      </motion.section>
      <motion.section className="card spot chart-card" {...reveal(0.08)}>
        <h3 className="title-m">Duration</h3>
        <p className="chart-sub body-s">Same configurations, wall-clock time of the measured region.</p>
        <LineChart series={build((c) => { const m = c.metrics.duration_s; return { y: m.median, lo: m.ci_low, hi: m.ci_high }; })}
          xTicks={xTicks} xLog={log} yLog={log} xFormat={xFormat} yFormat={fmtDuration} yAxisFmt={durationAxis} xLabel={xLabel} yLabel="Duration" />
      </motion.section>
    </div>
  );
}

function QualityView({ a }: { a: Analysis }) {
  const mc = a.meter_check;
  const q = a.quality;
  return (
    <>
      <div className="grid grid-4">
        <StatTile label="Valid runs" value={`${q.valid}/${q.runs}`} note={`${q.invalid} failed the result checksum · ${q.errors} errors`} />
        <StatTile label="Idle baseline" value={`${fmtNum(a.idle_w, 2)} W`} note={`drift ${fmtNum(a.idle_drift_w, 2)} W across the campaign`} delay={0.06} />
        <StatTile label="Background load" value={`${fmtNum(a.idle_background_cores, 2)} cores`} note={`${q.noisy} runs flagged as noisy`} delay={0.12} />
        <StatTile label="Repeatability" value={q.median_cv !== null ? `${fmtNum(q.median_cv * 100, 1)}%` : "–"} note="median coefficient of variation" delay={0.18} />
      </div>
      {mc && mc.points && (
        <motion.section className="card spot chart-card" {...reveal(0.1)}>
          <h3 className="title-m">Hardware counter vs software model</h3>
          <p className="chart-sub body-s">
            Each dot is one run: RAPL dynamic energy against the CPU-time × TDP model. Spearman ρ = {fmtNum(mc.spearman_model_vs_dynamic, 2)},
            Pearson r = {fmtNum(mc.pearson_model_vs_dynamic, 2)}; the model reads {fmtNum(mc.median_ratio_model_over_dynamic, 2)}× the measured value (median). The line is y = x.
          </p>
          {mc.verdicts && (
            <div className={`callout ${mc.verdicts.model_reverses ? "warn" : ""} body-m`} style={{ marginBottom: 16 }}>
              <ShieldCheckIcon />
              <div>
                <b>Same verdicts?</b> Of the {mc.verdicts.hardware_significant_pairs} configuration pairs the hardware counter tells apart,
                the model agrees on {mc.verdicts.model_agrees} and significantly reverses {mc.verdicts.model_reverses}.
                {mc.verdicts.reversals.length > 0 && (
                  <ul style={{ margin: "8px 0 0", paddingLeft: 18 }}>
                    {mc.verdicts.reversals.map((r) => (
                      <li key={r.a + r.b}>{r.a} vs {r.b}: hardware ×{fmtNum(r.hardware_ratio, 2)}, model ×{fmtNum(r.model_ratio, 2)}</li>
                    ))}
                  </ul>
                )}
              </div>
            </div>
          )}
          <ScatterPlot points={mc.points.filter((p) => p.dynamic > 0 && p.model > 0).map((p, i) => ({ key: String(i), x: p.dynamic, y: p.model, color: "var(--series-1)" }))}
            xLog yLog diagonal r={3.5} xAxisFmt={energyAxis} yAxisFmt={energyAxis} xLabel="RAPL dynamic energy" yLabel="Model estimate" height={340} />
        </motion.section>
      )}
    </>
  );
}

export default function Results() {
  const { campaignId, studyId } = useParams();
  const navigate = useNavigate();
  const { data: campaigns } = useApi<CampaignSummary[]>("/campaigns");
  const completed = (campaigns ?? []).filter((c) => c.quality);
  const cid = campaignId && campaignId !== "latest" ? campaignId : completed[0]?.id;
  const { data: a, error } = useApi<Analysis>(cid ? `/campaigns/${cid}/analysis` : null);
  const [metric, setMetric] = useState<MetricKey>("energy_dyn_j");
  const configs = useMemo(() => new Map((a?.configs ?? []).map((c) => [c.key, c])), [a]);
  const effMetric: MetricKey = a && a.primary_metric === "energy_model_j" ? "energy_model_j" : metric;
  const tab = studyId ?? a?.studies[0]?.id ?? "";
  const study = a?.studies.find((s) => s.id === tab);
  const metricLabel = a?.metrics[effMetric]?.label ?? "Energy";

  // Slide the study panel in from the side of the tab that was picked.
  const order = [...(a?.studies.map((s) => s.id) ?? []), "quality"];
  const index = order.indexOf(tab);
  const last = useRef(index);
  const direction = index >= last.current ? 1 : -1;
  useEffect(() => { last.current = index; }, [index]);

  return (
    <>
      <PageHeader eyebrow="Benchmark campaign · weeks 7–9" title="Results"
        description="Distributions, confidence intervals and significance tests for every study. Every percentage is a ratio of medians with a 95% bootstrap interval; p-values are Mann–Whitney U with Holm correction within each study." />
      <div className="content">
        <motion.div className="filter-row" {...reveal(0.1, 14)}>
          <label className="field" style={{ minWidth: 280 }}>
            <span className="label-s">Campaign</span>
            <span className="control">
              <select value={cid ?? ""} onChange={(e) => navigate(`/results/${e.target.value}/${tab}`)}>
                {completed.map((c) => <option key={c.id} value={c.id}>{c.id} · {c.preset}</option>)}
              </select>
            </span>
          </label>
          <div className="field">
            <span className="label-s">Energy metric</span>
            <Segmented label="Energy metric" value={effMetric} onChange={(v) => setMetric(v)} options={[
              { value: "energy_dyn_j", label: "Dynamic" }, { value: "energy_pkg_j", label: "Package" }, { value: "energy_model_j", label: "Model" },
            ]} />
          </div>
        </motion.div>
        {!cid && campaigns && <div className="card empty">No analysed campaign yet. <Link to="/campaigns">Run one.</Link></div>}
        {error && <div className="callout error">{error.message}</div>}
        {cid && !a && !error && <Skeleton height={420} />}
        {a && (
          <>
            <motion.div {...reveal(0.15, 14)}>
              <Tabs label="Studies" value={tab} onChange={(id) => navigate(`/results/${cid}/${id}`)}
                items={[...a.studies.map((s) => ({ id: s.id, label: TAB_LABELS[s.id] ?? s.title })), { id: "quality", label: <><ShieldCheckIcon /> Measurement quality</> }]} />
            </motion.div>
            <AnimatePresence mode="wait" custom={direction} initial={false}>
              <motion.div key={tab} className="stack" style={{ gap: 24 }} custom={direction}
                variants={{
                  initial: (d: number) => ({ opacity: 0, x: 48 * d }),
                  enter: { opacity: 1, x: 0, transition: { duration: 0.45, ease: EASE } },
                  exit: (d: number) => ({ opacity: 0, x: -36 * d, transition: { duration: 0.2, ease: [0.4, 0, 1, 1] } }),
                }}
                initial="initial" animate="enter" exit="exit">
                {tab === "quality" && <QualityView a={a} />}
                {study && (
                  <>
                    <section className="card mint study-head">
                      <div>
                        <div className="eyebrow">{study.title}</div>
                        <h2 className="headline-m">{study.question}</h2>
                        <p className="body-s muted" style={{ marginTop: 8 }}>{a.metrics[effMetric]?.description}</p>
                      </div>
                      <div className="row wrap" style={{ gap: 8 }}>
                        {study.groups.map((g) => g.baseline && (
                          <span key={g.baseline} className="chip">baseline: {g.rows.find((r) => r.is_baseline)?.label}</span>
                        ))}
                      </div>
                    </section>
                    <div className="grid grid-3">
                      {study.recommendations.map((r, i) => <RecommendationCard key={r.config + JSON.stringify(r.group)} rec={r} delay={(i % 3) * 0.06} />)}
                      {study.insights.length > 0 && (
                        <motion.section className={`card spot insights-fill rem-${study.recommendations.length % 3}`} {...reveal(0.12)}>
                          <div className="eyebrow" style={{ marginBottom: 10 }}>Insights</div>
                          <ul className="insight-list">{study.insights.map((i) => <li key={i}><span className="body-m">{i}</span></li>)}</ul>
                        </motion.section>
                      )}
                    </div>
                    <ResponseCurves study={study} configs={configs} metric={effMetric} metricLabel={metricLabel} />
                    {study.groups.map((g) => (
                      <div key={JSON.stringify(g.group)} className="stack" style={{ gap: 24 }}>
                        {groupTitle(g) && <h3 className="headline-s group-title">{groupTitle(g)}</h3>}
                        <GroupCharts study={study} g={g} configs={configs} metric={effMetric} metricLabel={metricLabel} />
                        <motion.section className="card" {...reveal()}>
                          <div className="eyebrow" style={{ marginBottom: 14 }}>Statistics</div>
                          <ComparisonTable g={g} configs={configs} metric={effMetric} />
                        </motion.section>
                      </div>
                    ))}
                  </>
                )}
              </motion.div>
            </AnimatePresence>
          </>
        )}
      </div>
    </>
  );
}
