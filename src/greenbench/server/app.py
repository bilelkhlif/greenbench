"""Dashboard backend: JSON API over the results directory, plus the built web UI."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from greenbench import __version__
from greenbench.analysis.analyze import analyze_campaign
from greenbench.paths import docs_dir, results_dir
from greenbench.protocol.plan import PRESETS, STUDIES, describe_studies, expand
from greenbench.roadmap import DOCS, roadmap
from greenbench.workloads import WORKLOADS

STATIC = Path(__file__).parent / "static"
ACTIVE_STATES = {"preparing", "idle-baseline", "warm-up", "running", "analysing"}
STALE_AFTER_S = 15 * 60  # a running campaign that has not written its status for this long has died

app = FastAPI(title="GreenBench", version=__version__)
_children: dict[str, subprocess.Popen] = {}


def _read_json(path: Path):
    for _ in range(5):  # the runner replaces these files atomically; retry a transient sharing error
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (PermissionError, json.JSONDecodeError):
            time.sleep(0.05)
    raise HTTPException(503, f"could not read {path.name}")


def _campaign_dirs() -> list[Path]:
    root = results_dir()
    if not root.exists():
        return []
    return sorted((d for d in root.iterdir() if (d / "campaign.json").exists()), key=lambda d: d.name, reverse=True)


def _dir(cid: str) -> Path:
    d = results_dir() / cid
    if not (d / "campaign.json").exists() or d.parent != results_dir():
        raise HTTPException(404, f"campaign {cid!r} not found")
    return d


def _status(d: Path) -> dict:
    p = d / "status.json"
    status = _read_json(p) if p.exists() else {"state": "unknown"}
    if status.get("state") in ACTIVE_STATES:
        age = time.time() - p.stat().st_mtime
        child = _children.get(d.name)
        if age > STALE_AFTER_S or (child is not None and child.poll() is not None and status["state"] != "analysing"):
            status["state"] = "interrupted"
    return status


def _analysis(d: Path) -> dict | None:
    """Serve the stored analysis. Never compute while a campaign runs: that CPU work would be
    background load on the very machine being measured."""
    path = d / "analysis.json"
    if path.exists():
        return _read_json(path)
    if _status(d).get("state") in ACTIVE_STATES or not (d / "runs.jsonl").exists():
        return None
    return analyze_campaign(d)


def _summary(d: Path) -> dict:
    c = _read_json(d / "campaign.json")
    status = _status(d)
    a = _read_json(d / "analysis.json") if (d / "analysis.json").exists() else None
    best = None
    if a:
        switches = [r for r in a["recommendations"] if r.get("kind") == "switch"]
        best = min(switches, key=lambda r: r["energy_change_pct"], default=None)
    return {
        "id": c["id"], "created_at": c["created_at"], "finished_at": c.get("finished_at"),
        "preset": c["config"]["preset"], "scale": c["config"]["scale"], "repetitions": c["config"]["repetitions"],
        "warmups": c["config"]["warmups"], "studies": list(c["studies"]), "notes": c["config"].get("notes", ""),
        "n_configs": sum(not cfg.get("skipped") for cfg in c["configs"]), "status": status,
        "cpu": c["environment"]["cpu"]["name"], "meter": (c.get("primary_meter") or {}).get("interface"),
        "quality": a["quality"] if a else None, "totals": a["totals"] if a else None,
        "idle_w": a["idle_w"] if a else None, "best": best,
    }


@app.get("/api/health")
def health():
    return {"ok": True, "version": __version__}


@lru_cache(maxsize=1)
def _environment():
    from greenbench.environment import fingerprint

    return fingerprint()


@app.get("/api/environment")
def environment():
    return _environment()


@app.get("/api/meter/live")
def meter_live():
    """Package power over half a second. Skipped while a campaign runs, to keep the machine quiet."""
    if any(_status(d).get("state") in ACTIVE_STATES for d in _campaign_dirs()[:3]):
        return {"available": False, "reason": "campaign running"}
    from greenbench.meters import open_meter

    try:
        meter = open_meter("auto")
    except Exception as exc:
        return {"available": False, "reason": str(exc)}
    if meter is None:
        return {"available": False, "reason": "no hardware meter"}
    try:
        watts = meter.power_w(0.5)
        return {"available": True, "watts": watts, "interface": meter.describe().get("interface")}
    finally:
        meter.close()


@app.get("/api/workloads")
def workloads():
    out = []
    for w in WORKLOADS.values():
        d = w.describe()
        d["studies"] = [s.id for s in STUDIES.values() if s.workload == w.name]
        out.append(d)
    return out


@app.get("/api/studies")
def studies():
    out = []
    for s in describe_studies():
        configs, _ = expand([s["id"]])
        s["n_configs"] = len(configs)
        s["n_skipped"] = sum(bool(c.skipped) for c in configs)
        out.append(s)
    return out


@app.get("/api/presets")
def presets():
    configs, _ = expand(list(STUDIES))
    runnable = sum(not c.skipped for c in configs)
    return [{**p.__dict__, "runs": runnable * (p.repetitions + p.warmups)} for p in PRESETS.values()]


@app.get("/api/campaigns")
def campaigns():
    return [_summary(d) for d in _campaign_dirs()]


@app.get("/api/campaigns/{cid}")
def campaign(cid: str):
    d = _dir(cid)
    c = _read_json(d / "campaign.json")
    c["status"] = _status(d)
    return c


@app.get("/api/campaigns/{cid}/runs")
def campaign_runs(cid: str):
    from greenbench.analysis.analyze import load_runs

    keep = ("seq", "config", "workload", "variant", "params", "round", "warmup", "status", "duration_s", "cpu_s",
            "peak_rss_mb", "energy_j", "energy_model_j", "background_cpu_s", "valid", "accuracy", "error")
    return [{k: r.get(k) for k in keep} for r in load_runs(_dir(cid))]


@app.get("/api/campaigns/{cid}/analysis")
def campaign_analysis(cid: str):
    a = _analysis(_dir(cid))
    if a is None:
        raise HTTPException(404, "the analysis is computed when the campaign completes")
    return a


class LaunchRequest(BaseModel):
    preset: str = "quick"
    studies: list[str] = Field(default_factory=lambda: list(STUDIES))
    repetitions: int | None = Field(default=None, ge=1, le=100)
    warmups: int | None = Field(default=None, ge=0, le=10)
    notes: str = ""


@app.post("/api/campaigns", status_code=201)
def launch(req: LaunchRequest):
    if req.preset not in PRESETS:
        raise HTTPException(422, f"unknown preset {req.preset!r}")
    unknown = [s for s in req.studies if s not in STUDIES]
    if unknown or not req.studies:
        raise HTTPException(422, f"unknown or empty studies: {unknown}")
    for d in _campaign_dirs():
        if _status(d).get("state") in ACTIVE_STATES:
            raise HTTPException(409, f"campaign {d.name} is still running")
    cid = datetime.now().strftime("%Y%m%d-%H%M%S") + f"-{req.preset}"
    cmd = [sys.executable, "-m", "greenbench", "run", "--preset", req.preset, "--studies", ",".join(req.studies),
           "--id", cid]
    if req.repetitions:
        cmd += ["--repetitions", str(req.repetitions)]
    if req.warmups is not None:
        cmd += ["--warmups", str(req.warmups)]
    if req.notes:
        cmd += ["--notes", req.notes]
    d = results_dir() / cid
    d.mkdir(parents=True, exist_ok=True)
    log = open(d / "runner.log", "w", encoding="utf-8")
    flags = (subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW) if sys.platform == "win32" else 0
    _children[cid] = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, creationflags=flags)
    deadline = time.time() + 20  # wait until the runner has written its first files
    while time.time() < deadline and not (d / "status.json").exists():
        time.sleep(0.2)
    return {"id": cid}


@app.post("/api/campaigns/{cid}/cancel")
def cancel(cid: str):
    d = _dir(cid)
    if _status(d).get("state") not in ACTIVE_STATES:
        raise HTTPException(409, "campaign is not running")
    (d / "cancel.flag").write_text(datetime.now(timezone.utc).isoformat(), encoding="utf-8")
    return {"ok": True}


@app.get("/api/roadmap")
def get_roadmap():
    return roadmap()


@app.get("/api/docs")
def docs():
    root = docs_dir()
    return [{"slug": slug, "title": title, "available": bool(root and (root / name).exists())}
            for slug, (name, title) in DOCS.items()]


@app.get("/api/docs/{slug}")
def doc(slug: str):
    if slug not in DOCS or docs_dir() is None:
        raise HTTPException(404, "unknown document")
    name, title = DOCS[slug]
    path = docs_dir() / name
    if not path.exists():
        raise HTTPException(404, "document not written yet")
    return {"slug": slug, "title": title, "markdown": path.read_text(encoding="utf-8")}


def _ranked_insights(insights: list[str]) -> list[str]:
    """Trade-offs first (they change decisions), statements of the obvious last."""
    def score(text: str) -> int:
        if any(k in text for k in ("not greenest", "repays", "not automatically greener", "accuracy loss",
                                   "Reading the inputs")):
            return 0
        if "tied" in text or "never repays" in text:
            return 1
        return 2
    return sorted(insights, key=score)


@app.get("/api/overview")
def overview():
    dirs = _campaign_dirs()
    summaries = [_summary(d) for d in dirs]
    done = [s for s in summaries if s["status"].get("state") == "completed"]
    latest = done[0] if done else None
    analysis = _read_json(results_dir() / latest["id"] / "analysis.json") if latest else None
    running = next((s for s in summaries if s["status"].get("state") in ACTIVE_STATES), None)
    order = {"switch": 0, "trade-off": 1, "keep": 2}
    recs = sorted([r for r in (analysis or {}).get("recommendations", []) if r.get("kind") in order],
                  key=lambda r: (order[r["kind"]], r["energy_change_pct"]))
    return {
        "version": __version__, "roadmap": roadmap(), "latest": latest, "running": running,
        "campaigns": len(summaries),
        "runs_measured": sum((s["quality"] or {}).get("runs", 0) for s in summaries),
        "energy_measured_j": sum((s["totals"] or {}).get("energy_pkg_j", 0) for s in summaries),
        "recommendations": recs[:6],
        "studies": [{"id": s["id"], "title": s["title"], "insights": _ranked_insights(s["insights"])[:2]}
                    for s in (analysis or {}).get("studies", [])],
        "meter_check": {k: v for k, v in ((analysis or {}).get("meter_check") or {}).items() if k != "points"},
        "idle_w": (analysis or {}).get("idle_w"),
    }


if STATIC.exists() and (STATIC / "index.html").exists():
    app.mount("/assets", StaticFiles(directory=STATIC / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        target = (STATIC / path).resolve()
        if path and target.is_file() and STATIC.resolve() in target.parents:
            return FileResponse(target)
        return FileResponse(STATIC / "index.html")
