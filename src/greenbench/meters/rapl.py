"""Linux RAPL reader through the powercap sysfs interface.

Reads /sys/class/powercap/intel-rapl:*/energy_uj (also used for AMD Zen since Linux 5.8).
Since the PLATYPUS disclosure (2020) energy_uj is root-readable only on most kernels:
run as root, inside a container started with access to /sys/class/powercap, or grant
read access, e.g. `sudo chmod a+r /sys/class/powercap/intel-rapl:*/energy_uj`.
Counters wrap at max_energy_range_uj; wrap-around is corrected on every read.
"""

from __future__ import annotations

import time
from pathlib import Path

from greenbench.meters.base import EnergyMeter, MeterUnavailable, Reading

BASE = Path("/sys/class/powercap")
_NAMES = {"core": "cores", "dram": "dram", "uncore": "gpu", "psys": "psys"}


class RaplMeter(EnergyMeter):
    name = "rapl"
    kind = "hardware"

    def __init__(self):
        if not BASE.exists():
            raise MeterUnavailable("no /sys/class/powercap (not Linux, or RAPL not exposed, e.g. inside a VM)")
        zones = []
        for zone in sorted(BASE.glob("intel-rapl:*")):
            name_file, energy_file = zone / "name", zone / "energy_uj"
            if not energy_file.exists():
                continue
            raw = name_file.read_text().strip()
            dom = "pkg" if raw.startswith("package") else _NAMES.get(raw)
            if dom is None:
                continue
            try:
                int(energy_file.read_text())
            except PermissionError as exc:
                raise MeterUnavailable("RAPL counters are not readable: run as root or "
                                       "chmod a+r /sys/class/powercap/intel-rapl:*/energy_uj") from exc
            max_range = int((zone / "max_energy_range_uj").read_text())
            zones.append((dom, energy_file, max_range))
        if not any(d == "pkg" for d, _, _ in zones):
            raise MeterUnavailable("no RAPL package zone found")
        self._zones = zones
        self._last = [int(f.read_text()) for _, f, _ in zones]
        self._acc = [0.0] * len(zones)
        doms = sorted({d for d, _, _ in zones})
        self.domains = tuple(["pkg"] + [d for d in doms if d != "pkg"])

    def read(self) -> Reading:
        t = time.perf_counter()
        energy = {d: 0.0 for d in self.domains}
        for i, (dom, f, max_range) in enumerate(self._zones):
            raw = int(f.read_text())
            step = raw - self._last[i]
            if step < 0:  # counter wrapped
                step += max_range
            self._acc[i] += step * 1e-6
            self._last[i] = raw
            energy[dom] += self._acc[i]
        return Reading(t, energy)

    def describe(self) -> dict:
        info = super().describe()
        info.update({"interface": "Linux powercap (intel-rapl)",
                     "channels": {str(f.parent.name): d for d, f, _ in self._zones}})
        return info
