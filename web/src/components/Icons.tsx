import type { ReactElement, SVGProps } from "react";

/* Custom outline icons in the same 24px / 1.5 stroke style as Heroicons (used for everything else). */

const base = {
  width: 24, height: 24, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor",
  strokeWidth: 1.5, strokeLinecap: "round" as const, strokeLinejoin: "round" as const, "aria-hidden": true,
};

/** The kit's button glyph: a sprout held in a hand. */
export function PlantHandIcon(p: SVGProps<SVGSVGElement>) {
  return (
    <svg {...base} {...p}>
      <path d="M12 12.5V8.2" />
      <path d="M12 9C9.4 9 7.6 7.2 7.6 4.6 10.2 4.6 12 6.4 12 9Z" />
      <path d="M12 8.2c0-2.4 1.8-4.2 4.2-4.2 0 2.4-1.8 4.2-4.2 4.2Z" />
      <path d="M2.8 14.6h2.6l3.4 2.2h4.4a1.3 1.3 0 0 0 0-2.6h-2.6" />
      <path d="M5.4 20.2h8.4l6.1-4.4a1.5 1.5 0 0 0-1.9-2.3l-3.6 2.4" />
    </svg>
  );
}

export function JoinIcon(p: SVGProps<SVGSVGElement>) {
  return (
    <svg {...base} {...p}>
      <path d="M5 4v3.5a4.5 4.5 0 0 0 4.5 4.5H12" />
      <path d="M19 4v3.5a4.5 4.5 0 0 1-4.5 4.5H12" />
      <path d="M12 12v8" />
      <path d="m9 17 3 3 3-3" />
    </svg>
  );
}

export function SigmaIcon(p: SVGProps<SVGSVGElement>) {
  return (
    <svg {...base} {...p}>
      <path d="M17.5 5H6.5l6 7-6 7h11" />
    </svg>
  );
}

export function TreeIndexIcon(p: SVGProps<SVGSVGElement>) {
  return (
    <svg {...base} {...p}>
      <rect x="9" y="3" width="6" height="4" rx="1" />
      <rect x="3" y="15" width="6" height="4" rx="1" />
      <rect x="15" y="15" width="6" height="4" rx="1" />
      <path d="M12 7v4M6 15v-2h12v2" />
    </svg>
  );
}

export function SearchTextIcon(p: SVGProps<SVGSVGElement>) {
  return (
    <svg {...base} {...p}>
      <path d="M4 6h9M4 10h6M4 14h4" />
      <circle cx="15.5" cy="14.5" r="3.5" />
      <path d="m18 17 2.5 2.5" />
    </svg>
  );
}

export const WORKLOAD_ICONS: Record<string, (p: SVGProps<SVGSVGElement>) => ReactElement> = {
  join: JoinIcon,
  search: SearchTextIcon,
  stream: SigmaIcon,
  index: TreeIndexIcon,
};
