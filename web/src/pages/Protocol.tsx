import { ArrowPathIcon, ChartBarIcon, DocumentTextIcon } from "@heroicons/react/24/outline";
import { marked } from "marked";
import { AnimatePresence, motion } from "motion/react";
import { useMemo } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useApi } from "../api";
import { PlantHandIcon } from "../components/Icons";
import { EASE, reveal } from "../components/motion";
import { PageHeader, Skeleton, Tabs } from "../components/ui";
import type { CampaignSummary } from "../types";

const STEPS = [
  { icon: PlantHandIcon, title: "Bring a workload", text: "A task, its variants, its knobs, and a checksum that proves every variant returns the same result." },
  { icon: ArrowPathIcon, title: "Isolate & repeat", text: "Fresh process per run, warm-ups discarded, randomised rounds, idle baseline, background-load check." },
  { icon: ChartBarIcon, title: "Measure energy & time", text: "RAPL package and core energy per phase, wall and CPU time, peak memory, plus a software model." },
  { icon: DocumentTextIcon, title: "Recommendation report", text: "Bootstrap CIs, Mann–Whitney with Holm, Cliff's δ, Pareto fronts: “X cuts energy by N% for Y% latency”." },
];

interface Doc { slug: string; title: string; available: boolean }

export default function Protocol() {
  const { slug } = useParams();
  const navigate = useNavigate();
  const { data: docs } = useApi<Doc[]>("/docs");
  const current = slug ?? "measurement-protocol";
  const { data: doc, error } = useApi<{ slug: string; title: string; markdown: string }>(`/docs/${current}`);
  const { data: campaigns } = useApi<CampaignSummary[]>("/campaigns");
  const latest = campaigns?.find((c) => c.quality);
  const html = useMemo(() => (doc ? (marked.parse(doc.markdown, { async: false }) as string) : ""), [doc]);

  return (
    <>
      <PageHeader eyebrow="Deliverables · weeks 1–6" title="Protocol & reports"
        description="How GreenBench builds evidence, and the written deliverables: the state-of-the-art report (weeks 1–3), the documented measurement protocol (weeks 4–6) and the week-7 campaign report." />
      <div className="content">
        <section className="pipeline">
          {STEPS.map((s, i) => (
            <motion.div key={s.title} className={`card spot pipe-step${i === STEPS.length - 1 ? " last" : ""}`} {...reveal(i * 0.1)}>
              <div className="row" style={{ justifyContent: "space-between" }}>
                <span className="avatar"><s.icon /></span>
                <span className="step-num">STEP {String(i + 1).padStart(2, "0")}</span>
              </div>
              <div>
                <div className="title-m">{s.title}</div>
                <div className="body-s" style={{ marginTop: 6 }}>{s.text}</div>
              </div>
            </motion.div>
          ))}
        </section>

        {latest && (
          <motion.div className="row wrap" style={{ gap: 8 }} {...reveal(0.1, 12)}>
            <span className="eyebrow" style={{ marginRight: 6 }}>Latest campaign</span>
            <span className="chip green">{latest.repetitions} repetitions</span>
            <span className="chip green">{latest.warmups} warm-ups</span>
            <span className="chip">{latest.scale} datasets</span>
            <span className="chip">{latest.n_configs} configurations</span>
            {latest.meter && <span className="chip">{latest.meter}</span>}
            {latest.idle_w && <span className="chip">idle {latest.idle_w.toFixed(2)} W subtracted</span>}
          </motion.div>
        )}

        <motion.div {...reveal(0.1, 12)}>
          <Tabs label="Documents" value={current} onChange={(id) => navigate(`/protocol/${id}`)}
            items={(docs ?? []).map((d) => ({ id: d.slug, label: d.title, disabled: !d.available }))} />
        </motion.div>
        <motion.article className="card markdown-card" {...reveal(0.15)}>
          {error ? <div className="empty">{error.message}</div> : !doc ? <Skeleton height={400} /> : (
            <AnimatePresence mode="wait" initial={false}>
              <motion.div key={doc.slug} className="markdown" dangerouslySetInnerHTML={{ __html: html }}
                initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0, transition: { duration: 0.45, ease: EASE } }}
                exit={{ opacity: 0, y: -8, transition: { duration: 0.18 } }} />
            </AnimatePresence>
          )}
        </motion.article>
      </div>
    </>
  );
}
