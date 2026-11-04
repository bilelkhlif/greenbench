"""Workload registry."""

from __future__ import annotations

from greenbench.workloads.base import Workload
from greenbench.workloads.indexing import Indexing
from greenbench.workloads.joins import Joins
from greenbench.workloads.streaming import StreamingAggregation
from greenbench.workloads.text_search import TextSearch

WORKLOADS: dict[str, Workload] = {w.name: w for w in (Joins(), TextSearch(), StreamingAggregation(), Indexing())}


def get(name: str) -> Workload:
    try:
        return WORKLOADS[name]
    except KeyError:
        raise KeyError(f"unknown workload {name!r}; choose from {', '.join(WORKLOADS)}") from None
