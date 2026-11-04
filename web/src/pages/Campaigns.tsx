import { ComputerDesktopIcon, ExclamationTriangleIcon, PlayIcon, StopCircleIcon } from "@heroicons/react/24/outline";
import { AnimatePresence, motion } from "motion/react";
import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, REPO_URL, STATIC, useApi } from "../api";
import { PlantHandIcon } from "../components/Icons";
import { EASE, reveal } from "../components/motion";
import { Checkbox, CircularProgress, LinearProgress, PageHeader, Radio, Skeleton } from "../components/ui";
import { ACTIVE, fmtDate, fmtDuration, fmtEnergy, fmtEstimate, STATE_LABELS } from "../format";
import type { CampaignSummary, Preset, StudyInfo } from "../types";

const SECONDS_PER_RUN: Record<string, number> = { quick: 1.3, standard: 3.4, full: 3.8 };

function StateChip({ state }: { state: string }) {
  const cls = state === "completed" ? "green" : ACTIVE.has(state) ? "accent" : state === "interrupted" ? "error" : "";
  return <span className={`chip ${cls}`}><span className="status-dot" />{STATE_LABELS[state] ?? state}</span>;
}

function LivePanel({ c, onCancel }: { c: CampaignSummary; onCancel: () => void }) {
  const s = c.status;
  const frac = s.total ? (s.done ?? 0) / s.total : 0;
  return (
    <motion.section className="card live-panel" initial={{ opacity: 0, y: -16, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, y: -12, scale: 0.98 }} transition={{ duration: 0.5, ease: EASE }}>
      <CircularProgress value={frac} size={140} stroke={10}>
        <div>
          <div className="ring-figure num">{Math.round(frac * 100)}%</div>
          <div className="label-s muted" style={{ marginTop: 4 }}>{s.done ?? 0} / {s.total ?? "?"} runs</div>
        </div>
      </CircularProgress>
      <div className="stack" style={{ flex: 1, minWidth: 0 }}>
        <div className="row wrap"><StateChip state={s.state} /><span className="label-m muted">{c.id}</span></div>
        <div className="title-l">{s.current?.label ?? STATE_LABELS[s.state]}</div>
        <div className="body-m secondary">
          {s.current ? (s.current.round < 0 ? "Warm-up run (discarded)" : `Round ${s.current.round + 1} of ${c.repetitions}`) : "Between runs"}
          {s.eta_s ? ` · about ${fmtDuration(s.eta_s)} left` : ""}
          {` · ${s.measured ?? 0} measured, ${s.invalid ?? 0} invalid, ${s.errors ?? 0} errors`}
        </div>
        <div className="callout warn body-m" style={{ marginTop: 4 }}>
          <ExclamationTriangleIcon />
          <span>Keep the machine quiet: the package meter sees every process. The dashboard pauses its live meter, its analysis and its background animations until the campaign ends.</span>
        </div>
        <div><button className="btn btn-danger has-icon" onClick={onCancel}><StopCircleIcon /> Stop after the current run</button></div>
      </div>
    </motion.section>
  );
}

