import { useId } from "react";

/** GreenBench mark: a leaf in a glowing mint disc with an amber energy badge. */
export function LogoMark({ size = 44 }: { size?: number }) {
  const id = `logo${useId().replace(/[^a-zA-Z0-9_-]/g, "")}`;
  return (
    <svg width={size} height={size} viewBox="0 0 48 48" role="img" aria-label="GreenBench AI">
      <defs>
        <linearGradient id={id} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#9af3e2" />
          <stop offset="1" stopColor="#199e70" />
        </linearGradient>
      </defs>
      <circle cx="22" cy="22" r="21" fill={`url(#${id})`} />
      <path d="M11.5 31.5C11.5 19.5 19 12.5 32 12.5c0 12.5-7.5 19-20.5 19Z" fill="#04211c" />
      <path d="M11.5 31.5 24.5 19.5" stroke="#64dcc8" strokeWidth="2.2" strokeLinecap="round" />
      <circle cx="36" cy="36" r="10" fill="#f5b544" stroke="#05080d" strokeWidth="2.5" />
      <path d="M37.6 29.8 32.4 37h4.1l-1.4 5.2 5.4-7.4h-4.2l1.3-5Z" fill="#04211c" />
    </svg>
  );
}
