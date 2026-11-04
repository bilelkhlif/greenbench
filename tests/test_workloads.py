import numpy as np
import pytest

from greenbench.data.generate import load_meta
from greenbench.workloads import WORKLOADS
from greenbench.workloads.base import RunContext, accuracy, checksum
from greenbench.workloads.hashing import HashTable
from greenbench.workloads.indexing import StaticBPlusTree


def _cases():
    for w in WORKLOADS.values():
        grids = [{"n_queries": n} for n in w.knobs["n_queries"]] if "n_queries" in w.knobs else [{}]
        for g in grids:
            for extra in ({}, {"storage": "csv"}, {"storage": "json-zstd"}, {"threads": 4}):
                if "threads" in extra and "threads" not in w.knobs:
                    continue
                yield pytest.param(w.name, {**g, **extra}, id=f"{w.name}-{g}-{extra}")


@pytest.mark.parametrize("name,overrides", list(_cases()))
def test_every_variant_matches_the_reference(tiny_dir, name, overrides):
    w = WORKLOADS[name]
    params = w.params(overrides)
    if hasattr(w, "ensure_inputs"):
        w.ensure_inputs(tiny_dir, params)
    prep = w.prepare(tiny_dir, load_meta(tiny_dir), params)
    ref = w.run(w.reference_variant, w.params({k: params[k] for k in w.result_knobs}), RunContext(),
                w.prepare(tiny_dir, load_meta(tiny_dir), w.params({k: params[k] for k in w.result_knobs})))
    for variant, spec in w.variants.items():
        if w.applicable(variant, params):
            continue
        ctx = RunContext()
        res = w.run(variant, params, ctx, prep)
        assert [p.name for p in ctx.phases][0] == "load"
        if spec.exact:
            assert checksum(res) == checksum(ref), f"{name}/{variant} differs from the reference"
        else:
            errors = accuracy(res, ref)
            assert errors, "approximate variants must be scored"


def test_hll_error_is_small(tiny_dir):
    w = WORKLOADS["streaming"]
    p = w.params()
    prep = w.prepare(tiny_dir, load_meta(tiny_dir), p)
    acc = accuracy(w.run("approx_hll", p, RunContext(), prep), w.run("incremental", p, RunContext(), prep))
    assert acc["count"]["mape"] == 0.0 and acc["value_sum"]["mape"] == 0.0
    assert acc["distinct_users"]["mape"] < 0.05  # HLL p=10: ~3 % standard error


def test_hash_table_against_dict():
    rng = np.random.default_rng(1)
    keys = np.unique(rng.integers(1, 2**60, 50_000))
    rng.shuffle(keys)
    table = HashTable(keys)
    probe = np.concatenate([keys[::3], rng.integers(2**61, 2**62, 1_000)])
    expected = {k: i for i, k in enumerate(keys.tolist())}
    got = table.lookup(probe)
    assert got.tolist() == [expected.get(k, -1) for k in probe.tolist()]


@pytest.mark.parametrize("n", [1, 63, 64, 65, 4_097, 300_000])
def test_bplus_tree_lower_bound_matches_searchsorted(n):
    rng = np.random.default_rng(n)
    keys = np.unique(rng.integers(0, 10 * n + 10, n + 5))[:n]
    tree = StaticBPlusTree(rng.permutation(keys), np.arange(keys.size))
    q = rng.integers(-5, 10 * n + 20, 5_000)
    assert np.array_equal(tree.lower_bound(q), np.searchsorted(np.sort(keys), q))
