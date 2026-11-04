"""Streaming aggregation: sliding windows (5 min, sliding every minute) over one day of events.

Per window and region: event count, value sum and number of distinct users.

* batch_recompute   - recompute every window from scratch (each event is processed 5 times)
* incremental       - pane technique: per-minute partials, add the entering pane and retract
                      the leaving one; distinct users via exact add/remove multiset counts
* approx_hll        - incremental counts/sums, distinct users from mergeable HyperLogLog sketches
* approx_sampling   - consistent 10 % sample of users, every metric scaled up by 10
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from greenbench.data.generate import SCHEMAS
from greenbench.data.storage import DEFAULT_STORAGE, STORAGES, read_table, table_path
from greenbench.workloads.base import Result, RunContext, Variant, Workload

DAY, WINDOW, SLIDE = 86_400, 300, 60
PANES = DAY // SLIDE
PER_WINDOW = WINDOW // SLIDE
WINDOWS = PANES - PER_WINDOW + 1
HLL_BITS = 10
SAMPLE_RATE = 10


def splitmix64(x: np.ndarray) -> np.ndarray:
    z = x.astype(np.uint64) + np.uint64(0x9E3779B97F4A7C15)
    z = (z ^ (z >> np.uint64(30))) * np.uint64(0xBF58476D1CE4E5B9)
    z = (z ^ (z >> np.uint64(27))) * np.uint64(0x94D049BB133111EB)
    return z ^ (z >> np.uint64(31))


def bit_length(x: np.ndarray) -> np.ndarray:
    n = np.zeros(x.shape, dtype=np.int64)
    y = x.copy()
    for s in (32, 16, 8, 4, 2, 1):
        big = y >= (np.uint64(1) << np.uint64(s))
        n[big] += s
        y[big] >>= np.uint64(s)
    return n + (y > 0)


def sliding_pane_sums(pane_vals: np.ndarray) -> np.ndarray:
    """Window totals from per-pane partials using prefix sums (pane_vals: [PANES, R])."""
    prefix = np.vstack([np.zeros((1, pane_vals.shape[1]), dtype=pane_vals.dtype), np.cumsum(pane_vals, axis=0)])
    return prefix[PER_WINDOW:PER_WINDOW + WINDOWS] - prefix[:WINDOWS]


def pane_partials(pane: np.ndarray, region: np.ndarray, value: np.ndarray, regions: int):
    cell = pane * regions + region
    counts = np.bincount(cell, minlength=PANES * regions).reshape(PANES, regions)
    sums = np.bincount(cell, weights=value, minlength=PANES * regions).reshape(PANES, regions)
    return counts.astype(np.int64), sums


def incremental_distinct(pane: np.ndarray, region: np.ndarray, user: np.ndarray, regions: int,
                         users: int) -> np.ndarray:
    bounds = np.searchsorted(pane, np.arange(PANES + 1))
    multiplicity = np.zeros(regions * users, dtype=np.int32)
    current = np.zeros(regions, dtype=np.int64)
    out = np.zeros((WINDOWS, regions), dtype=np.int64)

    def cells(p):
        a, b = bounds[p], bounds[p + 1]
        return np.unique(region[a:b] * users + user[a:b], return_counts=True)

    def enter(p):
        u, c = cells(p)
        fresh = u[multiplicity[u] == 0]
        multiplicity[u] += c.astype(np.int32)
        current[:] += np.bincount(fresh // users, minlength=regions)

    def leave(p):
        u, c = cells(p)
        multiplicity[u] -= c.astype(np.int32)
        gone = u[multiplicity[u] == 0]
        current[:] -= np.bincount(gone // users, minlength=regions)

    for p in range(PER_WINDOW):
        enter(p)
    out[0] = current
    for w in range(1, WINDOWS):
        leave(w - 1)
        enter(w + PER_WINDOW - 1)
        out[w] = current
    return out


def hll_distinct(pane: np.ndarray, region: np.ndarray, user: np.ndarray, regions: int) -> np.ndarray:
    m = 1 << HLL_BITS
    h = splitmix64(user)
    reg_idx = (h >> np.uint64(64 - HLL_BITS)).astype(np.int64)
    rest = h << np.uint64(HLL_BITS)  # remaining hash bits, left-aligned
    # rank = leading zeros of the remaining bits + 1 (capped when they are all zero)
    rank = np.where(rest == 0, 64 - HLL_BITS + 1, 64 - bit_length(rest) + 1).astype(np.uint8)
    regs = np.zeros((PANES * regions, m), dtype=np.uint8)
    np.maximum.at(regs, (pane * regions + region, reg_idx), rank)
    regs = regs.reshape(PANES, regions, m)
    alpha = 0.7213 / (1 + 1.079 / m)
    pow2 = 2.0 ** -np.arange(66)
    out = np.zeros((WINDOWS, regions), dtype=np.float64)
    for start in range(0, WINDOWS, 128):
        stop = min(start + 128, WINDOWS)
        win = regs[start:stop].copy()
        for k in range(1, PER_WINDOW):  # sketches are mergeable: register-wise max over 5 panes
            np.maximum(win, regs[start + k:stop + k], out=win)
        raw = alpha * m * m / pow2[win].sum(axis=2)
        zeros = (win == 0).sum(axis=2)
        linear = np.where(zeros > 0, m * np.log(m / np.maximum(zeros, 1)), raw)
        out[start:stop] = np.where((raw <= 2.5 * m) & (zeros > 0), linear, raw)
    return out


class StreamingAggregation(Workload):
    name = "streaming"
    title = "Streaming aggregation"
    summary = "Sliding-window counts, sums and distinct users"
    description = ("One day of time-ordered sensor/click events aggregated into 5-minute windows that slide "
                   "every minute, per region: event count, value sum and distinct users. Exact variants "
                   "must return identical results; approximate ones are scored on their error.")
    icon = "stream"
    inputs = ("events",)
    variants = {
        "batch_recompute": Variant("batch_recompute", "Batch recompute",
                                   "Recompute each window from scratch: every event is aggregated 5 times."),
        "incremental": Variant("incremental", "Incremental panes",
                               "Per-minute partials; add the entering pane, retract the leaving one."),
        "approx_hll": Variant("approx_hll", "Incremental + HyperLogLog",
                              "Exact counts and sums; distinct users from mergeable HLL sketches (p=10).",
                              exact=False),
        "approx_sampling": Variant("approx_sampling", "10 % user sample",
                                   "Aggregate a consistent 10 % sample of users and scale every metric by 10.",
                                   exact=False),
    }
    knobs = {"storage": list(STORAGES)}
    defaults = {"storage": DEFAULT_STORAGE}
    reference_variant = "incremental"
    phases = ("load", "aggregate")

    def prepare(self, data_dir: Path, meta: dict, params: dict) -> dict:
        return {"path": table_path(data_dir, "events", params["storage"]),
                "regions": int(meta["scale"]["regions"]), "users": int(meta["scale"]["users"])}

    def run(self, variant: str, params: dict, ctx: RunContext, prep: dict) -> Result:
        regions, users = prep["regions"], prep["users"]
        with ctx.phase("load"):
            tbl = read_table(prep["path"], params["storage"], SCHEMAS["events"],
                             ["ts", "region", "user_id", "value_milli"])
            ts = tbl.column("ts").to_numpy()
            region = tbl.column("region").to_numpy().astype(np.int64)
            user = tbl.column("user_id").to_numpy().astype(np.int64)
            value = tbl.column("value_milli").to_numpy()
        with ctx.phase("aggregate"):
            if variant == "batch_recompute":
                return self._batch(ts, region, user, value, regions, users)
            if variant == "approx_sampling":
                keep = splitmix64(user) % np.uint64(SAMPLE_RATE) == 0
                ts, region, user, value = ts[keep], region[keep], user[keep], value[keep]
            pane = ts // SLIDE
            counts, sums = pane_partials(pane, region, value, regions)
            count = sliding_pane_sums(counts)
            total = np.rint(sliding_pane_sums(sums)).astype(np.int64)
            if variant == "approx_hll":
                distinct = hll_distinct(pane, region, user, regions)
                return {"count": count, "value_sum": total, "distinct_users": distinct}
            distinct = incremental_distinct(pane, region, user, regions, users)
            if variant == "approx_sampling":
                return {"count": count * float(SAMPLE_RATE), "value_sum": total * float(SAMPLE_RATE),
                        "distinct_users": distinct * float(SAMPLE_RATE)}
            return {"count": count, "value_sum": total, "distinct_users": distinct}

    def _batch(self, ts, region, user, value, regions, users) -> Result:
        starts = np.arange(WINDOWS, dtype=np.int64) * SLIDE
        lo = np.searchsorted(ts, starts)
        hi = np.searchsorted(ts, starts + WINDOW)
        count = np.zeros((WINDOWS, regions), dtype=np.int64)
        total = np.zeros((WINDOWS, regions), dtype=np.int64)
        distinct = np.zeros((WINDOWS, regions), dtype=np.int64)
        for w in range(WINDOWS):
            a, b = lo[w], hi[w]
            reg = region[a:b]
            count[w] = np.bincount(reg, minlength=regions)
            total[w] = np.rint(np.bincount(reg, weights=value[a:b], minlength=regions)).astype(np.int64)
            seen = np.unique(reg * users + user[a:b])
            distinct[w] = np.bincount(seen // users, minlength=regions)
        return {"count": count, "value_sum": total, "distinct_users": distinct}

    def summary_of(self, result: Result) -> dict:
        return {"windows": int(result["count"].shape[0]), "regions": int(result["count"].shape[1]),
                "peak_window_events": float(np.asarray(result["count"]).sum(axis=1).max())}
