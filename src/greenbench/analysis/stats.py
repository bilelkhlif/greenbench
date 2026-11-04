"""Robust statistics for benchmark samples (small n, skewed, occasional outliers).

* medians with percentile-bootstrap 95 % confidence intervals
* ratio of medians (variant / baseline) with a bootstrap CI (independent resampling)
* Mann-Whitney U two-sided test (no normality assumption)
* Cliff's delta effect size, magnitude thresholds from Romano et al. (2006)
* Holm-Bonferroni correction across the comparisons of one study
"""

from __future__ import annotations

import numpy as np
from scipy import stats

N_BOOT = 4000


def describe(x: np.ndarray, rng: np.random.Generator) -> dict:
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    if x.size == 0:
        return {"n": 0}
    lo, hi = bootstrap_median_ci(x, rng)
    q1, q3 = np.percentile(x, [25, 75])
    mean = float(x.mean())
    std = float(x.std(ddof=1)) if x.size > 1 else 0.0
    return {"n": int(x.size), "median": float(np.median(x)), "ci_low": lo, "ci_high": hi, "mean": mean,
            "std": std, "cv": std / mean if mean else None, "q1": float(q1), "q3": float(q3),
            "min": float(x.min()), "max": float(x.max()), "values": [float(v) for v in x]}


def bootstrap_median_ci(x: np.ndarray, rng: np.random.Generator, alpha: float = 0.05) -> tuple[float, float]:
    if x.size < 2:
        v = float(x[0]) if x.size else float("nan")
        return v, v
    idx = rng.integers(0, x.size, size=(N_BOOT, x.size))
    meds = np.median(x[idx], axis=1)
    lo, hi = np.percentile(meds, [100 * alpha / 2, 100 * (1 - alpha / 2)])
    return float(lo), float(hi)


def ratio_of_medians(x: np.ndarray, base: np.ndarray, rng: np.random.Generator,
                     alpha: float = 0.05) -> tuple[float, float, float]:
    """median(x) / median(base) with a percentile-bootstrap CI."""
    x, base = np.asarray(x, float), np.asarray(base, float)
    point = float(np.median(x) / np.median(base))
    if x.size < 2 or base.size < 2:
        return point, point, point
    mx = np.median(x[rng.integers(0, x.size, size=(N_BOOT, x.size))], axis=1)
    mb = np.median(base[rng.integers(0, base.size, size=(N_BOOT, base.size))], axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        r = mx / mb
    r = r[np.isfinite(r)]
    lo, hi = np.percentile(r, [100 * alpha / 2, 100 * (1 - alpha / 2)])
    return point, float(lo), float(hi)


def mann_whitney_p(x: np.ndarray, y: np.ndarray) -> float:
    if len(x) < 2 or len(y) < 2:
        return float("nan")
    return float(stats.mannwhitneyu(x, y, alternative="two-sided").pvalue)


def cliffs_delta(x: np.ndarray, y: np.ndarray) -> float:
    """P(X > Y) - P(X < Y). Negative means x tends to be smaller (e.g. less energy)."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    if x.size == 0 or y.size == 0:
        return float("nan")
    diff = x[:, None] - y[None, :]
    return float((np.sign(diff)).mean())


def magnitude(delta: float) -> str:
    d = abs(delta)
    if not np.isfinite(d):
        return "n/a"
    if d < 0.147:
        return "negligible"
    if d < 0.33:
        return "small"
    if d < 0.474:
        return "medium"
    return "large"


def holm(pvalues: list[float]) -> list[float]:
    p = np.asarray(pvalues, dtype=float)
    out = np.full(p.size, np.nan)
    ok = np.flatnonzero(np.isfinite(p))
    if ok.size == 0:
        return out.tolist()
    order = ok[np.argsort(p[ok])]
    m = order.size
    running = 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (m - rank) * p[i]))
        out[i] = running
    return out.tolist()
