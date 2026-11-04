import { CheckIcon } from "@heroicons/react/24/outline";
import { motion, useInView } from "motion/react";
import { useEffect, useId, useRef, type ReactNode } from "react";
import { EASE, reveal, rise } from "./motion";

/** Page header: mono section label, display title revealed word by word, dim subtitle. */
export function PageHeader({ eyebrow, title, description, actions }: {
  eyebrow?: string; title: string; description?: ReactNode; actions?: ReactNode;
}) {
  const words = title.split(" ");
  return (
    <header className="page-hero">
      <div className="page-hero-copy">
        {eyebrow && <motion.div className="eyebrow" {...rise(0.05, 10)}>{eyebrow}</motion.div>}
        <h1 className="display-s page-title" aria-label={title}>
          {words.map((w, i) => (
            <span key={i} aria-hidden="true">
              <span className="word-mask">
                <motion.span className="word grad-text" initial={{ y: "110%" }} animate={{ y: 0 }}
                  transition={{ duration: 0.85, ease: EASE, delay: 0.12 + i * 0.07 }}>{w}</motion.span>
              </span>
              {i < words.length - 1 ? " " : ""}
            </span>
          ))}
        </h1>
        {description && <motion.p className="body-l" {...rise(0.3)}>{description}</motion.p>}
      </div>
      {actions && <motion.div className="actions" {...rise(0.4)}>{actions}</motion.div>}
    </header>
  );
}

/** Section head inside a page: label, title, optional subtitle and action; fades up when reached. */
export function SectionHead({ eyebrow, title, sub, action }: { eyebrow: string; title: ReactNode; sub?: ReactNode; action?: ReactNode }) {
  return (
    <motion.div className="section-head" {...reveal()}>
      <div>
        <div className="eyebrow">{eyebrow}</div>
        <h2 className="headline-l">{title}</h2>
        {sub && <p className="body-m">{sub}</p>}
      </div>
      {action}
    </motion.div>
  );
}

export function LinearProgress({ label, value, info, right, done }: {
  label?: ReactNode; value: number; info?: ReactNode; right?: ReactNode; done?: boolean;
}) {
  const pct = Math.max(0, Math.min(1, value)) * 100;
  const ref = useRef<HTMLDivElement>(null);
  const seen = useInView(ref, { once: true, margin: "-30px" });
  return (
    <div className="progress">
      {label !== undefined && <div className="head label-l"><span>{label}</span></div>}
      <div ref={ref} className="track" role="progressbar" aria-valuenow={Math.round(pct)} aria-valuemin={0} aria-valuemax={100}>
        <motion.div className={`fill${done ? " done" : ""}`} initial={{ width: 0 }} animate={{ width: seen ? `${pct}%` : 0 }}
          transition={{ duration: 1.2, ease: EASE, delay: 0.1 }} />
      </div>
      {(info !== undefined || right !== undefined) && (
        <div className="info body-s"><span>{info}</span><span className="num">{right ?? `${Math.round(pct)}%`}</span></div>
      )}
    </div>
  );
}

export function CircularProgress({ value, size = 120, stroke = 12, children }: {
  value: number; size?: number; stroke?: number; children?: ReactNode;
}) {
  const id = `ring${useId().replace(/[^a-zA-Z0-9_-]/g, "")}`;
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const v = Math.max(0, Math.min(1, value));
  return (
    <div style={{ position: "relative", width: size, height: size }}>
      <svg width={size} height={size} role="progressbar" aria-valuenow={Math.round(v * 100)} style={{ overflow: "visible" }}>
        <defs>
          <linearGradient id={id} x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor="#9af3e2" />
            <stop offset="1" stopColor="#199e70" />
          </linearGradient>
        </defs>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="rgba(255,255,255,0.07)" strokeWidth={stroke} />
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={`url(#${id})`} strokeWidth={stroke}
          strokeDasharray={`${c * v} ${c}`} strokeLinecap="round" transform={`rotate(-90 ${size / 2} ${size / 2})`}
          style={{ transition: "stroke-dasharray 600ms var(--ease-out)", filter: "drop-shadow(0 0 8px rgba(100,220,200,0.55))" }} />
      </svg>
      <div style={{ position: "absolute", inset: 0, display: "grid", placeItems: "center", textAlign: "center" }}>{children}</div>
    </div>
  );
}

export function Checkbox({ checked, onChange, title, description }: {
  checked: boolean; onChange: (v: boolean) => void; title: ReactNode; description?: ReactNode;
}) {
  return (
    <label className={`check${checked ? " selected" : ""}`}>
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      <span className="box"><CheckIcon strokeWidth={3} /></span>
      <span className="text"><span className="label-l">{title}</span>{description && <span className="body-s">{description}</span>}</span>
    </label>
  );
}

export function Radio({ name, checked, onChange, title, description }: {
  name: string; checked: boolean; onChange: () => void; title: ReactNode; description?: ReactNode;
}) {
  return (
    <label className={`check${checked ? " selected" : ""}`}>
      <input type="radio" name={name} checked={checked} onChange={onChange} />
      <span className="radio" />
      <span className="text"><span className="label-l">{title}</span>{description && <span className="body-s">{description}</span>}</span>
    </label>
  );
}

const SLIDE = { type: "spring", stiffness: 420, damping: 36 } as const;

/** Pill buttons sharing one glass indicator that slides to the chosen option. */
export function Segmented<T extends string>({ options, value, onChange, label }: {
  options: { value: T; label: ReactNode }[]; value: T; onChange: (v: T) => void; label: string;
}) {
  const id = useId();
  return (
    <div className="segmented" role="group" aria-label={label}>
      {options.map((o) => (
        <button key={o.value} type="button" aria-pressed={o.value === value} onClick={() => onChange(o.value)}>
          {o.value === value && <motion.span layoutId={`seg${id}`} className="seg-active" transition={SLIDE} />}
          <span className="seg-label">{o.label}</span>
        </button>
      ))}
    </div>
  );
}

/** Tabs with the same sliding indicator. On narrow screens the row scrolls sideways, kept centred on the active tab. */
export function Tabs({ items, value, onChange, label }: {
  items: { id: string; label: ReactNode; disabled?: boolean }[]; value: string; onChange: (id: string) => void; label: string;
}) {
  const id = useId();
  const row = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = row.current;
    const active = el?.querySelector<HTMLElement>('[aria-selected="true"]');
    if (el && active && el.scrollWidth > el.clientWidth) {
      el.scrollTo({ left: active.offsetLeft - (el.clientWidth - active.offsetWidth) / 2, behavior: "smooth" });
    }
  }, [value]);
  return (
    <div ref={row} className="tabs" role="tablist" aria-label={label}>
      {items.map((t) => (
        <button key={t.id} type="button" role="tab" aria-selected={value === t.id} disabled={t.disabled}
          className={`tab${value === t.id ? " active" : ""}`} onClick={() => onChange(t.id)}>
          {value === t.id && <motion.span layoutId={`tab${id}`} className="seg-active" transition={SLIDE} />}
          <span className="seg-label">{t.label}</span>
        </button>
      ))}
    </div>
  );
}

export function StatTile({ label, value, note, delay = 0 }: { label: string; value: ReactNode; note?: ReactNode; delay?: number }) {
  return (
    <motion.div className="card spot stat-tile" {...reveal(delay)}>
      <div className="stat-label">{label}</div>
      <div className="stat-value grad-text">{value}</div>
      {note && <div className="stat-note">{note}</div>}
    </motion.div>
  );
}

export function Skeleton({ height = 120 }: { height?: number }) {
  return <div className="skeleton" style={{ height }} />;
}
