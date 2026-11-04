"""Indexing: point lookups (80 % hits) plus a few range queries over a key-value table.

Variants: no index (full scans), a bulk-loaded B+-tree (fanout 64) and a hash index. Build
and query phases are measured separately, which gives the break-even number of queries
at which an index pays back its build energy. Hash indexes cannot answer range queries,
so they fall back to scans for those.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from greenbench.data.generate import SCHEMAS
from greenbench.data.storage import DEFAULT_STORAGE, STORAGES, read_table, table_path
from greenbench.workloads.base import Result, RunContext, Variant, Workload
from greenbench.workloads.hashing import HashTable

FANOUT = 64
INT64_MAX = np.iinfo(np.int64).max
SCAN_MAX_QUERIES = 2_000


def _blocks(sorted_keys: np.ndarray, fanout: int) -> np.ndarray:
    n_blocks = -(-sorted_keys.size // fanout)
    out = np.full(n_blocks * fanout, INT64_MAX, dtype=np.int64)
    out[:sorted_keys.size] = sorted_keys
    return out.reshape(n_blocks, fanout)


class StaticBPlusTree:
    """Bulk-loaded B+-tree: sorted leaves of `fanout` keys, separator levels above them."""

    def __init__(self, keys: np.ndarray, payload: np.ndarray, fanout: int = FANOUT):
        order = np.argsort(keys)
        self.keys = keys[order]
        self.payload = payload[order]  # covering index: leaves carry the payload
        self.fanout = fanout
        self.leaves = _blocks(self.keys, fanout)
        self.levels: list[np.ndarray] = []
        firsts = self.leaves[:, 0]
        while firsts.size > 1:
            self.levels.append(_blocks(firsts, fanout))
            firsts = self.levels[-1][:, 0]
        self.levels.reverse()  # root first

    @property
    def height(self) -> int:
        return len(self.levels) + 1

    def lower_bound(self, q: np.ndarray, chunk: int = 16_384) -> np.ndarray:
        """Position of the first key >= q, by descending from the root (node-local linear search)."""
        out = np.empty(q.size, dtype=np.int64)
        f = self.fanout
        for s in range(0, q.size, chunk):
            qq = q[s:s + chunk, None]
            node = np.zeros(qq.shape[0], dtype=np.int64)
            for level in self.levels:
                child = (level[node] <= qq).sum(axis=1) - 1
                node = node * f + np.maximum(child, 0)
            out[s:s + chunk] = node * f + (self.leaves[node] < qq).sum(axis=1)
        return out


class Indexing(Workload):
    name = "indexing"
    title = "Indexing"
    summary = "Point and range lookups on a key-value table"
    description = ("A key-value table with unique 64-bit keys answers a batch of point lookups (80 % of "
                   "keys exist) and range queries. The build phase (creating the index) and the query "
                   "phase are measured separately to expose the build-cost versus query-cost trade-off.")
    icon = "index"
    inputs = ("kv",)
    variants = {
        "scan": Variant("scan", "No index (full scan)", "Answer every query by scanning all keys."),
        "btree": Variant("btree", "B+-tree", "Bulk-load a B+-tree (fanout 64); descend it for each query."),
        "hash_index": Variant("hash_index", "Hash index",
                              "Open-addressing hash table on the key; ranges fall back to scans."),
    }
    knobs = {"n_queries": [1_000, 100_000], "storage": list(STORAGES)}
    defaults = {"n_queries": 1_000, "storage": DEFAULT_STORAGE}
    result_knobs = ("n_queries",)
    reference_variant = "btree"
    phases = ("load", "build", "query")

    def applicable(self, variant: str, params: dict) -> str | None:
        if variant == "scan" and int(params["n_queries"]) > SCAN_MAX_QUERIES:
            return f"full scans are capped at {SCAN_MAX_QUERIES:,} queries (minutes per run beyond that)"
        return None

    def query_file(self, data_dir: Path, n: int) -> Path:
        return data_dir / f"kv_queries_{n}.npz"

    def ensure_inputs(self, data_dir: Path, params: dict) -> None:
        """Write the query set once, outside any measurement (needs the existing keys)."""
        n = int(params["n_queries"])
        path = self.query_file(data_dir, n)
        if path.exists():
            return
        keys = read_table(table_path(data_dir, "kv", DEFAULT_STORAGE), DEFAULT_STORAGE, SCHEMAS["kv"],
                          ["key"]).column("key").to_numpy()
        rng = np.random.default_rng(n)
        n_hits = int(n * 0.8)
        hits = rng.choice(keys, size=n_hits, replace=n_hits > keys.size)
        misses = rng.integers(1, 2**50, size=n - hits.size, dtype=np.int64)
        points = rng.permutation(np.concatenate([hits, misses]))
        n_ranges = max(5, n // 200)
        width = int(100 * 2**50 / keys.size)  # about 100 keys per range
        lo = rng.integers(1, 2**50 - width, size=n_ranges, dtype=np.int64)
        np.savez(path, points=points, lo=lo, hi=lo + width)

    def prepare(self, data_dir: Path, meta: dict, params: dict) -> dict:
        q = np.load(self.query_file(data_dir, int(params["n_queries"])))
        return {"path": table_path(data_dir, "kv", params["storage"]),
                "points": q["points"], "lo": q["lo"], "hi": q["hi"]}

    def run(self, variant: str, params: dict, ctx: RunContext, prep: dict) -> Result:
        points, lo, hi = prep["points"], prep["lo"], prep["hi"]
        with ctx.phase("load"):
            tbl = read_table(prep["path"], params["storage"], SCHEMAS["kv"], ["key", "payload"])
            keys = tbl.column("key").to_numpy()
            payload = tbl.column("payload").to_numpy()
        point_out = np.full(points.size, -1, dtype=np.int64)
        r_count = np.zeros(lo.size, dtype=np.int64)
        r_sum = np.zeros(lo.size, dtype=np.int64)
        if variant == "btree":
            with ctx.phase("build"):
                tree = StaticBPlusTree(keys, payload)
            with ctx.phase("query"):
                pos = tree.lower_bound(points)
                pos_c = np.minimum(pos, tree.keys.size - 1)
                found = (pos < tree.keys.size) & (tree.keys[pos_c] == points)
                point_out[found] = tree.payload[pos_c[found]]
                a, b = tree.lower_bound(lo), tree.lower_bound(hi)
                r_count[:] = b - a
                for i in range(lo.size):  # leaf scan between the two bounds
                    r_sum[i] = tree.payload[a[i]:b[i]].sum()
        elif variant == "hash_index":
            with ctx.phase("build"):
                table = HashTable(keys)
            with ctx.phase("query"):
                rows = table.lookup(points)
                found = rows >= 0
                point_out[found] = payload[rows[found]]
                self._scan_ranges(keys, payload, lo, hi, r_count, r_sum)
        else:
            with ctx.phase("build"):
                pass  # nothing to build: that is the point of a scan
            with ctx.phase("query"):
                for i, q in enumerate(points):
                    hit = np.flatnonzero(keys == q)
                    if hit.size:
                        point_out[i] = payload[hit[0]]
                self._scan_ranges(keys, payload, lo, hi, r_count, r_sum)
        return {"point_payload": point_out, "range_count": r_count, "range_sum": r_sum}

    @staticmethod
    def _scan_ranges(keys, payload, lo, hi, r_count, r_sum) -> None:
        for i in range(lo.size):
            mask = (keys >= lo[i]) & (keys < hi[i])
            r_count[i] = int(mask.sum())
            r_sum[i] = int(payload[mask].sum())

    def summary_of(self, result: Result) -> dict:
        return {"point_hits": int((result["point_payload"] >= 0).sum()),
                "range_queries": int(result["range_count"].size),
                "keys_in_ranges": int(result["range_count"].sum())}
