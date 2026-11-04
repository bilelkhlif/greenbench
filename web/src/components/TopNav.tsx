import {
  BeakerIcon, Bars3Icon, BoltIcon, ChartBarIcon, DocumentTextIcon, HomeIcon, LightBulbIcon, MapIcon, XMarkIcon,
} from "@heroicons/react/24/outline";
import { AnimatePresence, motion } from "motion/react";
import { useEffect, useState } from "react";
import { Link, NavLink, useLocation } from "react-router-dom";
import { useApi } from "../api";
import type { CampaignSummary, Roadmap } from "../types";
import { LogoMark } from "./Logo";
import { EASE } from "./motion";

const ITEMS = [
  { to: "/", label: "Overview", icon: HomeIcon, end: true },
  { to: "/workloads", label: "Workloads", icon: BeakerIcon },
  { to: "/campaigns", label: "Campaigns", icon: BoltIcon },
  { to: "/results", label: "Results", icon: ChartBarIcon },
  { to: "/recommendations", label: "Insights", icon: LightBulbIcon },
  { to: "/protocol", label: "Protocol", icon: DocumentTextIcon },
  { to: "/roadmap", label: "Roadmap", icon: MapIcon },
];

export function TopNav({ running }: { running?: CampaignSummary }) {
  const { pathname } = useLocation();
  const { data: roadmap } = useApi<Roadmap>("/roadmap");
  const [open, setOpen] = useState(false);
  const [scrolled, setScrolled] = useState(false);
  useEffect(() => setOpen(false), [pathname]);
  useEffect(() => {
    const on = () => setScrolled(window.scrollY > 8);
    on();
    window.addEventListener("scroll", on, { passive: true });
    return () => window.removeEventListener("scroll", on);
  }, []);
  const s = running?.status;
  const week = roadmap?.current_week;

  return (
    <header className={`topbar${scrolled ? " scrolled" : ""}`}>
      <motion.nav className="nav-shell" aria-label="Main" initial={{ y: -30, opacity: 0 }} animate={{ y: 0, opacity: 1 }}
        transition={{ duration: 0.8, ease: EASE }}>
        <Link to="/" className="brand" aria-label="GreenBench AI home">
          <LogoMark size={32} />
          <span className="wordmark">GreenBench <em>AI</em></span>
        </Link>
        <div className="nav-links">
          {ITEMS.map(({ to, label, end }, i) => (
            <NavLink key={to} to={to} end={end} className={({ isActive }) => `nav-link${isActive ? " active" : ""}`}>
              {({ isActive }) => (
                <>
                  {isActive && (
                    <motion.span layoutId="nav-active" className="nav-active" transition={{ type: "spring", stiffness: 380, damping: 34 }} />
                  )}
                  <span className="nav-num">{String(i + 1).padStart(2, "0")}</span>
                  <span className="nav-label">{label}</span>
                  {to === "/campaigns" && running && <span className="nav-badge" aria-label="campaign running" />}
                </>
              )}
            </NavLink>
          ))}
        </div>
        {s ? (
          <Link to="/campaigns" className="nav-status running">
            <span className="status-dot" style={{ color: "var(--amber)" }} />
            measuring <b>{s.total ? Math.round(((s.done ?? 0) / s.total) * 100) : 0}%</b>
          </Link>
        ) : week ? (
          <Link to="/roadmap" className="nav-status">
            <span className="status-dot" style={{ color: "var(--mint)" }} />
            week <b>{week}</b> / 12
          </Link>
        ) : null}
        <button type="button" className="nav-burger" aria-expanded={open} aria-label={open ? "Close menu" : "Open menu"} onClick={() => setOpen(!open)}>
          {open ? <XMarkIcon /> : <Bars3Icon />}
        </button>
      </motion.nav>
      <AnimatePresence>
        {open && (
          <motion.div className="nav-sheet" initial={{ opacity: 0, y: -12, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -10, scale: 0.98 }} transition={{ duration: 0.3, ease: EASE }}>
            {ITEMS.map(({ to, label, icon: Icon, end }, i) => (
              <motion.div key={to} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.04 * i, duration: 0.3, ease: EASE }}>
                <NavLink to={to} end={end} className={({ isActive }) => `sheet-link${isActive ? " active" : ""}`}>
                  <Icon /> {label}
                  {to === "/campaigns" && running && <span className="nav-badge" aria-label="campaign running" />}
                </NavLink>
              </motion.div>
            ))}
          </motion.div>
        )}
      </AnimatePresence>
    </header>
  );
}
