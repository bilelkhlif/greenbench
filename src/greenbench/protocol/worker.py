"""One measured run, executed in a fresh process (isolation: no state carried between runs).

Reads a JSON spec on stdin, prints a JSON record on stdout. Imports, inputs and the meter
are prepared before the measured region; result validation happens after it.
"""

from __future__ import annotations

import gc
import json
import sys
import time
import traceback
from pathlib import Path


def _busy_cpu_s(ct) -> float:
    """System-wide busy CPU-seconds (all cores)."""
    if sys.platform == "win32":
        return ct.user + ct.system  # interrupt/DPC time is already part of system time
    return sum(ct) - ct.idle - getattr(ct, "iowait", 0.0)


def _peak_rss_bytes(proc) -> int:
    mi = proc.memory_info()
    peak = getattr(mi, "peak_wset", None)
    if peak:
        return int(peak)
    try:
        import resource

        kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return int(kb * (1 if sys.platform == "darwin" else 1024))
    except ImportError:
        return int(mi.rss)


def execute(spec: dict) -> dict:
    import psutil
    import pyarrow as pa

    from greenbench.data.generate import load_meta
    from greenbench.meters import open_meter
    from greenbench.meters.model import EnergyModel
    from greenbench.protocol.reference import load_reference_arrays
    from greenbench.workloads import get
    from greenbench.workloads.base import RunContext, accuracy, checksum

    w = get(spec["workload"])
    variant, params = spec["variant"], spec["params"]
    data_dir = Path(spec["data_dir"])
    threads = int(params.get("threads", 1))
    pa.set_cpu_count(max(1, threads))
    pa.set_io_thread_count(max(1, threads))

    meter = open_meter(spec.get("meter", "auto"))
    prep = w.prepare(data_dir, load_meta(data_dir), params)
    proc = psutil.Process()
    ctx = RunContext(meter, proc)
    gc.collect()
    rss_before = proc.memory_info().rss
    sys_before = psutil.cpu_times()
    started = time.time()

    result = w.run(variant, params, ctx, prep)  # ---- measured region (all phases) ----

    sys_after = psutil.cpu_times()
    peak = _peak_rss_bytes(proc)
    first, last = ctx.phases[0].start, ctx.phases[-1].end
    duration = last.t - first.t
    cpu_s = last.cpu_s - first.cpu_s
    energy = {d: last.energy[d] - first.energy[d] for d in last.energy}
    phases = [{"name": p.name, "duration_s": p.end.t - p.start.t, "cpu_s": p.end.cpu_s - p.start.cpu_s,
               "energy_j": {d: p.end.energy[d] - p.start.energy[d] for d in p.end.energy}} for p in ctx.phases]
    if meter is not None:
        meter.close()

    model = EnergyModel(spec["model"]["tdp_w"], spec["model"]["logical_cpus"])
    model_energy = model.estimate(cpu_s, duration, peak / 2**30)
    busy = _busy_cpu_s(sys_after) - _busy_cpu_s(sys_before)

    record = {
        "status": "ok", "started_unix": started, "duration_s": duration, "cpu_s": cpu_s,
        "cpu_util": cpu_s / duration if duration > 0 else None,
        "peak_rss_mb": peak / 2**20, "rss_before_mb": rss_before / 2**20,
        "energy_j": energy, "energy_model_j": model_energy, "phases": phases,
        "background_cpu_s": max(0.0, busy - cpu_s),
        "meter": None if meter is None else meter.name,
    }

    ck = checksum(result)
    record["checksum"] = ck
    if w.variants[variant].exact:
        record["valid"] = ck == spec["reference_checksum"]
        record["accuracy"] = None
    else:
        ref = load_reference_arrays(data_dir, w.name, params)
        record["valid"] = True
        record["accuracy"] = accuracy(result, ref)
    if not record["valid"]:
        record["status"] = "invalid"
    record["result_summary"] = w.summary_of(result)
    return record


def main() -> None:
    spec = json.loads(sys.stdin.read())
    try:
        out = execute(spec)
    except Exception as exc:  # report, never crash the campaign
        out = {"status": "error", "error": f"{type(exc).__name__}: {exc}", "traceback": traceback.format_exc()}
    sys.stdout.write(json.dumps(out))


if __name__ == "__main__":
    main()