export default function Campaigns() {
  const [params] = useSearchParams();
  const { data: presets } = useApi<Preset[]>("/presets");
  const { data: studies } = useApi<StudyInfo[]>("/studies");
  const { data: list, reload } = useApi<CampaignSummary[]>("/campaigns", 2500);
  const initial = params.get("studies")?.split(",").filter(Boolean);
  const [preset, setPreset] = useState("quick");
  const [selected, setSelected] = useState<string[] | null>(initial ?? null);
  const [reps, setReps] = useState("");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const chosen = selected ?? studies?.map((s) => s.id) ?? [];
  const running = list?.find((c) => ACTIVE.has(c.status.state));
  const p = presets?.find((x) => x.name === preset);
  const repsN = reps ? Number(reps) : p?.repetitions ?? 0;
  const repsInvalid = reps !== "" && !(Number.isInteger(repsN) && repsN >= 1 && repsN <= 100);
  const estimate = useMemo(() => {
    if (!studies || !p) return null;
    let configs = studies.filter((s) => chosen.includes(s.id)).reduce((a, s) => a + s.n_configs - s.n_skipped, 0);
    if (chosen.includes("join-algorithms") && chosen.includes("storage-formats")) configs -= 1; // shared configuration
    const runs = configs * (repsN + p.warmups);
    return { configs, runs, seconds: runs * (SECONDS_PER_RUN[p.name] ?? 3) + p.idle_s * 3 };
  }, [studies, p, chosen, repsN]);

  async function launch() {
    setBusy(true);
    setErr(null);
    try {
      await api("/campaigns", { method: "POST", body: JSON.stringify({ preset, studies: chosen, repetitions: reps ? repsN : null, notes }) });
      await reload();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function cancel(id: string) {
    try {
      await api(`/campaigns/${id}/cancel`, { method: "POST" });
      await reload();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <>
      <PageHeader eyebrow="Protocol · automated" title="Campaigns"
        description="A campaign runs every selected configuration in fresh processes, after warm-ups, in a new random order each round, with the idle baseline re-measured along the way. Results and statistics are stored next to the code." />
      <div className="content">
        {STATIC && (
          <motion.div className="callout body-m" {...reveal(0.05, 12)}>
            <ComputerDesktopIcon />
            <span>
              This is the hosted, read-only copy of the dashboard. A campaign measures the energy of the machine it runs on, so it
              starts from a local install: clone the repository, <code>pip install -e .</code>, then <code>greenbench serve</code>
              {REPO_URL && <> (steps in the <a href={REPO_URL}>README</a>)</>}.
            </span>
          </motion.div>
        )}
        <AnimatePresence>{running && <LivePanel key="live" c={running} onCancel={() => cancel(running.id)} />}</AnimatePresence>
        <div className="grid grid-sidebar">
          <motion.section className="card spot" {...reveal()}>
            <div className="card-head"><div><h3 className="title-l">New campaign</h3><div className="sub body-m">Measured on this machine.</div></div><span className="avatar"><PlayIcon /></span></div>
            <div className="stack" style={{ gap: 4 }}>
              <div className="form-label">Preset</div>
              {!presets ? <Skeleton height={150} /> : presets.map((x) => (
                <Radio key={x.name} name="preset" checked={preset === x.name} onChange={() => setPreset(x.name)}
                  title={`${x.label} · ${x.scale} data`} description={x.description} />
              ))}
              <div className="form-label" style={{ marginTop: 18 }}>Studies</div>
              {!studies ? <Skeleton height={200} /> : studies.map((s) => (
                <Checkbox key={s.id} checked={chosen.includes(s.id)} title={s.title} description={s.question}
                  onChange={(v) => setSelected(v ? [...chosen, s.id] : chosen.filter((x) => x !== s.id))} />
              ))}
              <div className="grid" style={{ gridTemplateColumns: "1fr", gap: 16, marginTop: 16 }}>
                <label className={`field${repsInvalid ? " error" : ""}`}>
                  <span className="label-s">Repetitions per configuration</span>
                  <span className="control"><input inputMode="numeric" placeholder={p ? String(p.repetitions) : "10"} value={reps} onChange={(e) => setReps(e.target.value)} /></span>
                  <span className="support body-s">{repsInvalid ? "Enter a whole number between 1 and 100" : "Leave empty to use the preset"}</span>
                </label>
                <label className="field">
                  <span className="label-s">Notes</span>
                  <span className="control"><input placeholder="e.g. laptop on battery, browser closed" value={notes} onChange={(e) => setNotes(e.target.value)} /></span>
                  <span className="support body-s">Stored with the results</span>
                </label>
              </div>
              {estimate && (
                <div className="callout body-m" style={{ marginTop: 16 }}>
                  <PlantHandIcon />
                  <span>{estimate.configs} configurations · {estimate.runs} runs · about {fmtEstimate(estimate.seconds)} on this machine</span>
                </div>
              )}
              {err && <div className="callout error body-m">{err}</div>}
              <div className="row" style={{ marginTop: 16 }}>
                <button className="btn btn-filled has-icon" disabled={STATIC || busy || Boolean(running) || chosen.length === 0 || repsInvalid} onClick={launch}>
                  <PlayIcon /> {STATIC ? "Launch from a local install" : running ? "A campaign is running" : busy ? "Starting…" : "Launch campaign"}
                </button>
              </div>
            </div>
          </motion.section>

          <section className="stack" style={{ gap: 16 }}>
            {!list ? <Skeleton height={200} /> : list.length === 0 ? (
              <div className="card empty">No campaign yet. Start with the quick preset to check the setup.</div>
            ) : list.map((c, i) => {
              const s = c.status;
              const active = ACTIVE.has(s.state);
              return (
                <motion.article key={c.id} className="card spot campaign-card" {...reveal(Math.min(i, 4) * 0.06)}>
                  <div className="row wrap" style={{ justifyContent: "space-between" }}>
                    <div>
                      <div className="title-m">{c.id}</div>
                      <div className="body-s muted">{fmtDate(c.created_at)} · {c.preset} preset · {c.scale} data · {c.repetitions} reps after {c.warmups} warm-ups</div>
                    </div>
                    <StateChip state={s.state} />
                  </div>
                  {c.notes && <p className="body-m secondary" style={{ marginTop: 10 }}>{c.notes}</p>}
                  {(active || s.state === "cancelled" || s.state === "interrupted") && s.total ? (
                    <div style={{ marginTop: 14 }}>
                      <LinearProgress value={(s.done ?? 0) / s.total} info={`${s.done ?? 0} of ${s.total} runs`} />
                    </div>
                  ) : null}
                  {c.quality && (
                    <div className="row wrap" style={{ marginTop: 14, gap: 8 }}>
                      <span className="chip green">{c.quality.valid}/{c.quality.runs} runs valid</span>
                      <span className="chip">{c.n_configs} configurations</span>
                      {c.totals && <span className="chip">{fmtEnergy(c.totals.energy_pkg_j)} measured</span>}
                      {c.idle_w && <span className="chip">idle {c.idle_w.toFixed(2)} W</span>}
                      {c.quality.invalid > 0 && <span className="chip error">{c.quality.invalid} invalid</span>}
                    </div>
                  )}
                  {c.best && <p className="body-m secondary" style={{ marginTop: 14 }}><b style={{ color: "var(--ink)" }}>Strongest result:</b> {c.best.text}</p>}
                  <div className="row" style={{ marginTop: 14, justifyContent: "flex-end" }}>
                    {active ? (
                      <button className="btn btn-danger sm" onClick={() => cancel(c.id)}>Stop</button>
                    ) : c.quality ? (
                      <Link className="btn btn-tonal sm" to={`/results/${c.id}`}>Open results</Link>
                    ) : null}
                  </div>
                </motion.article>
              );
            })}
          </section>
        </div>
      </div>
    </>
  );
}
