"""Campaign orchestration: the automated measurement protocol.

1. fingerprint the machine and check the meters
2. prepare datasets, storage copies, query sets and reference results (never measured)
3. measure the idle baseline (package power with nothing running)
4. warm-up block: every configuration runs W times, discarded
5. R randomised rounds: every configuration once per round, in a fresh random order,
   each run in a fresh process, with a cool-down pause between runs
6. re-measure idle power periodically and at the end (drift check)
7. analyse: distributions, confidence intervals, significance tests, recommendations
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import psutil

from greenbench.data.generate import ensure_dataset, load_meta, storage_sizes
from greenbench.environment import fingerprint
from greenbench.meters import open_meter
from greenbench.paths import results_dir
from greenbench.protocol.plan import PRESETS, STUDIES, expand, schedule
from greenbench.protocol.reference import ensure_reference
from greenbench.workloads import get

RUN_TIMEOUT_S = 600
IDLE_EVERY_N_RUNS = 60


@dataclass
class CampaignConfig:
    preset: str = "standard"
    studies: list[str] = field(default_factory=lambda: list(STUDIES))
    scale: str | None = None
    repetitions: int | None = None
    warmups: int | None = None
    cooldown_s: float | None = None
    idle_s: float | None = None
    meter: str = "auto"
    seed: int | None = None
    notes: str = ""
    campaign_id: str | None = None

    def resolved(self) -> "CampaignConfig":
        p = PRESETS[self.preset]
        return CampaignConfig(
            preset=self.preset, studies=list(self.studies), scale=self.scale or p.scale,
            repetitions=self.repetitions or p.repetitions,
            warmups=p.warmups if self.warmups is None else self.warmups,
            cooldown_s=p.cooldown_s if self.cooldown_s is None else self.cooldown_s,
            idle_s=p.idle_s if self.idle_s is None else self.idle_s, meter=self.meter,
            seed=self.seed if self.seed is not None else int(time.time()) % 100_000,
            notes=self.notes, campaign_id=self.campaign_id or new_campaign_id(self.preset))


def new_campaign_id(preset: str) -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S") + f"-{preset}"


def write_json(path: Path, data) -> None:
    """Atomic write; retried because Windows refuses to replace a file another process is reading."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    for attempt in range(50):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            time.sleep(0.02 * (attempt + 1))
    os.replace(tmp, path)


def measure_idle(meter, seconds: float, window: float = 1.0) -> dict:
    """Package power with nothing running, plus how busy the rest of the machine was."""
    if meter is None or seconds <= 0:
        return {"samples": [], "seconds": 0}
    time.sleep(min(2.0, seconds / 4))  # let the previous activity settle
    first = meter.read()
    psutil.cpu_percent(None)
    samples = []
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        a = meter.read()
        time.sleep(window)
        b = meter.read()
        dt = b.t - a.t
        samples.append({"pkg_w": (b.energy_j["pkg"] - a.energy_j["pkg"]) / dt,
                        **({"cores_w": (b.energy_j["cores"] - a.energy_j["cores"]) / dt}
                           if "cores" in b.energy_j else {})})
    last = meter.read()
    span = last.t - first.t
    avg = {f"{d}_w": (last.energy_j[d] - first.energy_j[d]) / span for d in last.energy_j}
    return {"at": datetime.now(timezone.utc).isoformat(), "seconds": span, "average": avg, "samples": samples,
            "system_cpu_percent": psutil.cpu_percent(None)}


