import { AnimatePresence, motion, MotionConfig } from "motion/react";
import { useEffect } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { prefetch, REPO_URL, STATIC, useApi } from "./api";
import { LogoMark } from "./components/Logo";
import { EASE, pageVariants, useSpotlight } from "./components/motion";
import { Sky } from "./components/Sky";
import { TopNav } from "./components/TopNav";
import { ACTIVE } from "./format";
import Campaigns from "./pages/Campaigns";
import Overview from "./pages/Overview";
import Protocol from "./pages/Protocol";
import Recommendations from "./pages/Recommendations";
import Results from "./pages/Results";
import RoadmapPage from "./pages/Roadmap";
import Workloads from "./pages/Workloads";
import type { CampaignSummary } from "./types";

function Footer() {
  return (
    <footer className="site-footer">
      <div className="footer-inner">
        <span className="footer-brand"><LogoMark size={22} /><b>GreenBench AI</b> · Same result. Not the same energy.</span>
        <span>
          © 2026 Bajar Omar · Khlif Bilel · SUP'COM INDP3 SIA tutored project
          {STATIC && " · snapshot of the committed results"}
          {REPO_URL && <> · <a href={REPO_URL}>Source on GitHub</a></>}
        </span>
      </div>
    </footer>
  );
}

export default function App() {
  const location = useLocation();
  const section = location.pathname.split("/")[1] || "home";
  const { data } = useApi<CampaignSummary[]>("/campaigns", 5000);
  const running = data?.find((c) => ACTIVE.has(c.status.state));
  const latest = data?.find((c) => c.quality)?.id;
  useSpotlight();
  useEffect(() => {
    prefetch(["/overview", "/environment", "/workloads", "/studies", "/presets", "/roadmap", "/docs", "/docs/measurement-protocol"]);
  }, []);
  useEffect(() => {
    if (latest) prefetch([`/campaigns/${latest}/analysis`]);
  }, [latest]);

  return (
    <MotionConfig reducedMotion="user">
      {/* "quiet" pauses decorative animation while a campaign measures this machine */}
      <div className={`app${running ? " quiet" : ""}`}>
        <Sky scene={section} />
        <motion.div key={location.pathname} className="route-beam" aria-hidden="true" initial={{ scaleX: 0, opacity: 1 }}
          animate={{ scaleX: 1, opacity: 0 }} transition={{ scaleX: { duration: 0.7, ease: EASE }, opacity: { duration: 0.45, delay: 0.55 } }} />
        <TopNav running={running} />
        <AnimatePresence mode="wait" onExitComplete={() => window.scrollTo({ top: 0, left: 0, behavior: "instant" })}>
          <motion.main key={section} className="main" variants={pageVariants} initial="initial" animate="enter" exit="exit">
            <Routes location={location}>
              <Route path="/" element={<Overview />} />
              <Route path="/workloads" element={<Workloads />} />
              <Route path="/campaigns" element={<Campaigns />} />
              <Route path="/results" element={<Results />} />
              <Route path="/results/:campaignId" element={<Results />} />
              <Route path="/results/:campaignId/:studyId" element={<Results />} />
              <Route path="/recommendations" element={<Recommendations />} />
              <Route path="/protocol" element={<Protocol />} />
              <Route path="/protocol/:slug" element={<Protocol />} />
              <Route path="/roadmap" element={<RoadmapPage />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
            <Footer />
          </motion.main>
        </AnimatePresence>
      </div>
    </MotionConfig>
  );
}
