import { useCallback, useEffect, useRef, useState } from "react";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

/** True in the GitHub Pages build: data comes from the JSON snapshot next to the app, nothing can be launched. */
export const STATIC = import.meta.env.VITE_STATIC === "1";
/** Repository link, set by the Pages build. */
export const REPO_URL: string | undefined = import.meta.env.VITE_REPO_URL || undefined;

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  if (STATIC && init?.method && init.method !== "GET") {
    throw new ApiError(405, "This hosted copy is read-only: campaigns run on your own machine (greenbench serve).");
  }
  const res = await fetch(STATIC ? `${import.meta.env.BASE_URL}data${path}.json` : `/api${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* keep statusText */
    }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

/* Last response per path. Pages render from it at once, so a page transition shows real content
   instead of a skeleton, then refresh in the background. */
const cache = new Map<string, unknown>();

export async function prefetch(paths: string[]): Promise<void> {
  await Promise.all(paths.filter((p) => !cache.has(p)).map((p) => api(p).then((d) => cache.set(p, d)).catch(() => undefined)));
}

/** Fetch on mount (and when `path` changes); optionally poll. Serves the cached copy while refetching. */
export function useApi<T>(path: string | null, pollMs?: number) {
  const [data, setData] = useState<T | null>(() => (path ? ((cache.get(path) as T) ?? null) : null));
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(Boolean(path) && !(path && cache.has(path)));
  const alive = useRef(true);

  const load = useCallback(async () => {
    if (!path) return;
    try {
      const d = await api<T>(path);
      cache.set(path, d);
      if (alive.current) {
        setData(d);
        setError(null);
      }
    } catch (e) {
      if (alive.current) setError(e instanceof ApiError ? e : new ApiError(0, String(e)));
    } finally {
      if (alive.current) setLoading(false);
    }
  }, [path]);

  useEffect(() => {
    alive.current = true;
    const hit = path ? (cache.get(path) as T | undefined) : undefined;
    if (hit !== undefined) setData(hit);
    setLoading(Boolean(path) && hit === undefined);
    load();
    if (!pollMs || !path || STATIC) return () => { alive.current = false; };
    const id = window.setInterval(load, pollMs);
    return () => {
      alive.current = false;
      window.clearInterval(id);
    };
  }, [load, path, pollMs]);

  return { data, error, loading, reload: load };
}
