import { animate, useInView, useReducedMotion, type Variants } from "motion/react";
import { useEffect, useRef, useState } from "react";

export const EASE = [0.22, 1, 0.36, 1] as const;

/** Whole-page transition: the old page lifts away, the new one rises into place. */
export const pageVariants: Variants = {
  initial: { opacity: 0, y: 22 },
  enter: { opacity: 1, y: 0, transition: { duration: 0.6, ease: EASE } },
  exit: { opacity: 0, y: -14, transition: { duration: 0.26, ease: [0.4, 0, 1, 1] } },
};

/** Props for an element that fades up the first time it scrolls into view. The blur is dropped at the end:
    a lingering filter would cut glass panels inside off from the sky they blur. */
export function reveal(delay = 0, y = 26) {
  return {
    initial: { opacity: 0, y, filter: "blur(6px)" },
    whileInView: { opacity: 1, y: 0, filter: "blur(0px)", transitionEnd: { filter: "none" } },
    viewport: { once: true, margin: "0px 0px -60px 0px" },
    transition: { duration: 0.75, ease: EASE, delay },
  } as const;
}

/** Same, but on mount (for the first screen of a page). */
export function rise(delay = 0, y = 18) {
  return {
    initial: { opacity: 0, y, filter: "blur(6px)" },
    animate: { opacity: 1, y: 0, filter: "blur(0px)", transitionEnd: { filter: "none" } },
    transition: { duration: 0.75, ease: EASE, delay },
  } as const;
}

/** A number that counts up from its previous value the first time it is seen. */
export function CountUp({ value, format, duration = 1.6 }: { value: number; format: (v: number) => string; duration?: number }) {
  const ref = useRef<HTMLSpanElement>(null);
  const inView = useInView(ref, { once: true, margin: "-40px" });
  const reduce = useReducedMotion();
  const from = useRef(0);
  const [shown, setShown] = useState(reduce ? value : 0);
  useEffect(() => {
    if (!inView) return;
    if (reduce) {
      setShown(value);
      return;
    }
    const controls = animate(from.current, value, { duration, ease: EASE, onUpdate: setShown });
    from.current = value;
    return () => controls.stop();
  }, [inView, value, reduce, duration]);
  return <span ref={ref} className="num">{format(shown)}</span>;
}

/** Feed the pointer position to `.spot` cards (as --mx/--my) for their spotlight and border glow. */
export function useSpotlight() {
  useEffect(() => {
    const move = (e: PointerEvent) => {
      const el = (e.target as Element | null)?.closest?.(".spot") as HTMLElement | null;
      if (!el) return;
      const r = el.getBoundingClientRect();
      el.style.setProperty("--mx", `${e.clientX - r.left}px`);
      el.style.setProperty("--my", `${e.clientY - r.top}px`);
    };
    document.addEventListener("pointermove", move, { passive: true });
    return () => document.removeEventListener("pointermove", move);
  }, []);
}
