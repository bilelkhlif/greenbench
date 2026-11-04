"""Text search: keyword queries (1-2 terms, AND) over support tickets.

Variants: a regular-expression full scan vs an inverted index built on the fly. The
`n_queries` knob exposes the build-cost / query-cost trade-off: the index costs more up
front and pays off once enough queries share it.
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pyarrow.compute as pc

from greenbench.data.generate import SCHEMAS
from greenbench.data.storage import DEFAULT_STORAGE, STORAGES, read_table, table_path
from greenbench.workloads.base import Result, RunContext, Variant, Workload


def _pack(per_query: list[np.ndarray], doc_ids: np.ndarray) -> Result:
    offsets = np.zeros(len(per_query) + 1, dtype=np.int64)
    offsets[1:] = np.cumsum([a.size for a in per_query])
    ids = np.concatenate(per_query) if per_query else np.empty(0, np.int64)
    return {"offsets": offsets, "doc_ids": doc_ids[ids].astype(np.int64)}


class TextSearch(Workload):
    name = "text_search"
    title = "Text search"
    summary = "Keyword queries over support tickets"
    description = ("Boolean keyword search (one or two terms joined by AND) over a corpus of support "
                   "tickets with a Zipf-distributed vocabulary. Queries mix common, mid-frequency and rare "
                   "terms; every variant returns the exact same sorted document lists.")
    icon = "search"
    inputs = ("documents",)
    variants = {
        "regex_scan": Variant("regex_scan", "Full scan (regex)",
                              "Scan the whole corpus with a compiled word-boundary regex for each query term."),
        "inverted_index": Variant("inverted_index", "Inverted index",
                                  "Tokenise once, build term → posting lists, answer queries by intersection."),
    }
    knobs = {"n_queries": [1, 10, 100], "storage": list(STORAGES)}
    defaults = {"n_queries": 10, "storage": DEFAULT_STORAGE}
    result_knobs = ("n_queries",)
    reference_variant = "inverted_index"
    phases = ("load", "build", "query")

    def prepare(self, data_dir: Path, meta: dict, params: dict) -> dict:
        vocab = meta["vocabulary"]
        queries = [[vocab[r] for r in q] for q in meta["text_queries"][: int(params["n_queries"])]]
        return {"path": table_path(data_dir, "documents", params["storage"]), "queries": queries}

    def run(self, variant: str, params: dict, ctx: RunContext, prep: dict) -> Result:
        with ctx.phase("load"):
            tbl = read_table(prep["path"], params["storage"], SCHEMAS["documents"], ["doc_id", "text"])
            texts = tbl.column("text")
            doc_ids = tbl.column("doc_id").to_numpy()
        if variant == "regex_scan":
            return self._scan(texts, doc_ids, prep["queries"], ctx)
        return self._index(texts, doc_ids, prep["queries"], ctx)

    def _scan(self, texts, doc_ids, queries, ctx: RunContext) -> Result:
        with ctx.phase("build"):
            docs = texts.to_pylist()
            corpus = "\n".join(docs)
            starts = np.zeros(len(docs), dtype=np.int64)
            starts[1:] = np.cumsum([len(d) + 1 for d in docs[:-1]])
        with ctx.phase("query"):
            out = []
            for terms in queries:
                hits = None
                for term in terms:
                    pattern = re.compile(r"\b" + re.escape(term) + r"\b")
                    pos = np.fromiter((m.start() for m in pattern.finditer(corpus)), dtype=np.int64)
                    docs_hit = np.unique(np.searchsorted(starts, pos, side="right") - 1)
                    hits = docs_hit if hits is None else np.intersect1d(hits, docs_hit, assume_unique=True)
                out.append(hits)
        return _pack(out, doc_ids)

    def _index(self, texts, doc_ids, queries, ctx: RunContext) -> Result:
        with ctx.phase("build"):
            tokens = pc.split_pattern(texts, pattern=" ")
            lengths = pc.list_value_length(tokens).to_numpy()
            enc = pc.dictionary_encode(pc.list_flatten(tokens)).combine_chunks()
            term_ids = enc.indices.to_numpy(zero_copy_only=False).astype(np.int64)
            dictionary = {t: i for i, t in enumerate(enc.dictionary.to_pylist())}
            n_docs = lengths.size
            doc_of_token = np.repeat(np.arange(n_docs, dtype=np.int64), lengths)
            keys = np.unique(term_ids * n_docs + doc_of_token)  # sorted, deduplicated (term, doc) pairs
            post_terms, post_docs = keys // n_docs, keys % n_docs
            offsets = np.searchsorted(post_terms, np.arange(len(dictionary) + 1))
        with ctx.phase("query"):
            out = []
            empty = np.empty(0, dtype=np.int64)
            for terms in queries:
                hits = None
                for term in terms:
                    t = dictionary.get(term)
                    plist = empty if t is None else post_docs[offsets[t]:offsets[t + 1]]
                    hits = plist if hits is None else np.intersect1d(hits, plist, assume_unique=True)
                out.append(hits)
        return _pack(out, doc_ids)

    def summary_of(self, result: Result) -> dict:
        counts = np.diff(result["offsets"])
        return {"queries": int(counts.size), "total_hits": int(counts.sum()),
                "median_hits": float(np.median(counts)) if counts.size else 0.0}