class Runner:
    def __init__(self, cfg: CampaignConfig, log=print):
        self.cfg = cfg.resolved()
        self.log = log
        self.dir = results_dir() / self.cfg.campaign_id
        self.dir.mkdir(parents=True, exist_ok=True)
        self.runs_path = self.dir / "runs.jsonl"
        self.status_path = self.dir / "status.json"
        self.cancel_path = self.dir / "cancel.flag"
        self.status: dict = {}

    def _status(self, **kw) -> None:
        self.status.update(kw, updated_at=datetime.now(timezone.utc).isoformat())
        write_json(self.status_path, self.status)

    def run(self) -> Path:
        cfg = self.cfg
        configs, members = expand(cfg.studies)
        plan = schedule(configs, cfg.repetitions, cfg.warmups, cfg.seed)
        by_key = {c.key: c for c in configs}
        self._status(state="preparing", done=0, total=len(plan), measured=0, invalid=0, errors=0,
                     started_at=datetime.now(timezone.utc).isoformat(), current=None, eta_s=None)
        self.log(f"campaign {cfg.campaign_id}: {len(configs)} configurations, {len(plan)} runs")

        env = fingerprint()
        meter = open_meter(cfg.meter, **({"include_slow": True} if cfg.meter in ("auto", "emi")
                                         and sys.platform == "win32" else {}))
        campaign = {
            "id": cfg.campaign_id, "created_at": datetime.now(timezone.utc).isoformat(), "config": asdict(cfg),
            "environment": env, "primary_meter": None if meter is None else meter.describe(),
            "studies": {sid: {**asdict(STUDIES[sid]), "configs": members[sid]} for sid in cfg.studies},
            "configs": [c.to_dict() for c in configs], "idle": [],
        }
        write_json(self.dir / "campaign.json", campaign)

        needs = {(t, c.params["storage"]) for c in configs for t in get(c.workload).inputs}
        data_dir = ensure_dataset(cfg.scale, needs, log=self.log)
        meta = load_meta(data_dir)
        campaign["dataset"] = {"scale": cfg.scale, "seed": meta["seed"], "rows": meta["rows"],
                               "bytes": storage_sizes(data_dir)}
        refs = {}
        for c in configs:
            w = get(c.workload)
            if hasattr(w, "ensure_inputs"):
                w.ensure_inputs(data_dir, c.params)
            refs[c.key] = ensure_reference(data_dir, c.workload, c.params)["checksum"]

        self._status(state="idle-baseline")
        self.log("measuring idle baseline...")
        campaign["idle"].append(measure_idle(meter, cfg.idle_s))
        write_json(self.dir / "campaign.json", campaign)

        model_info = {"tdp_w": env["cpu"]["tdp_w"], "logical_cpus": env["cpu"]["logical_cpus"]}
        t_start = time.perf_counter()
        counters = {"measured": 0, "invalid": 0, "errors": 0}
        state = "running"
        for i, item in enumerate(plan):
            if self.cancel_path.exists():
                state = "cancelled"
                break
            c = by_key[item["config"]]
            self._status(state="warm-up" if item["warmup"] else "running", done=i,
                         current={"config": c.key, "label": c.label, "round": item["round"]}, **counters)
            spec = {"workload": c.workload, "variant": c.variant, "params": c.params, "data_dir": str(data_dir),
                    "meter": cfg.meter, "reference_checksum": refs[c.key], "model": model_info}
            rec = self._launch(spec)
            rec.update({"seq": i, "config": c.key, "workload": c.workload, "variant": c.variant,
                        "params": c.params, "round": item["round"], "warmup": item["warmup"]})
            with self.runs_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec) + "\n")
            if not item["warmup"]:
                counters["measured"] += 1
                counters["invalid"] += rec["status"] == "invalid"
            counters["errors"] += rec["status"] == "error"
            if rec["status"] != "ok":
                self.log(f"  run {i} {c.key}: {rec['status']} {rec.get('error', '')}")
            elapsed = time.perf_counter() - t_start
            self._status(done=i + 1, eta_s=elapsed / (i + 1) * (len(plan) - i - 1), **counters)
            if (i + 1) % 25 == 0:
                self.log(f"  {i + 1}/{len(plan)} runs, {elapsed / 60:.1f} min elapsed")
            if (i + 1) % IDLE_EVERY_N_RUNS == 0 and i + 1 < len(plan):
                self._status(state="idle-baseline")
                campaign["idle"].append(measure_idle(meter, min(5.0, cfg.idle_s)))
                write_json(self.dir / "campaign.json", campaign)
            time.sleep(cfg.cooldown_s)

        if state != "cancelled":
            self._status(state="idle-baseline")
            campaign["idle"].append(measure_idle(meter, cfg.idle_s))
        if meter is not None:
            meter.close()
        campaign["finished_at"] = datetime.now(timezone.utc).isoformat()
        campaign["state"] = "completed" if state != "cancelled" else "cancelled"
        write_json(self.dir / "campaign.json", campaign)

        self._status(state="analysing", current=None, eta_s=None)
        from greenbench.analysis.analyze import analyze_campaign

        analyze_campaign(self.dir)
        self._status(state=campaign["state"], finished_at=campaign["finished_at"])
        self.cancel_path.unlink(missing_ok=True)
        self.log(f"campaign {campaign['state']}: {self.dir}")
        return self.dir

    def _launch(self, spec: dict) -> dict:
        env = dict(os.environ, PYTHONHASHSEED="0", OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1",
                   MKL_NUM_THREADS="1")
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        try:
            proc = subprocess.run([sys.executable, "-m", "greenbench.protocol.worker"], input=json.dumps(spec),
                                  capture_output=True, text=True, timeout=RUN_TIMEOUT_S, env=env, creationflags=flags)
        except subprocess.TimeoutExpired:
            return {"status": "error", "error": f"timeout after {RUN_TIMEOUT_S} s"}
        try:
            return json.loads(proc.stdout)
        except json.JSONDecodeError:
            return {"status": "error", "error": f"worker exited {proc.returncode}: {proc.stderr.strip()[-800:]}"}
