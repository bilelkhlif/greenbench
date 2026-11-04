import { AdjustmentsHorizontalIcon, ArrowRightIcon } from "@heroicons/react/24/outline";
import { motion } from "motion/react";
import { Link } from "react-router-dom";
import { useApi } from "../api";
import { WORKLOAD_ICONS } from "../components/Icons";
import { reveal } from "../components/motion";
import { PageHeader, Skeleton } from "../components/ui";
import type { WorkloadInfo } from "../types";

const KNOB_LABELS: Record<string, string> = { threads: "threads", storage: "storage format", n_queries: "query count" };

function Illustration({ name }: { name: string }) {
  // Light on the dark media panel: mint strokes, amber highlights, faint glass rows.
  const g = "#64dcc8", g2 = "#34d399", m = "#f5b544", m2 = "#c98500", t = "rgba(255,255,255,0.16)", w = "rgba(255,255,255,0.07)";
  if (name === "joins") {
    return (
      <svg viewBox="0 0 320 150" width="100%" height="100%" aria-hidden="true" className="illus deco">
        {[0, 1, 2, 3, 4, 5].map((i) => <rect key={i} x={30} y={22 + i * 18} width={70} height={12} rx={3} fill={i % 2 ? t : w} />)}
        <rect x={30} y={10} width={70} height={8} rx={3} fill={g} />
        {[0, 1, 2].map((i) => <rect key={i} x={120} y={40 + i * 18} width={56} height={12} rx={3} fill={i % 2 ? t : w} />)}
        <rect x={120} y={28} width={56} height={8} rx={3} fill={m2} />
        <path className="flow" d="M104 60 C 150 60 170 75 206 75 M180 66 C 192 66 196 75 206 75" fill="none" stroke={g2} strokeWidth={3} strokeLinecap="round" />
        <path d="m200 69 8 6-8 6" fill="none" stroke={g2} strokeWidth={3} strokeLinecap="round" strokeLinejoin="round" />
        {[0, 1, 2, 3].map((i) => (
          <g key={i}>
            <rect x={218} y={44 + i * 18} width={46} height={12} rx={3} fill={w} />
            <rect x={268} y={44 + i * 18} width={24} height={12} rx={3} fill={i === 0 ? m : t} />
          </g>
        ))}
        <rect x={218} y={32} width={74} height={8} rx={3} fill={g} />
      </svg>
    );
  }
  if (name === "text_search") {
    return (
      <svg viewBox="0 0 320 150" width="100%" height="100%" aria-hidden="true" className="illus deco">
        {[0, 1, 2].map((d) => (
          <g key={d} transform={`translate(${40 + d * 22},${18 + d * 10})`}>
            <rect width={120} height={96} rx={8} fill="rgba(13,20,31,0.9)" stroke={t} />
            {[0, 1, 2, 3, 4].map((l) => <rect key={l} x={14} y={16 + l * 15} width={l === 4 ? 50 : 92} height={6} rx={3} fill={t} />)}
            {d === 2 && <rect x={50} y={30} width={30} height={8} rx={3} fill={m} />}
            {d === 2 && <rect x={18} y={60} width={26} height={8} rx={3} fill={m} />}
          </g>
        ))}
        <g className="scan">
          <circle cx={232} cy={70} r={30} fill="rgba(100,220,200,0.08)" stroke={g} strokeWidth={6} />
          <path d="m254 92 26 26" stroke={g} strokeWidth={9} strokeLinecap="round" />
        </g>
      </svg>
    );
  }
  if (name === "streaming") {
    const xs = Array.from({ length: 34 }, (_, i) => 24 + i * 8.2 + ((i * 37) % 5));
    return (
      <svg viewBox="0 0 320 150" width="100%" height="100%" aria-hidden="true" className="illus deco">
        <line x1={18} x2={302} y1={100} y2={100} stroke={t} strokeWidth={2} />
        {xs.map((x, i) => <circle key={i} cx={x} cy={100 - ((i * 53) % 4) * 6} r={3.5} fill={i % 3 ? g2 : g} />)}
        {[0, 1, 2].map((w) => (
          <rect key={w} x={34 + w * 40} y={34 + w * 14} width={150} height={16} rx={8} fill={w === 2 ? "rgba(245,181,68,0.25)" : "none"}
            stroke={w === 2 ? m : g} strokeWidth={2} opacity={w === 2 ? 1 : 0.6} className={w === 2 ? "slide" : undefined} />
        ))}
        <text x={186} y={128} fontSize={10.5} fill="#7a8896" fontFamily="JetBrains Mono Variable, monospace">5-min windows, slide 1 min</text>
      </svg>
    );
  }
  return (
    <svg viewBox="0 0 320 150" width="100%" height="100%" aria-hidden="true" className="illus deco">
      <rect x={130} y={14} width={60} height={22} rx={6} fill={g} />
      {[0, 1, 2].map((i) => (
        <g key={i}>
          <path d={`M160 36 L ${70 + i * 90} 66`} stroke={t} strokeWidth={2} />
          <rect x={44 + i * 90} y={66} width={52} height={20} rx={6} fill={w} stroke={g2} strokeWidth={2} />
          {[0, 1].map((j) => (
            <g key={j}>
              <path d={`M${70 + i * 90} 86 L ${56 + i * 90 + j * 28} 112`} stroke={t} strokeWidth={2} />
              <rect x={44 + i * 90 + j * 28} y={112} width={24} height={18} rx={4} fill={i === 1 && j === 0 ? m : w} stroke={t} className={i === 1 && j === 0 ? "blink" : undefined} />
            </g>
          ))}
        </g>
      ))}
    </svg>
  );
}

