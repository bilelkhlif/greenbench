import { ArrowRightIcon, CalendarDaysIcon, CheckBadgeIcon } from "@heroicons/react/24/outline";
import { motion } from "motion/react";
import { useLayoutEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { STATIC, useApi } from "../api";
import { CountUp, reveal, rise } from "../components/motion";
import { RecommendationCard } from "../components/RecommendationCard";
import { LinearProgress, SectionHead, Skeleton } from "../components/ui";
import { fmtCompact, fmtEnergy, fmtNum, fmtPct } from "../format";
import type { Environment, Overview, RoadmapPhase } from "../types";

function phaseProgress(p: RoadmapPhase, week: number): number {
  const [a, b] = p.weeks;
  if (week > b) return 1;
  if (week < a) return 0;
  return (week - a + 1) / (b - a + 1);
}

// The title draws itself on the first visit only; coming back to the page shows it already lit.
let titleDrawn = false;

/** The name is drawn as an outline, then fills with light. Waits for the display font so the
    outline traces the real glyphs, and fits the viewBox to the measured text. */
function HeroTitle({ instant }: { instant: boolean }) {
  const text = useRef<SVGTextElement>(null);
  const [box, setBox] = useState("0 0 1000 170");
  const [go, setGo] = useState(false);
  useLayoutEffect(() => {
    let alive = true;
    Promise.all([document.fonts.load('700 132px "Space Grotesk Variable"'), document.fonts.ready]).catch(() => undefined).then(() => {
      if (!alive || !text.current) return;
      const b = text.current.getBBox();
      setBox(`${b.x - 14} ${b.y - 10} ${b.width + 28} ${b.height + 20}`);
      setGo(true);
      titleDrawn = true;
    });
    return () => { alive = false; };
  }, []);
  return (
    <h1 className={`hero-title${go ? (instant ? " done" : " go") : ""}`} aria-label="GreenBench AI">
      <svg viewBox={box} aria-hidden="true">
        <defs>
          <linearGradient id="hero-fill" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor="#ffffff" />
            <stop offset="0.5" stopColor="#d9fff6" />
            <stop offset="1" stopColor="#64dcc8" />
          </linearGradient>
          <linearGradient id="hero-fill-warm" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor="#ffe0a3" />
            <stop offset="1" stopColor="#f5b544" />
          </linearGradient>
        </defs>
        <g className="glow">
          <text ref={text} x="500" y="130" textAnchor="middle">GreenBench <tspan className="ai">AI</tspan></text>
        </g>
      </svg>
    </h1>
  );
}

export default function OverviewPage() {
  const { data: ov, error } = useApi<Overview>("/overview", 8000);
  const { data: env } = useApi<Environment>("/environment");
  const running = Boolean(ov?.running);
  const { data: live } = useApi<{ available: boolean; watts?: Record<string, number>; reason?: string }>(
    ov && !running && !STATIC ? "/meter/live" : null, 5000);

  const week = ov?.roadmap.current_week ?? 7;
  const latest = ov?.latest;
  const best = ov?.recommendations.find((r) => r.kind === "switch");
  const meter = env ? Object.values(env.meters).find((m) => m.available) : undefined;
  const nowPhase = ov?.roadmap.phases.find((p) => p.status === "in-progress");
  const toContent = () => document.getElementById("evidence")?.scrollIntoView({ behavior: "smooth", block: "start" });
  const [instant] = useState(() => titleDrawn);
  const k = instant ? 0.3 : 1; // hero delays are compressed on repeat visits

  return (
    <>
      <section className="home-hero">
        <motion.div className="hero-eyebrow" {...rise(0.05 * k, 10)}>SUP'COM · INDP3 SIA · Projet tutoré 2026–2027</motion.div>
        <HeroTitle instant={instant} />
        <motion.p className="hero-tagline" {...rise(0.9 * k)}>Same result. <span className="lit">Not the same energy.</span></motion.p>
        <motion.p className="body-l hero-text" {...rise(1.05 * k)}>
          Energy benchmarking of large-scale data-processing algorithms. Every variant is measured on the processor's
          own energy counters, checked against the same result, and compared with statistics that hold.
        </motion.p>
        <motion.div className="hero-meta" {...rise(1.2 * k)}>
          <span><CalendarDaysIcon /> Week {week} of 12{nowPhase ? ` · ${nowPhase.title.toLowerCase()} started` : ""}</span>
          <span><CheckBadgeIcon /> {latest?.quality ? `${latest.quality.valid}/${latest.quality.runs} results validated` : "Results validated by checksum"}</span>
          <span>
            <span className={`live-dot${live?.available ? "" : " off"}`} />
            {live?.available && live.watts ? `CPU package ${fmtNum(live.watts.pkg, 1)} W, live`
              : STATIC ? `Measured on ${env?.cpu.name.replace(/ with .*$/, "") ?? "the reference laptop"}`
              : running ? "Live meter paused: campaign running" : "CPU package meter"}
          </span>
        </motion.div>
        <motion.div className="hero-actions" {...rise(1.35 * k)}>
          <Link className="btn btn-filled lg" to="/results">Explore the results <ArrowRightIcon /></Link>
          <Link className="btn btn-outlined lg" to="/campaigns">Run a campaign</Link>
        </motion.div>
        <motion.button type="button" className="scroll-hint" onClick={toContent} initial={{ opacity: 0 }} animate={{ opacity: 1 }}
          transition={{ delay: 2 * k, duration: 1 }}>
          <span className="mouse" />
          Scroll
        </motion.button>
      </section>

      <div className="content" id="evidence">
        {error && <div className="callout error">Could not reach the GreenBench server: {error.message}</div>}
        {!ov ? <Skeleton height={140} /> : (
          <section className="stat-band">
            {[
              { label: "Runs measured", value: ov.runs_measured, fmt: (v: number) => fmtCompact(Math.round(v)),
                note: `${ov.campaigns} campaign${ov.campaigns === 1 ? "" : "s"}, one fresh process per run`, cls: "grad-text" },
              { label: "Energy measured", value: ov.energy_measured_j, fmt: fmtEnergy, note: "CPU-package energy over every measured region", cls: "grad-text" },
              { label: "Largest saving", value: best?.energy_change_pct ?? null, fmt: (v: number) => fmtPct(v),
                note: best ? `${best.label} vs ${best.baseline_label}` : "Run a campaign to get evidence", cls: "grad-mint" },
              { label: "Hardware vs model", value: ov.meter_check?.spearman_model_vs_dynamic ?? null, fmt: (v: number) => `ρ ${fmtNum(v, 2)}`,
                note: "Rank agreement between the energy counter and the software model", cls: "grad-text" },
            ].map((s, i) => (
              <motion.div key={s.label} className="card spot" {...reveal(i * 0.08)}>
                <div className={`stat-figure ${s.cls}`}>{s.value === null ? "–" : <CountUp value={s.value} format={s.fmt} />}</div>
                <div className="stat-caption">{s.label}</div>
                <div className="stat-note">{s.note}</div>
              </motion.div>
            ))}
          </section>
        )}

        <SectionHead eyebrow="Evidence" title="What the measurements say"
          sub="Each figure is a ratio of medians with a 95% bootstrap interval; only differences that survive the significance test are shown."
          action={<Link to="/recommendations" className="btn btn-text">All insights <ArrowRightIcon /></Link>} />
        {ov && ov.recommendations.length === 0 && (
          <div className="card empty">No significant result yet. Run the standard campaign to produce evidence.</div>
        )}
        <div className="grid grid-3">
          {(ov?.recommendations ?? []).slice(0, 6).map((r, i) => <RecommendationCard key={`${r.study}${r.config}`} rec={r} delay={(i % 3) * 0.08} />)}
        </div>

        {ov && ov.studies.length > 0 && (
          <>
            <SectionHead eyebrow="Trade-offs" title="Faster is not always greener"
              sub="One finding per study, ranked so that the ones that change a decision come first." />
            <motion.section className="card spot" {...reveal()}>
              <ul className="insight-list">
                {ov.studies.flatMap((s) => s.insights.slice(0, 1).map((i) => (
                  <li key={s.id + i}><Link to={`/results/${latest?.id}/${s.id}`} className="label-l">{s.title}</Link><span className="body-m">{i}</span></li>
                )))}
              </ul>
            </motion.section>
          </>
        )}

        <SectionHead eyebrow="Status" title="Where the project stands" />
        <div className="grid grid-2">
          <motion.section className="card spot" {...reveal()}>
            <div className="card-head">
              <div>
                <h3 className="title-l">Roadmap: week {week} of 12</h3>
                <div className="sub body-m">Weeks 1–6 delivered; the benchmark campaign has started.</div>
              </div>
              <Link to="/roadmap" className="btn btn-text">Roadmap <ArrowRightIcon /></Link>
            </div>
            <div className="stack" style={{ gap: 20 }}>
              {(ov?.roadmap.phases ?? []).map((p) => {
                const v = phaseProgress(p, week);
                return (
                  <LinearProgress key={p.id} label={`${p.title} · weeks ${p.weeks[0]}–${p.weeks[1]}`} value={v} done={v >= 1}
                    info={p.deliverable} right={v >= 1 ? "Delivered" : v > 0 ? `${Math.round(v * 100)}%` : "Upcoming"} />
                );
              })}
            </div>
          </motion.section>

          <motion.section className="card spot" {...reveal(0.08)}>
            <div className="card-head">
              <div>
                <h3 className="title-l">Measurement setup</h3>
                <div className="sub body-m">The machine every number on this dashboard comes from.</div>
              </div>
              <Link to="/protocol" className="btn btn-text">Protocol <ArrowRightIcon /></Link>
            </div>
            {!env ? <Skeleton height={180} /> : (
              <dl className="kv">
                <dt>Processor</dt><dd>{env.cpu.name} · {env.cpu.physical_cores} cores / {env.cpu.logical_cpus} threads</dd>
                <dt>Memory · OS</dt><dd>{env.memory_gb} GB · {env.os.system} {env.os.release}</dd>
                <dt>Energy meter</dt><dd>{meter?.interface ?? "Software model only"}{meter?.provider ? ` (${meter.provider})` : ""}</dd>
                <dt>Domains</dt><dd>{meter?.domains?.join(", ") ?? "–"}</dd>
                <dt>Idle power</dt><dd>{ov?.idle_w ? `${fmtNum(ov.idle_w, 2)} W, subtracted from every run` : "–"}</dd>
                <dt>Power</dt><dd>{env.power.plan ?? "–"} plan · {env.power.ac_plugged ? "on AC power" : env.power.ac_plugged === false ? "on battery" : "desktop"}</dd>
                <dt>Isolation</dt><dd>{env.virtualization.virtualized ? "virtualised (flagged)" : "bare metal, one process per run"}</dd>
                <dt>Model</dt><dd>TDP {env.cpu.tdp_w} W share × CPU time, for cross-checking</dd>
              </dl>
            )}
          </motion.section>
        </div>
      </div>
    </>
  );
}
