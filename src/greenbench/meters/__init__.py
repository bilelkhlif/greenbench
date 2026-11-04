"""Energy meters: hardware counters (Windows EMI, Linux RAPL) plus a software model."""

from __future__ import annotations

from greenbench.meters.base import EnergyMeter, MeterUnavailable, Reading, delta

__all__ = ["EnergyMeter", "MeterUnavailable", "Reading", "delta", "open_meter", "probe_meters"]


def _candidates():
    from greenbench.meters.emi import EmiMeter
    from greenbench.meters.rapl import RaplMeter

    return {"emi": EmiMeter, "rapl": RaplMeter}


def open_meter(name: str = "auto", **kwargs) -> EnergyMeter | None:
    """Open the requested hardware meter. "auto" picks the first available; "model" returns None."""
    if name == "model":
        return None
    cands = _candidates()
    if name != "auto":
        return cands[name](**kwargs)
    for cls in cands.values():
        try:
            return cls(**kwargs)
        except MeterUnavailable:
            continue
    return None


def probe_meters() -> dict[str, dict]:
    """Availability of every hardware meter, with the reason when unavailable."""
    out = {}
    for name, cls in _candidates().items():
        try:
            m = cls()
        except MeterUnavailable as exc:
            out[name] = {"available": False, "reason": str(exc)}
            continue
        except Exception as exc:  # unexpected platform quirks must not break the tool
            out[name] = {"available": False, "reason": f"{type(exc).__name__}: {exc}"}
            continue
        out[name] = {"available": True, **m.describe()}
        m.close()
    return out