export default function Workloads() {
  const { data } = useApi<WorkloadInfo[]>("/workloads");
  return (
    <>
      <PageHeader eyebrow="Methodology · slide 6" title="What we benchmark"
        description="Four representative data-processing tasks over seeded multi-source data. Each has implementation variants that must return the same result, plus cross-cutting knobs: storage format, compression, parallelism and query volume." />
      <div className="content">
        {!data ? <Skeleton height={400} /> : (
          <div className="grid grid-2">
            {data.map((w, i) => {
              const Icon = WORKLOAD_ICONS[w.icon] ?? AdjustmentsHorizontalIcon;
              return (
                <motion.article key={w.name} className="card spot product-card" {...reveal((i % 2) * 0.1)}>
                  <div className="pc-header">
                    <span className="avatar"><Icon /></span>
                    <div className="titles">
                      <div className="title-m">{w.title}</div>
                      <div className="body-m">{w.summary}</div>
                    </div>
                    <span className="chip green">{w.variants.length} variants</span>
                  </div>
                  <div className="pc-media"><Illustration name={w.name} /></div>
                  <div className="pc-body">
                    <div className="title-m">Variants compared</div>
                    <div className="label-m">
                      knobs: {Object.keys(w.knobs).map((k) => KNOB_LABELS[k] ?? k).join(" · ")} · inputs: {w.inputs.join(", ")}
                    </div>
                    <p className="body-m">{w.description}</p>
                    <ul className="variant-list">
                      {w.variants.map((v) => (
                        <li key={v.name}>
                          <div className="row" style={{ gap: 8 }}>
                            <span className="label-l">{v.label}</span>
                            {v.name === w.reference_variant && <span className="chip ghost">reference</span>}
                            {!v.exact && <span className="chip accent">approximate</span>}
                          </div>
                          <span className="body-s muted">{v.description}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                  <div className="pc-actions">
                    <Link className="btn btn-outlined" to={`/campaigns?studies=${w.studies.join(",")}`}>Run its study</Link>
                    <Link className="btn btn-filled" to={`/results/latest/${w.studies[0]}`}>See results <ArrowRightIcon /></Link>
                  </div>
                </motion.article>
              );
            })}
          </div>
        )}
      </div>
    </>
  );
}
