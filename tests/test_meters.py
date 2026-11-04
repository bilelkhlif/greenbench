import time

import pytest

from greenbench.meters import MeterUnavailable, open_meter, probe_meters
from greenbench.meters.model import EnergyModel, detect_tdp


def test_tdp_patterns():
    assert detect_tdp("AMD Ryzen 7 6800HS with Radeon Graphics")[0] == 35
    assert detect_tdp("Intel(R) Core(TM) i7-1165G7 @ 2.80GHz")[0] == 28
    assert detect_tdp("Intel(R) Core(TM) i5-12400")[0] == 65
    assert detect_tdp("Mystery CPU")[1].startswith("default")


def test_model_formula():
    e = EnergyModel(tdp_w=32, logical_cpus=16).estimate(cpu_s=2.0, wall_s=1.0, mem_gb=8.0)
    assert e["cpu"] == pytest.approx(4.0)
    assert e["dram"] == pytest.approx(3.0)
    assert e["total"] == pytest.approx(7.0)


def test_probe_never_raises():
    info = probe_meters()
    assert set(info) == {"emi", "rapl"}
    assert all("available" in v for v in info.values())


def test_hardware_meter_counts_up_when_available():
    try:
        meter = open_meter("auto")
    except MeterUnavailable:
        meter = None
    if meter is None:
        pytest.skip("no hardware energy meter on this machine")
    a = meter.read()
    end = time.perf_counter() + 0.3
    x = 0
    while time.perf_counter() < end:
        x += sum(range(1000))
    b = meter.read()
    meter.close()
    power = (b.energy_j["pkg"] - a.energy_j["pkg"]) / (b.t - a.t)
    assert 0.1 < power < 500, f"implausible package power {power:.2f} W"
