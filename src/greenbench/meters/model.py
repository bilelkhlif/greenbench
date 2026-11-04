"""Software energy model, recorded on every run to cross-check the hardware counters.

The model follows the CodeCarbon-style estimate used when no counter is available:

    E_cpu  = (TDP / logical CPUs) x CPU-seconds of the measured process
    E_dram = 0.375 W/GB x peak resident memory (GB) x wall time      (3 W per 8 GB)

It attributes energy to the process only (no idle or static power) and ignores DVFS,
turbo and memory-traffic effects. It is an estimate, never reported as a measurement.
"""

from __future__ import annotations

import os
import re

DRAM_W_PER_GB = 0.375

# Nominal TDP (W) by CPU family pattern. First match wins; override with GREENBENCH_TDP_W.
_TDP_PATTERNS: list[tuple[str, float]] = [
    (r"Ryzen \d \d{4}HS", 35), (r"Ryzen \d \d{4}HX", 55), (r"Ryzen \d \d{4}H\b", 45),
    (r"Ryzen \d \d{4}U", 15), (r"Ryzen AI", 28), (r"Ryzen \d PRO \d{4}U", 15),
    (r"Ryzen \d \d{4}X3D", 120), (r"Ryzen \d \d{4}X", 105), (r"Ryzen \d \d{4}G", 65), (r"Ryzen \d \d{4}\b", 65),
    (r"EPYC", 200), (r"Threadripper", 280),
    (r"Core\(TM\) Ultra \d \d{3}H", 28), (r"Core\(TM\) Ultra \d \d{3}U", 15), (r"Core\(TM\) Ultra \d \d{3}V", 17),
    (r"Core\(TM\) i\d-\d{4,5}HX", 55), (r"Core\(TM\) i\d-\d{4,5}H", 45), (r"Core\(TM\) i\d-\d{4,5}P", 28),
    (r"Core\(TM\) i\d-\d{4,5}U", 15), (r"Core\(TM\) i\d-\d{4,5}G\d", 28), (r"Core\(TM\) i\d-\d{4,5}K", 125),
    (r"Core\(TM\) i\d-\d{4,5}", 65),
    (r"Xeon", 150), (r"Apple M\d (Max|Pro)", 40), (r"Apple M\d", 20),
]
DEFAULT_TDP_W = 45.0


def detect_tdp(cpu_name: str) -> tuple[float, str]:
    env = os.environ.get("GREENBENCH_TDP_W")
    if env:
        return float(env), "GREENBENCH_TDP_W"
    for pattern, tdp in _TDP_PATTERNS:
        m = re.search(pattern, cpu_name or "")
        if m:
            return float(tdp), f"nominal TDP of the {m.group(0).replace('(TM)', '')} family"
    return DEFAULT_TDP_W, "default (unknown CPU)"


class EnergyModel:
    def __init__(self, tdp_w: float, logical_cpus: int):
        self.tdp_w = tdp_w
        self.logical_cpus = max(1, logical_cpus)

    def estimate(self, cpu_s: float, wall_s: float, mem_gb: float) -> dict[str, float]:
        cpu = self.tdp_w / self.logical_cpus * cpu_s
        dram = DRAM_W_PER_GB * mem_gb * wall_s
        return {"cpu": cpu, "dram": dram, "total": cpu + dram}

    def describe(self) -> dict:
        return {"name": "model", "kind": "model", "tdp_w": self.tdp_w, "logical_cpus": self.logical_cpus,
                "dram_w_per_gb": DRAM_W_PER_GB,
                "formula": "TDP/logical_cpus x cpu_seconds + 0.375 W/GB x peak_rss_GB x wall_seconds"}
