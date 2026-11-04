"""Large-volume joins: revenue per country = orders JOIN customers ON customer_id, then GROUP BY country.

Variants: hash join vs sort-merge join. Knob `threads` > 1 switches to a radix-partitioned
version where partitions are joined concurrently (NumPy releases the GIL in its kernels).
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pyarrow.compute as pc

from greenbench.data.generate import SCHEMAS
from greenbench.data.storage import DEFAULT_STORAGE, STORAGES, read_table, table_path
from greenbench.workloads.base import Result, RunContext, Variant, Workload
from greenbench.workloads.hashing import HashTable, radix_partition


def hash_join(build: np.ndarray, probe: np.ndarray) -> np.ndarray:
    return HashTable(build).lookup(probe)


def sort_merge_join(build: np.ndarray, probe: np.ndarray) -> np.ndarray:
    b_order = np.argsort(build)
    b_sorted = build[b_order]
    p_order = np.argsort(probe)
    p_sorted = probe[p_order]
    # Merge step: both sides sorted, NumPy's search reuses its cursor for ascending needles.
    pos = np.searchsorted(b_sorted, p_sorted)
    pos_c = np.minimum(pos, max(b_sorted.size - 1, 0))
    hit = b_sorted[pos_c] == p_sorted
    out = np.full(probe.size, -1, dtype=np.int64)
    out[p_order[hit]] = b_order[pos_c[hit]]
    return out


def partitioned_join(build: np.ndarray, probe: np.ndarray, threads: int, algo) -> np.ndarray:
    parts = threads * 4
    b_rows, b_off = radix_partition(build, parts)
    p_rows, p_off = radix_partition(probe, parts)
    out = np.full(probe.size, -1, dtype=np.int64)

    def work(i: int) -> None:
        br = b_rows[b_off[i]:b_off[i + 1]]
        pr = p_rows[p_off[i]:p_off[i + 1]]
        if br.size == 0 or pr.size == 0:
            return
        local = algo(build[br], probe[pr])
        hit = local >= 0
        out[pr[hit]] = br[local[hit]]

    with ThreadPoolExecutor(max_workers=threads) as pool:
        list(pool.map(work, range(parts)))
    return out


class Joins(Workload):
    name = "joins"
    title = "Large-volume joins"
    summary = "Revenue per country: orders ⋈ customers, then group-by"
    description = ("A primary-key / foreign-key join between a large fact table (orders, from several "
                   "sources) and a dimension table (customers), followed by a group-by on country. "
                   "3 % of orders reference unknown customers and are dropped by the inner join.")
    icon = "join"
    inputs = ("orders", "customers")
    variants = {
        "hash": Variant("hash", "Hash join",
                        "Build an open-addressing hash table on customers, probe it with every order."),
        "sort_merge": Variant("sort_merge", "Sort-merge join",
                              "Sort both inputs on customer_id, then merge the sorted runs."),
    }
    knobs = {"threads": [1, 2, 4, 8], "storage": list(STORAGES)}
    defaults = {"threads": 1, "storage": DEFAULT_STORAGE}
    reference_variant = "hash"
    phases = ("load", "join", "aggregate")

    def prepare(self, data_dir: Path, meta: dict, params: dict) -> dict:
        s = params["storage"]
        return {"orders": table_path(data_dir, "orders", s), "customers": table_path(data_dir, "customers", s)}

    def run(self, variant: str, params: dict, ctx: RunContext, prep: dict) -> Result:
        threads, storage = int(params["threads"]), params["storage"]
        with ctx.phase("load"):
            orders = read_table(prep["orders"], storage, SCHEMAS["orders"], ["customer_id", "amount_cents"], threads)
            customers = read_table(prep["customers"], storage, SCHEMAS["customers"], ["customer_id", "country"],
                                   threads)
            o_key = orders.column("customer_id").to_numpy()
            amount = orders.column("amount_cents").to_numpy()
            c_key = customers.column("customer_id").to_numpy()
            enc = pc.dictionary_encode(customers.column("country")).combine_chunks()
            country_code = enc.indices.to_numpy(zero_copy_only=False)
            country_name = np.array(enc.dictionary.to_pylist())
        with ctx.phase("join"):
            algo = hash_join if variant == "hash" else sort_merge_join
            match = algo(c_key, o_key) if threads == 1 else partitioned_join(c_key, o_key, threads, algo)
        with ctx.phase("aggregate"):
            ok = match >= 0
            codes = country_code[match[ok]]
            counts = np.bincount(codes, minlength=country_name.size)
            sums = np.bincount(codes, weights=amount[ok], minlength=country_name.size)
        order = np.argsort(country_name)
        return {"country": country_name[order], "orders": counts[order].astype(np.int64),
                "revenue_cents": np.rint(sums[order]).astype(np.int64)}

    def summary_of(self, result: Result) -> dict:
        top = np.argsort(result["revenue_cents"])[::-1][:3]
        return {"matched_orders": int(result["orders"].sum()),
                "revenue": round(float(result["revenue_cents"].sum()) / 100, 2),
                "top_countries": [str(result["country"][i]) for i in top]}
