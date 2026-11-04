"""Deterministic synthetic multi-source datasets.

Five tables model a small data platform fed by several sources:

* customers  (CRM database)        - dimension table, unique customer_id
* orders     (API + files + DB)    - fact table, 3 % orphan keys, `source` column
* documents  (support tickets)     - free text with a Zipf vocabulary
* events     (IoT / click stream)  - one day of time-ordered events
* kv         (key-value store)     - unique keys + payload, for indexing

The same seed always produces byte-identical canonical tables, so every machine
benchmarks exactly the same data.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pyarrow as pa

from greenbench.data.storage import DEFAULT_STORAGE, STORAGES, table_path, write_table
from greenbench.paths import datasets_dir

SEED = 20261104


@dataclass(frozen=True)
class Scale:
    customers: int
    orders: int
    docs: int
    events: int
    kv: int
    vocab: int = 20_000
    doc_words: int = 30
    users: int = 50_000
    regions: int = 16
    sensors: int = 2_000


SCALES = {
    "tiny": Scale(customers=2_000, orders=20_000, docs=1_000, events=60_000, kv=50_000, vocab=3_000, users=2_000),
    "small": Scale(customers=50_000, orders=500_000, docs=15_000, events=500_000, kv=500_000),
    "medium": Scale(customers=200_000, orders=2_000_000, docs=50_000, events=2_000_000, kv=2_000_000),
}

COUNTRIES = ["Tunisia", "France", "Germany", "Italy", "Spain", "Morocco", "Algeria", "Egypt", "Canada",
             "United States", "Brazil", "Mexico", "United Kingdom", "Netherlands", "Belgium", "Switzerland",
             "Sweden", "Norway", "Poland", "Portugal", "Turkey", "Japan", "South Korea", "India", "China",
             "Singapore", "Australia", "Nigeria", "Kenya", "South Africa"]
SEGMENTS = ["consumer", "small-business", "enterprise", "public-sector", "education"]
SOURCES = ["api", "csv-export", "crm-db", "event-stream"]

SCHEMAS = {
    "customers": pa.schema([("customer_id", pa.int64()), ("country", pa.string()), ("segment", pa.string()),
                            ("signup_year", pa.int16())]),
    "orders": pa.schema([("order_id", pa.int64()), ("customer_id", pa.int64()), ("amount_cents", pa.int64()),
                         ("ts", pa.int64()), ("source", pa.string())]),
    "documents": pa.schema([("doc_id", pa.int64()), ("text", pa.string())]),
    "events": pa.schema([("ts", pa.int64()), ("region", pa.int16()), ("sensor_id", pa.int32()),
                         ("user_id", pa.int32()), ("value_milli", pa.int64())]),
    "kv": pa.schema([("key", pa.int64()), ("payload", pa.int64())]),
}
TABLES = tuple(SCHEMAS)


def _zipf_probs(n: int, s: float) -> np.ndarray:
    w = 1.0 / np.arange(1, n + 1) ** s
    return w / w.sum()


def _unique_keys(rng: np.random.Generator, n: int, high: int) -> np.ndarray:
    keys = np.unique(rng.integers(1, high, size=int(n * 1.05) + 16, dtype=np.int64))
    while keys.size < n:
        keys = np.unique(np.concatenate([keys, rng.integers(1, high, size=n, dtype=np.int64)]))
    return rng.permutation(keys)[:n]


def _vocabulary(rng: np.random.Generator, n: int) -> list[str]:
    syllables = ["ba", "ce", "di", "fo", "gu", "ha", "je", "ki", "lo", "mu", "na", "pe", "qui", "ro", "su",
                 "ta", "ve", "wo", "xa", "yu", "zo", "tri", "pla", "str", "ion", "en", "ar", "ol", "ix", "um"]
    words: set[str] = set()
    out: list[str] = []
    while len(out) < n:
        k = int(rng.integers(1, 4))
        w = "".join(syllables[i] for i in rng.integers(0, len(syllables), size=k))
        if len(w) >= 3 and w not in words:
            words.add(w)
            out.append(w)
    return out


def generate_tables(scale: Scale, seed: int = SEED) -> tuple[dict[str, pa.Table], dict]:
    rng = np.random.default_rng(seed)
    tables: dict[str, pa.Table] = {}

    # customers
    cust_ids = _unique_keys(rng, scale.customers, 2**40)
    country_idx = rng.choice(len(COUNTRIES), size=scale.customers, p=_zipf_probs(len(COUNTRIES), 0.9))
    tables["customers"] = pa.table({
        "customer_id": cust_ids,
        "country": pa.array(np.array(COUNTRIES, dtype=object)[country_idx], pa.string()),
        "segment": pa.array(np.array(SEGMENTS, dtype=object)[rng.integers(0, len(SEGMENTS), scale.customers)],
                            pa.string()),
        "signup_year": rng.integers(2010, 2027, size=scale.customers).astype(np.int16),
    }, schema=SCHEMAS["customers"])

    # orders: popular customers order more; 3 % reference customers missing from the CRM
    popularity = rng.permutation(_zipf_probs(scale.customers, 0.6))
    order_cust = cust_ids[rng.choice(scale.customers, size=scale.orders, p=popularity)]
    orphans = rng.random(scale.orders) < 0.03
    order_cust[orphans] = rng.integers(2**40, 2**41, size=int(orphans.sum()), dtype=np.int64)
    amounts = np.clip(np.round(rng.lognormal(mean=8.1, sigma=0.9, size=scale.orders)), 50, 1_000_000)
    tables["orders"] = pa.table({
        "order_id": np.arange(1, scale.orders + 1, dtype=np.int64),
        "customer_id": order_cust,
        "amount_cents": amounts.astype(np.int64),
        "ts": np.sort(rng.integers(1_767_225_600, 1_798_761_600, size=scale.orders, dtype=np.int64)),
        "source": pa.array(np.array(SOURCES, dtype=object)[rng.choice(4, scale.orders, p=[.45, .2, .25, .1])],
                           pa.string()),
    }, schema=SCHEMAS["orders"])

    # documents: Zipf vocabulary, ~30 words per ticket
    vocab = _vocabulary(rng, scale.vocab)
    lengths = rng.poisson(scale.doc_words - 5, size=scale.docs) + 5
    word_ids = rng.choice(scale.vocab, size=int(lengths.sum()), p=_zipf_probs(scale.vocab, 1.07))
    vocab_arr = np.array(vocab, dtype=object)
    bounds = np.concatenate([[0], np.cumsum(lengths)])
    words = vocab_arr[word_ids]
    texts = [" ".join(words[bounds[i]:bounds[i + 1]]) for i in range(scale.docs)]
    tables["documents"] = pa.table({"doc_id": np.arange(scale.docs, dtype=np.int64),
                                    "text": pa.array(texts, pa.string())}, schema=SCHEMAS["documents"])

    # events: diurnal traffic over one day, time-ordered like an append-only log
    hours = rng.choice(24, size=scale.events, p=_diurnal())
    ts = np.sort(hours * 3600 + rng.integers(0, 3600, size=scale.events))
    users = rng.choice(scale.users, size=scale.events, p=_zipf_probs(scale.users, 0.8))
    tables["events"] = pa.table({
        "ts": ts.astype(np.int64),
        "region": rng.choice(scale.regions, size=scale.events, p=_zipf_probs(scale.regions, 0.7)).astype(np.int16),
        "sensor_id": rng.integers(0, scale.sensors, size=scale.events).astype(np.int32),
        "user_id": users.astype(np.int32),
        "value_milli": np.clip(rng.normal(20_000, 5_000, size=scale.events), 0, None).astype(np.int64),
    }, schema=SCHEMAS["events"])

    # kv
    tables["kv"] = pa.table({"key": _unique_keys(rng, scale.kv, 2**50),
                             "payload": rng.integers(0, 1_000_000, size=scale.kv, dtype=np.int64)},
                            schema=SCHEMAS["kv"])

    meta = {"seed": seed, "scale": asdict(scale), "vocabulary": vocab,
            "text_queries": _text_queries(np.random.default_rng(seed + 1), scale.vocab, 2_000)}
    return tables, meta


def _diurnal() -> np.ndarray:
    h = np.arange(24)
    w = 0.35 + np.exp(-((h - 14) ** 2) / 18.0) + 0.5 * np.exp(-((h - 20) ** 2) / 6.0)
    return w / w.sum()


def _text_queries(rng: np.random.Generator, vocab: int, n: int) -> list[list[int]]:
    """A fixed pool of keyword queries (vocabulary ranks). n_queries takes a prefix of the pool."""
    bands = [(10, min(200, vocab)), (min(200, vocab - 1), min(2_000, vocab)), (min(2_000, vocab - 1), vocab)]
    pool = []
    for _ in range(n):
        n_terms = 1 if rng.random() < 0.6 else 2
        terms = []
        for _ in range(n_terms):
            lo, hi = bands[int(rng.choice(3, p=[0.3, 0.45, 0.25]))]
            terms.append(int(rng.integers(lo, max(lo + 1, hi))))
        pool.append(sorted(set(terms)))
    return pool


def ensure_dataset(scale_name: str, needs: set[tuple[str, str]] | None = None, log=print) -> Path:
    """Generate the canonical dataset once, then derive the missing (table, storage) copies."""
    directory = datasets_dir(scale_name)
    meta_path = directory / "meta.json"
    if not meta_path.exists():
        directory.mkdir(parents=True, exist_ok=True)
        t0 = time.perf_counter()
        log(f"generating '{scale_name}' dataset (seed {SEED})...")
        tables, meta = generate_tables(SCALES[scale_name])
        for name, tbl in tables.items():
            write_table(tbl, table_path(directory, name, DEFAULT_STORAGE), DEFAULT_STORAGE)
        meta["rows"] = {name: tbl.num_rows for name, tbl in tables.items()}
        meta["generated_in_s"] = round(time.perf_counter() - t0, 1)
        meta_path.write_text(json.dumps(meta), encoding="utf-8")
        log(f"  done in {meta['generated_in_s']} s")
    for table, storage in sorted(needs or ()):
        ensure_storage(directory, table, storage, log)
    return directory


def ensure_storage(directory: Path, table: str, storage: str, log=print) -> Path:
    path = table_path(directory, table, storage)
    if not path.exists():
        import pyarrow.parquet as pq

        log(f"  writing {path.name}")
        canonical = pq.read_table(table_path(directory, table, DEFAULT_STORAGE))
        write_table(canonical, path, storage)
    return path


def load_meta(directory: Path) -> dict:
    return json.loads((directory / "meta.json").read_text(encoding="utf-8"))


def storage_sizes(directory: Path) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for table in TABLES:
        for storage in STORAGES:
            p = table_path(directory, table, storage)
            if p.exists():
                out.setdefault(table, {})[storage] = p.stat().st_size
    return out
