import { motion } from "motion/react";
import { fmtPct } from "../format";
import type { Recommendation } from "../types";
import { reveal } from "./motion";

const KIND_LABEL = { switch: "Switch", keep: "Keep baseline", "trade-off": "Trade-off", inconclusive: "No clear winner" };

export function RecommendationCard({ rec, delay = 0 }: { rec: Recommendation; delay?: number }) {
  const ci = rec.energy_change_ci_pct;
  const keep = rec.kind === "keep";
  return (
    <motion.article className={`rec-card spot${rec.significant ? "" : " is-muted"}`} {...reveal(delay)}
      whileHover={{ y: -6, transition: { type: "spring", stiffness: 300, damping: 22 } }}>
      <div className="rec-top">
        <span className={`kind kind-${rec.kind}`}>{KIND_LABEL[rec.kind]}</span>
        {rec.significant && <span className="effect">{rec.magnitude} effect</span>}
      </div>
      <div className={`rec-number ${rec.energy_change_pct < 0 ? "good" : "warm"}`}>{fmtPct(rec.energy_change_pct)}</div>
      <div className="rec-vs">{keep ? `energy of the best alternative, ${rec.label}` : `energy vs ${rec.baseline_label}`}</div>
      <h3 className="rec-title">{keep ? rec.baseline_label : rec.label}</h3>
      <p className="rec-text">{rec.text}</p>
      <div className="rec-meta">
        <span className="chip">95% CI {fmtPct(ci[0])} to {fmtPct(ci[1])}</span>
        <span className="chip">latency {fmtPct(rec.duration_change_pct)}</span>
        {!rec.exact && <span className="chip accent">approximate</span>}
      </div>
    </motion.article>
  );
}
