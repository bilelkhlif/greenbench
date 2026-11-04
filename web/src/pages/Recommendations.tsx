import { ArrowRightIcon, InformationCircleIcon } from "@heroicons/react/24/outline";
import { motion } from "motion/react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { useApi } from "../api";
import { reveal } from "../components/motion";
import { RecommendationCard } from "../components/RecommendationCard";
import { PageHeader, SectionHead, Segmented, Skeleton } from "../components/ui";
import type { Analysis, CampaignSummary } from "../types";

export default function Recommendations() {
  const { data: campaigns } = useApi<CampaignSummary[]>("/campaigns");
  const latest = (campaigns ?? []).find((c) => c.quality);
  const { data: a } = useApi<Analysis>(latest ? `/campaigns/${latest.id}/analysis` : null);
  const [filter, setFilter] = useState<"significant" | "all">("significant");

  return (
    <>
      <PageHeader eyebrow="Proposed solution · slide 7" title="Quantified recommendations"
        description={<>Each recommendation states the gain and its cost, in the form “<i>X cuts energy by N% for a Y% latency cost</i>”, with a 95% confidence interval and an effect size. Evidence from campaign {latest ? <Link to={`/results/${latest.id}`}>{latest.id}</Link> : "…"}.</>}
        actions={<Segmented label="Filter" value={filter} onChange={setFilter} options={[{ value: "significant", label: "Significant" }, { value: "all", label: "All" }]} />} />
      <div className="content">
        <motion.div className="callout body-m" {...reveal(0.1, 14)}>
          <InformationCircleIcon />
          <span>
            Energy is the <b>dynamic</b> CPU-package energy: what the computation added on top of the idle baseline. A result is
            significant when the Mann–Whitney test, Holm-corrected within its study, gives p &lt; 0.05. Cliff's δ grades the effect
            (negligible &lt; 0.147 ≤ small &lt; 0.33 ≤ medium &lt; 0.474 ≤ large). Approximate variants also report their error.
          </span>
        </motion.div>
        {!a ? <Skeleton height={300} /> : a.studies.map((s, n) => {
          const recs = s.recommendations.filter((r) => filter === "all" || r.significant);
          return (
            <section key={s.id} className="stack" style={{ gap: 18 }}>
              <SectionHead eyebrow={`Study ${String(n + 1).padStart(2, "0")}`} title={s.title} sub={s.question}
                action={<Link to={`/results/${a.campaign_id}/${s.id}`} className="btn btn-text">Evidence <ArrowRightIcon /></Link>} />
              {recs.length === 0 && (
                <motion.div className="card flat body-m muted" {...reveal()}>No significant energy saving against the baseline in this study.</motion.div>
              )}
              <div className="grid grid-3">
                {recs.map((r, i) => <RecommendationCard key={r.config + JSON.stringify(r.group)} rec={r} delay={(i % 3) * 0.06} />)}
                {s.insights.length > 0 && (
                  <motion.section className={`card spot insights-fill rem-${recs.length % 3}`} {...reveal(0.1)}>
                    <div className="eyebrow" style={{ marginBottom: 10 }}>Insights</div>
                    <ul className="insight-list">{s.insights.map((i) => <li key={i}><span className="body-m">{i}</span></li>)}</ul>
                  </motion.section>
                )}
              </div>
            </section>
          );
        })}
      </div>
    </>
  );
}
