"""Workload API: a task, its implementation variants, and the knobs it accepts."""

from __future__ import annotations

import hashlib
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

Result = dict[str, np.ndarray]


@dataclass(frozen=True)
class Variant:
    name: str
    label: str
    description: str
    exact: bool = True


@dataclass
class Snapshot:
    t: float
    energy: dict[str, float]
    cpu_s: float


@dataclass
class Phase:
    name: str
    start: Snapshot
    end: Snapshot


@dataclass
class RunContext:
    """Timestamps energy, CPU time and wall time at every phase boundary of the measured region."""

    meter: Any = None
    process: Any = None
    phases: list[Phase] = field(default_factory=list)

    def snapshot(self) -> Snapshot:
        t = time.perf_counter()
        energy = self.meter.read().energy_j if self.meter is not None else {}
        ct = self.process.cpu_times() if self.process is not None else None
        return Snapshot(t, energy, (ct.user + ct.system) if ct else 0.0)

    @contextmanager
    def phase(self, name: str):
        start = self.snapshot()
        yield
        self.phases.append(Phase(name, start, self.snapshot()))


class Workload:
    name: str = ""
    title: str = ""
    summary: str = ""
    description: str = ""
    icon: str = ""
    inputs: tuple[str, ...] = ()
    variants: dict[str, Variant] = {}
    knobs: dict[str, list] = {}
    defaults: dict[str, Any] = {}
    # Knobs whose value changes the expected result (e.g. the number of queries).
    result_knobs: tuple[str, ...] = ()
    reference_variant: str = ""
    phases: tuple[str, ...] = ()

    def params(self, overrides: dict | None = None) -> dict:
        p = dict(self.defaults)
        p.update(overrides or {})
        return p

    def applicable(self, variant: str, params: dict) -> str | None:
        """None when the configuration can run; otherwise the reason it is skipped."""
        return None

    def prepare(self, data_dir: Path, meta: dict, params: dict) -> dict:
        """Inputs built before measurement starts (query sets, file paths...)."""
        return {}

    def run(self, variant: str, params: dict, ctx: RunContext, prep: dict) -> Result:
        raise NotImplementedError

    def summary_of(self, result: Result) -> dict:
        return {}

    def describe(self) -> dict:
        return {
            "name": self.name, "title": self.title, "summary": self.summary, "description": self.description,
            "icon": self.icon, "inputs": list(self.inputs), "phases": list(self.phases),
            "variants": [{"name": v.name, "label": v.label, "description": v.description, "exact": v.exact}
                         for v in self.variants.values()],
            "knobs": self.knobs, "defaults": self.defaults, "reference_variant": self.reference_variant,
        }


def checksum(result: Result) -> str:
    h = hashlib.sha256()
    for key in sorted(result):
        arr = np.ascontiguousarray(result[key])
        h.update(key.encode())
        h.update(str(arr.dtype).encode())
        h.update(str(arr.shape).encode())
        h.update(arr.tobytes())
    return h.hexdigest()[:16]


def accuracy(result: Result, reference: Result) -> dict[str, dict[str, float]]:
    """Relative error of each numeric output against the exact reference (approximate variants)."""
    out = {}
    for key, ref in reference.items():
        if key not in result or ref.dtype.kind not in "iuf":
            continue
        ref_f = ref.astype(np.float64).ravel()
        res_f = np.asarray(result[key], dtype=np.float64).ravel()
        if res_f.shape != ref_f.shape:
            continue
        nz = ref_f != 0
        ape = np.abs(res_f[nz] - ref_f[nz]) / np.abs(ref_f[nz])
        out[key] = {"mape": float(ape.mean()) if ape.size else 0.0,
                    "p95_ape": float(np.percentile(ape, 95)) if ape.size else 0.0,
                    "max_ape": float(ape.max()) if ape.size else 0.0}
    return out
