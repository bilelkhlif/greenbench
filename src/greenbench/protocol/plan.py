"""Experimental plan: studies (one question each), presets, and the randomised run schedule.

A study varies one or two factors of a workload around a baseline. Identical configurations
shared by several studies are measured once and reused.
"""

from __future__ import annotations

import itertools
import json
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np

from greenbench.data.storage import DEFAULT_STORAGE, STORAGE_LABELS, STORAGES
from greenbench.workloads import get


@dataclass(frozen=True)
class Study:
    id: str
    title: str
    question: str
    workload: str
    factors: dict[str, list]
    baseline: dict[str, Any]
    fixed: dict[str, Any] = field(default_factory=dict)
    # Comparisons are made within groups sharing these factor values (e.g. same query count).
    group_by: tuple[str, ...] = ()
    fallback_baselines: tuple[dict, ...] = ()


STUDIES: dict[str, Study] = {s.id: s for s in [
    Study("join-algorithms", "Join algorithm × parallelism",
          "Which join algorithm and thread count compute the same join with the least energy?",
          "joins", {"variant": ["hash", "sort_merge"], "threads": [1, 2, 4, 8]},
          baseline={"variant": "hash", "threads": 1}, fixed={"storage": DEFAULT_STORAGE}),
    Study("storage-formats", "Storage format × compression",
          "How much energy does the on-disk format cost when the computation is identical?",
          "joins", {"storage": list(STORAGES)}, baseline={"storage": "csv"},
          fixed={"variant": "hash", "threads": 1}),
    Study("text-search", "Full scan vs inverted index",
          "From how many queries does building an inverted index pay back its energy?",
          "text_search", {"variant": ["regex_scan", "inverted_index"], "n_queries": [1, 10, 100]},
          baseline={"variant": "regex_scan"}, fixed={"storage": DEFAULT_STORAGE}, group_by=("n_queries",)),
    Study("streaming-windows", "Batch vs incremental, exact vs approximate",
          "How much energy do incremental windows and approximate sketches save, and at what accuracy?",
          "streaming", {"variant": ["batch_recompute", "incremental", "approx_hll", "approx_sampling"]},
          baseline={"variant": "batch_recompute"}, fixed={"storage": DEFAULT_STORAGE}),
    Study("indexing", "No index vs B+-tree vs hash index",
          "Which index answers the query batch with the least energy, build cost included?",
          "indexing", {"variant": ["scan", "btree", "hash_index"], "n_queries": [1_000, 100_000]},
          baseline={"variant": "scan"}, fixed={"storage": DEFAULT_STORAGE}, group_by=("n_queries",),
          fallback_baselines=({"variant": "btree"},)),
]}


@dataclass(frozen=True)
class Preset:
    name: str
    label: str
    description: str
    scale: str
    repetitions: int
    warmups: int
    cooldown_s: float
    idle_s: float


PRESETS: dict[str, Preset] = {p.name: p for p in [
    Preset("quick", "Quick check", "Small datasets, 5 repetitions. A few minutes: try the tool, check a setup.",
           "small", 5, 1, 0.2, 5.0),
    Preset("standard", "Standard campaign",
           "Medium datasets, 10 repetitions after 2 warm-ups. The week-7 pilot campaign.",
           "medium", 10, 2, 0.5, 10.0),
    Preset("full", "Full campaign", "Medium datasets, 30 repetitions after 3 warm-ups. Final results (weeks 8–9).",
           "medium", 30, 3, 1.0, 20.0),
]}


def _fmt(knob: str, value: Any) -> str:
    if knob == "threads":
        return f"{value} thread" + ("s" if int(value) > 1 else "")
    if knob == "n_queries":
        return f"{int(value):,} quer" + ("ies" if int(value) > 1 else "y")
    if knob == "storage":
        return STORAGE_LABELS.get(value, value)
    return f"{knob}={value}"


@dataclass
class Config:
    key: str
    workload: str
    variant: str
    params: dict
    label: str
    studies: list[str] = field(default_factory=list)
    labels: dict[str, str] = field(default_factory=dict)  # label in the context of each study
    skipped: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def config_key(workload: str, variant: str, params: dict) -> str:
    return f"{workload}/{variant}/" + ",".join(f"{k}={params[k]}" for k in sorted(params))


def expand(study_ids: list[str]) -> tuple[list[Config], dict[str, list[str]]]:
    """Unique configurations across the selected studies, and the config keys of each study."""
    configs: dict[str, Config] = {}
    members: dict[str, list[str]] = {}
    for sid in study_ids:
        study = STUDIES[sid]
        w = get(study.workload)
        names = list(study.factors)
        members[sid] = []
        for combo in itertools.product(*(study.factors[n] for n in names)):
            values = dict(zip(names, combo))
            variant = values.pop("variant", study.fixed.get("variant", w.reference_variant))
            fixed = {k: v for k, v in study.fixed.items() if k != "variant"}
            params = w.params({**fixed, **values})
            key = config_key(w.name, variant, params)
            shown = [_fmt(k, params[k]) for k in values]
            label = " · ".join([w.variants[variant].label] + shown) if "variant" in names or not shown \
                else " · ".join(shown)
            if key not in configs:
                configs[key] = Config(key, w.name, variant, params, label, skipped=w.applicable(variant, params))
            configs[key].studies.append(sid)
            configs[key].labels[sid] = label
            members[sid].append(key)
    return list(configs.values()), members


def schedule(configs: list[Config], repetitions: int, warmups: int, seed: int) -> list[dict]:
    """Warm-up block, then randomised rounds: each round runs every configuration once in a fresh order."""
    rng = np.random.default_rng(seed)
    runnable = [c for c in configs if not c.skipped]
    plan = []
    for w in range(warmups):
        for i in rng.permutation(len(runnable)):
            plan.append({"config": runnable[i].key, "round": -(warmups - w), "warmup": True})
    for r in range(repetitions):
        for i in rng.permutation(len(runnable)):
            plan.append({"config": runnable[i].key, "round": r, "warmup": False})
    return plan


def describe_studies() -> list[dict]:
    out = []
    for s in STUDIES.values():
        d = asdict(s)
        d["group_by"] = list(s.group_by)
        d["fallback_baselines"] = list(s.fallback_baselines)
        out.append(json.loads(json.dumps(d)))
    return out
