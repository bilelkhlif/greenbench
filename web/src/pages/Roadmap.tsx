import { CheckCircleIcon, ClockIcon, DocumentTextIcon } from "@heroicons/react/24/outline";
import { motion } from "motion/react";
import { Link } from "react-router-dom";
import { useApi } from "../api";
import { EASE, reveal } from "../components/motion";
import { PageHeader, Skeleton } from "../components/ui";
import type { Roadmap } from "../types";

const STATUS_LABEL = { done: "Delivered", "in-progress": "In progress", todo: "Upcoming" } as const;

export default function RoadmapPage() {
  const { data } = useApi<Roadmap>("/roadmap");
  const weeks = Array.from({ length: 12 }, (_, i) => i + 1);
  return (
    <>
      <PageHeader eyebrow="Roadmap · slide 10" title="12-week roadmap & deliverables"
        description={data ? `We are at the end of week ${data.current_week}: the state of the art and the measurement protocol are delivered, and the benchmark campaign has started.` : ""} />
      <div className="content">
        {!data ? <Skeleton height={320} /> : (
          <>
            <motion.section className="card gantt" {...reveal(0.1)}>
              <div className="gantt-head">
                <span className="label-m">PHASE</span>
                <div className="gantt-weeks">{weeks.map((w) => <span key={w} className={w === data.current_week ? "now" : undefined}>W{w}</span>)}</div>
                <span className="label-m">DELIVERABLE</span>
              </div>
              {data.phases.map((p, i) => (
                <div key={p.id} className={`gantt-row ${p.status}`}>
                  <div>
                    <div className="title-m">{p.title}</div>
                    <div className="body-s muted">Weeks {p.weeks[0]}–{p.weeks[1]} · {p.summary}</div>
                  </div>
                  <div className="gantt-track">
                    <motion.div className="gantt-bar" style={{ gridColumn: `${p.weeks[0]} / ${p.weeks[1] + 1}` }}
                      initial={{ scaleX: 0 }} whileInView={{ scaleX: 1 }} viewport={{ once: true }}
                      transition={{ duration: 0.9, ease: EASE, delay: 0.25 + i * 0.12 }} />
                    <div className="gantt-now" style={{ gridColumn: `${data.current_week} / ${data.current_week + 1}` }} />
                  </div>
                  <div className="row" style={{ gap: 12 }}>
                    <span className="avatar accent" style={{ width: 34, height: 34, borderRadius: 11 }}><DocumentTextIcon /></span>
                    <span className="body-m">{p.deliverable}</span>
                  </div>
                </div>
              ))}
            </motion.section>

            <div className="grid grid-2">
              {data.phases.map((p, i) => (
                <motion.section key={p.id} className={`card spot phase-card ${p.status}`} {...reveal((i % 2) * 0.08)}>
                  <div className="card-head">
                    <div>
                      <div className="eyebrow" style={{ marginBottom: 8 }}>Phase {String(i + 1).padStart(2, "0")} · weeks {p.weeks[0]}–{p.weeks[1]}</div>
                      <h3 className="title-l">{p.title}</h3>
                    </div>
                    <span className={`chip ${p.status === "done" ? "green" : p.status === "in-progress" ? "accent" : ""}`}>
                      <span className="status-dot" />{STATUS_LABEL[p.status]}
                    </span>
                  </div>
                  <ul className="task-list">
                    {p.tasks.map((t) => (
                      <li key={t.week} className={t.status}>
                        {t.status === "done" ? <CheckCircleIcon /> : <ClockIcon />}
                        <div><span className="label-m">WEEK {t.week}{t.week === data.current_week ? " · NOW" : ""}</span><p className="body-m">{t.text}</p></div>
                      </li>
                    ))}
                  </ul>
                  <div className="row wrap" style={{ gap: 8, marginTop: 16 }}>
                    {p.links.map((l) => <Link key={l.doc} to={`/protocol/${l.doc}`} className="btn btn-tonal sm">{l.label}</Link>)}
                    {p.id === "campaign" && <Link to="/results" className="btn btn-outlined sm">Campaign results</Link>}
                  </div>
                </motion.section>
              ))}
            </div>
          </>
        )}
      </div>
    </>
  );
}
