"""Common interface for hardware energy meters."""

from __future__ import annotations

import time
from dataclasses import dataclass


class MeterUnavailable(RuntimeError):
    """Raised when a meter cannot be used on this machine (missing device, permissions...)."""


@dataclass
class Reading:
    """Cumulative energy per domain (joules, monotonic) at perf_counter time `t`."""

    t: float
    energy_j: dict[str, float]


class EnergyMeter:
    """A cumulative energy counter. Energy over an interval is the difference of two reads."""

    name = "base"
    kind = "hardware"
    # Domains that refresh on every read, so they can time sub-second regions.
    domains: tuple[str, ...] = ()
    primary_domain = "pkg"

    def read(self) -> Reading:
        raise NotImplementedError

    def close(self) -> None:
        pass

    def describe(self) -> dict:
        return {
            "name": self.name,
            "kind": self.kind,
            "domains": list(self.domains),
            "primary_domain": self.primary_domain,
        }

    def power_w(self, seconds: float = 1.0) -> dict[str, float]:
        """Average power per domain over a short wait (used for idle baselines)."""
        a = self.read()
        time.sleep(seconds)
        b = self.read()
        dt = b.t - a.t
        return {d: (b.energy_j[d] - a.energy_j[d]) / dt for d in self.domains}


def delta(a: Reading, b: Reading) -> dict[str, float]:
    return {d: b.energy_j[d] - a.energy_j[d] for d in a.energy_j if d in b.energy_j}
