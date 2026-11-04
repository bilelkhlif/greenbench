"""Turn raw runs into evidence: per-configuration distributions, comparisons against each
study's baseline, Pareto fronts, break-even points and quantified recommendations."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from scipy import stats as sstats

from greenbench.analysis.stats import cliffs_delta, describe, holm, magnitude, mann_whitney_p, ratio_of_medians
from greenbench.workloads import get

METRICS = {
    "energy_dyn_j": ("Dynamic energy", "J", "Package energy minus the idle baseline: what the computation added."),
    "energy_pkg_j": ("Package energy", "J", "Total CPU-package energy over the run (RAPL)."),
    "energy_model_j": ("Model estimate", "J", "Software model: TDP share x CPU time + DRAM heuristic."),
    "duration_s": ("Duration", "s", "Wall-clock time of the measured region."),
    "cpu_s": ("CPU time", "s", "User + system CPU time of the run process (all threads)."),
    "peak_rss_mb": ("Peak memory", "MB", "Peak resident memory of the run process."),
    "avg_power_w": ("Average power", "W", "Package energy divided by duration."),
}
ALPHA = 0.05
# A run is noisy when other processes used at least one core more than during the idle baseline.
# Windows CPU-time counters tick every 15.6 ms, hence the absolute floor.
NOISY_EXTRA_CORES = 1.0
NOISY_MIN_CPU_S = 0.05


def load_runs(cdir: Path) -> list[dict]:
    runs = []
    path = cdir / "runs.jsonl"
    if not path.exists():
        return runs
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            runs.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # partially written last line of a running campaign
    return runs


def idle_power(campaign: dict) -> float | None:
    vals = [m["average"]["pkg_w"] for m in campaign.get("idle", []) if m.get("average", {}).get("pkg_w")]
    return float(np.median(vals)) if vals else None


def idle_background_cores(campaign: dict) -> float:
    pct = [m["system_cpu_percent"] for m in campaign.get("idle", []) if m.get("system_cpu_percent") is not None]
    return float(np.median(pct)) / 100 * campaign["environment"]["cpu"]["logical_cpus"] if pct else 0.0


def is_noisy(run: dict, idle_bg_cores: float) -> bool:
    bg = run.get("background_cpu_s", 0.0)
    return bg > NOISY_MIN_CPU_S and bg / max(run["duration_s"], 1e-9) - idle_bg_cores > NOISY_EXTRA_CORES


def derive(run: dict, idle_w: float | None) -> dict:
    d = {"duration_s": run["duration_s"], "cpu_s": run["cpu_s"], "peak_rss_mb": run["peak_rss_mb"],
         "energy_model_j": run["energy_model_j"]["total"]}
    pkg = (run.get("energy_j") or {}).get("pkg")
    if pkg is not None:
        d["energy_pkg_j"] = pkg
        d["avg_power_w"] = pkg / run["duration_s"] if run["duration_s"] > 0 else None
        if idle_w is not None:
            d["energy_dyn_j"] = pkg - idle_w * run["duration_s"]
    return d


def _phase_table(runs: list[dict], idle_w: float | None) -> dict:
    out: dict[str, dict] = {}
    names = [p["name"] for p in runs[0]["phases"]] if runs else []
    for name in names:
        dur = [p["duration_s"] for r in runs for p in r["phases"] if p["name"] == name]
        pkg = [p["energy_j"].get("pkg") for r in runs for p in r["phases"] if p["name"] == name]
        row = {"duration_s": float(np.median(dur))}
        if pkg and pkg[0] is not None:
            row["energy_pkg_j"] = float(np.median(pkg))
            if idle_w is not None:
                row["energy_dyn_j"] = float(np.median([e - idle_w * t for e, t in zip(pkg, dur)]))
        out[name] = row
    return out


def _pct(ratio: float) -> float:
    return (ratio - 1.0) * 100.0


def analyze_campaign(cdir: Path, write: bool = True) -> dict:
    cdir = Path(cdir)
    campaign = json.loads((cdir / "campaign.json").read_text(encoding="utf-8"))
    runs = load_runs(cdir)
    idle_w = idle_power(campaign)
    idle_bg = idle_background_cores(campaign)
    has_hw = any((r.get("energy_j") or {}).get("pkg") is not None for r in runs if r.get("status") == "ok")
    primary = "energy_dyn_j" if has_hw and idle_w is not None else "energy_model_j"
    rng = np.random.default_rng(7)

    measured = [r for r in runs if not r.get("warmup")]
    good = [r for r in measured if r.get("status") == "ok"]
    by_cfg: dict[str, list[dict]] = {}
    for r in good:
        by_cfg.setdefault(r["config"], []).append(r)

    configs = {}
    for c in campaign["configs"]:
        rs = by_cfg.get(c["key"], [])
        all_rs = [r for r in measured if r.get("config") == c["key"]]
        derived = [derive(r, idle_w) for r in rs]
        metrics = {}
        for m in METRICS:
            vals = [d[m] for d in derived if d.get(m) is not None]
            if vals:
                metrics[m] = describe(np.array(vals), rng)
        w = get(c["workload"])
        entry = {**c, "exact": w.variants[c["variant"]].exact, "n_runs": len(all_rs), "n_valid": len(rs),
                 "n_invalid": sum(r.get("status") == "invalid" for r in all_rs),
                 "n_errors": sum(r.get("status") == "error" for r in all_rs),
                 "n_noisy": sum(is_noisy(r, idle_bg) for r in rs),
                 "metrics": metrics, "phases": _phase_table(rs, idle_w) if rs else {}}
        acc = [r["accuracy"] for r in rs if r.get("accuracy")]
        if acc:
            entry["accuracy"] = {k: {"mape": float(np.median([a[k]["mape"] for a in acc])),
                                     "p95_ape": float(np.median([a[k]["p95_ape"] for a in acc]))}
                                 for k in acc[0]}
        configs[c["key"]] = entry

    studies = [_study(sid, s, configs, primary, rng) for sid, s in campaign["studies"].items()]
    meter_check = _meter_check(good, idle_w)
    if meter_check is not None:
        meter_check["verdicts"] = _model_reversals(configs, studies)
    analysis = {
        "campaign_id": campaign["id"], "generated_at": datetime.now(timezone.utc).isoformat(),
        "primary_metric": primary, "metrics": {k: {"label": v[0], "unit": v[1], "description": v[2]}
                                              for k, v in METRICS.items()},
        "idle_w": idle_w, "idle_drift_w": _idle_drift(campaign), "idle_background_cores": idle_bg,
        "configs": list(configs.values()), "studies": studies,
        "recommendations": [rec for s in studies for rec in s["recommendations"]],
        "meter_check": meter_check,
        "quality": {"runs": len(measured), "valid": len(good),
                    "invalid": sum(r.get("status") == "invalid" for r in measured),
                    "errors": sum(r.get("status") == "error" for r in runs),
                    "noisy": sum(c["n_noisy"] for c in configs.values()),
                    "median_cv": _median_cv(configs, primary)},
        "totals": {"energy_pkg_j": float(sum((r.get("energy_j") or {}).get("pkg") or 0 for r in runs)),
                   "measured_seconds": float(sum(r.get("duration_s") or 0 for r in runs))},
    }
    if write:
        (cdir / "analysis.json").write_text(json.dumps(analysis, indent=1), encoding="utf-8")
    return analysis


def _idle_drift(campaign: dict) -> float | None:
    vals = [m["average"]["pkg_w"] for m in campaign.get("idle", []) if m.get("average", {}).get("pkg_w")]
    return float(max(vals) - min(vals)) if len(vals) > 1 else None


def _median_cv(configs: dict, metric: str) -> float | None:
    cvs = [c["metrics"][metric]["cv"] for c in configs.values()
           if metric in c["metrics"] and c["metrics"][metric].get("cv") is not None]
    return float(np.median(cvs)) if cvs else None


def _meter_check(runs: list[dict], idle_w: float | None) -> dict | None:
    pairs = [(derive(r, idle_w).get("energy_dyn_j"), r["energy_model_j"]["total"], (r.get("energy_j") or {}).get("pkg"))
             for r in runs]
    pairs = [p for p in pairs if p[0] is not None and p[2] is not None]
    if len(pairs) < 5:
        return None
    dyn, model, pkg = (np.array(v) for v in zip(*pairs))
    rho = sstats.spearmanr(model, dyn).statistic
    r = sstats.pearsonr(model, dyn).statistic
    pos = dyn > 0
    return {"n": len(pairs), "spearman_model_vs_dynamic": float(rho), "pearson_model_vs_dynamic": float(r),
            "median_ratio_model_over_dynamic": float(np.median(model[pos] / dyn[pos])) if pos.any() else None,
            "median_ratio_model_over_package": float(np.median(model / pkg)),
            "points": [{"model": float(a), "dynamic": float(b)} for a, b in zip(model[:400], dyn[:400])]}


def _model_reversals(configs: dict, studies: list[dict]) -> dict:
    """Would the software model have reached the same verdicts as the hardware counter?

    For every pair of configurations in a study group that the hardware separates (Mann-Whitney
    p < 0.05 on dynamic energy), check the model's verdict. A reversal is a pair the model also
    separates significantly, but in the opposite direction.
    """
    pairs, agree, reversals = 0, 0, []
    for s in studies:
        for g in s["groups"]:
            keys = [r["key"] for r in g["rows"] if "energy_dyn_j" in configs[r["key"]]["metrics"]]
            for i, a in enumerate(keys):
                for b in keys[i + 1:]:
                    hw_a, hw_b = (np.array(configs[k]["metrics"]["energy_dyn_j"]["values"]) for k in (a, b))
                    mo_a, mo_b = (np.array(configs[k]["metrics"]["energy_model_j"]["values"]) for k in (a, b))
                    if mann_whitney_p(hw_a, hw_b) >= ALPHA:
                        continue
                    pairs += 1
                    hw_dir = np.sign(np.median(hw_a) - np.median(hw_b))
                    mo_dir = np.sign(np.median(mo_a) - np.median(mo_b))
                    if hw_dir == mo_dir:
                        agree += 1
                    elif mann_whitney_p(mo_a, mo_b) < ALPHA:
                        label = lambda k: configs[k]["labels"].get(s["id"], configs[k]["label"])  # noqa: E731
                        reversals.append({
                            "study": s["id"], "a": label(a), "b": label(b),
                            "hardware_ratio": float(np.median(hw_a) / np.median(hw_b)),
                            "model_ratio": float(np.median(mo_a) / np.median(mo_b))})
    return {"hardware_significant_pairs": pairs, "model_agrees": agree, "model_reverses": len(reversals),
            "reversals": reversals}


def _matches(params: dict, variant: str, cond: dict) -> bool:
    return all((variant if k == "variant" else params.get(k)) == v for k, v in cond.items())


def _study(sid: str, s: dict, configs: dict, metric: str, rng) -> dict:
    keys = [k for k in s["configs"] if k in configs]
    group_by = s.get("group_by") or []
    groups: dict[tuple, list[str]] = {}
    for k in keys:
        c = configs[k]
        groups.setdefault(tuple(c["params"][g] for g in group_by), []).append(k)

    out_groups, pvals, cells = [], [], []
    for gvals, gkeys in groups.items():
        ok = [k for k in gkeys if metric in configs[k]["metrics"]]
        base_key = None
        for cond in [s["baseline"], *s.get("fallback_baselines", [])]:
            base_key = next((k for k in ok if _matches(configs[k]["params"], configs[k]["variant"], cond)), None)
            if base_key:
                break
        rows = []
        for k in gkeys:
            c = configs[k]
            row = {"key": k, "label": c["labels"].get(sid, c["label"]), "variant": c["variant"],
                   "is_baseline": k == base_key, "skipped": c.get("skipped"), "exact": c["exact"]}
            if metric in c["metrics"]:
                row["energy"] = {m: c["metrics"][m]["median"] for m in ("energy_dyn_j", "energy_pkg_j", "energy_model_j")
                                 if m in c["metrics"]}
                row["duration_s"] = c["metrics"]["duration_s"]["median"]
            if base_key and k != base_key and metric in c["metrics"]:
                x = np.array(c["metrics"][metric]["values"])
                b = np.array(configs[base_key]["metrics"][metric]["values"])
                ratio, lo, hi = ratio_of_medians(x, b, rng)
                dx = np.array(c["metrics"]["duration_s"]["values"])
                db = np.array(configs[base_key]["metrics"]["duration_s"]["values"])
                dratio, dlo, dhi = ratio_of_medians(dx, db, rng)
                delta = cliffs_delta(x, b)
                p = mann_whitney_p(x, b)
                row.update({"energy_ratio": ratio, "energy_ratio_ci": [lo, hi], "energy_change_pct": _pct(ratio),
                            "energy_change_ci_pct": [_pct(lo), _pct(hi)], "duration_ratio": dratio,
                            "duration_ratio_ci": [dlo, dhi], "duration_change_pct": _pct(dratio),
                            "p_value": p, "cliffs_delta": delta, "magnitude": magnitude(delta)})
                if "energy_pkg_j" in c["metrics"] and "energy_pkg_j" in configs[base_key]["metrics"]:
                    t_ratio, _, _ = ratio_of_medians(np.array(c["metrics"]["energy_pkg_j"]["values"]),
                                                     np.array(configs[base_key]["metrics"]["energy_pkg_j"]["values"]),
                                                     rng)
                    row["package_energy_change_pct"] = _pct(t_ratio)
                pvals.append(p)
                cells.append(row)
            rows.append(row)
        _mark_pareto(rows)
        out_groups.append({"group": dict(zip(group_by, gvals)), "baseline": base_key, "rows": rows})

    for row, padj in zip(cells, holm(pvals)):
        row["p_adj"] = padj
        row["significant"] = bool(np.isfinite(padj) and padj < ALPHA)

    study = {"id": sid, "title": s["title"], "question": s["question"], "workload": s["workload"],
             "factors": s["factors"], "baseline": s["baseline"], "group_by": group_by, "groups": out_groups}
    study["recommendations"] = _recommend(study, configs, metric)
    study["insights"] = _insights(study, configs, metric)
    return study


def _mark_pareto(rows: list[dict]) -> None:
    pts = [(r["energy"].get("energy_dyn_j", r["energy"].get("energy_model_j")), r["duration_s"])
           for r in rows if "energy" in r]
    for r in rows:
        if "energy" not in r:
            continue
        e = r["energy"].get("energy_dyn_j", r["energy"].get("energy_model_j"))
        t = r["duration_s"]
        r["pareto"] = not any((pe <= e and pt <= t) and (pe < e or pt < t) for pe, pt in pts)


def _fmt_pct(v: float) -> str:
    return f"{abs(v):.0f}%" if abs(v) >= 10 else f"{abs(v):.1f}%"


def _latency_phrase(change: float) -> str:
    if abs(change) < 2:
        return "at the same speed"
    return f"while running {_fmt_pct(change)} faster" if change < 0 else f"for a {_fmt_pct(change)} latency cost"


def _accuracy_note(c: dict) -> str:
    acc = c.get("accuracy") or {}
    worst = max(acc.items(), key=lambda kv: kv[1]["mape"], default=None)
    if not worst:
        return ""
    return f", with a {worst[1]['mape'] * 100:.1f}% mean error on {worst[0].replace('_', ' ')}"


def _recommend(study: dict, configs: dict, metric: str) -> list[dict]:
    """One recommendation per group, of one of four kinds:

    switch       an exact alternative uses significantly less energy than the baseline
    keep         the baseline wins: even the best alternative uses significantly more energy
    inconclusive no significant difference either way
    trade-off    an approximate variant saves energy at a measured accuracy cost
    """
    recs = []
    for g in study["groups"]:
        base = g["baseline"]
        cands = [r for r in g["rows"] if not r["is_baseline"] and "energy_change_pct" in r]
        if not base or not cands:
            continue
        base_label = next(r["label"] for r in g["rows"] if r["is_baseline"])
        exact = [r for r in cands if r["exact"]]
        best = min(exact, key=lambda r: r["energy_change_pct"], default=None)
        if best is not None:
            sig = best.get("significant", False)
            change = best["energy_change_pct"]
            if sig and change < 0:
                kind = "switch"
                text = (f"{best['label']} cuts energy by {_fmt_pct(change)} versus {base_label} "
                        f"{_latency_phrase(best['duration_change_pct'])}.")
            elif sig:
                kind = "keep"
                text = (f"Keep {base_label}: every alternative uses more energy. The closest, {best['label']}, "
                        f"costs {_fmt_pct(change)} more {_latency_phrase(best['duration_change_pct'])}.")
            else:
                kind = "inconclusive"
                text = (f"{best['label']} and {base_label} are statistically indistinguishable on energy "
                        f"({change:+.1f}%, not significant): choose on other criteria.")
            recs.append(_rec(study, g, best, base, base_label, kind, text, configs))
        # An approximate variant is only worth recommending if it also beats the best exact option.
        approx = min((r for r in cands if not r["exact"]), key=lambda r: r["energy_change_pct"], default=None)
        best_exact = best if best is not None and best["energy_change_pct"] < 0 else \
            next(r for r in g["rows"] if r["is_baseline"])
        if approx is not None and approx.get("significant") and approx["energy_change_pct"] < 0 \
                and _median(configs, approx["key"], metric) < _median(configs, best_exact["key"], metric) \
                and _differs(configs, approx["key"], best_exact["key"], metric):
            gain = (1 - _median(configs, approx["key"], metric) / _median(configs, best_exact["key"], metric)) * 100
            text = (f"{approx['label']} cuts energy by {_fmt_pct(approx['energy_change_pct'])} versus {base_label} "
                    f"{_latency_phrase(approx['duration_change_pct'])}{_accuracy_note(configs[approx['key']])}; "
                    f"that is {gain:.0f}% below the best exact option, {best_exact['label']}.")
            recs.append(_rec(study, g, approx, base, base_label, "trade-off", text, configs))
    return recs


def _median(configs: dict, key: str, metric: str) -> float:
    return configs[key]["metrics"][metric]["median"]


def _rec(study, g, row, base, base_label, kind, text, configs) -> dict:
    return {"study": study["id"], "group": g["group"], "kind": kind, "config": row["key"], "label": row["label"],
            "baseline": base, "baseline_label": base_label, "text": text,
            "significant": kind in ("switch", "keep", "trade-off"), "exact": row["exact"],
            "energy_change_pct": row["energy_change_pct"], "energy_change_ci_pct": row["energy_change_ci_pct"],
            "duration_change_pct": row["duration_change_pct"],
            "package_energy_change_pct": row.get("package_energy_change_pct"), "p_adj": row.get("p_adj"),
            "cliffs_delta": row["cliffs_delta"], "magnitude": row["magnitude"],
            "accuracy": configs[row["key"]].get("accuracy")}


def _differs(configs: dict, a: str, b: str, metric: str) -> bool:
    """Do two configurations differ on `metric` (Mann-Whitney p < 0.05 and at least a medium effect)?"""
    x = np.array(configs[a]["metrics"][metric]["values"])
    y = np.array(configs[b]["metrics"][metric]["values"])
    return mann_whitney_p(x, y) < ALPHA and abs(cliffs_delta(x, y)) >= 0.33


def _insights(study: dict, configs: dict, metric: str) -> list[str]:
    out = []
    for g in study["groups"]:
        rows = [r for r in g["rows"] if "energy" in r and metric in configs[r["key"]]["metrics"]]
        if len(rows) < 2:
            continue
        med = lambda r: configs[r["key"]]["metrics"][metric]["median"]  # noqa: E731
        exact = [r for r in rows if r["exact"]]
        fastest = min(exact, key=lambda r: r["duration_s"])
        greenest = min(exact, key=med)
        nq = g["group"].get("n_queries")
        where = f" at {nq:,} quer{'y' if nq == 1 else 'ies'}" if nq is not None else ""
        if fastest["key"] == greenest["key"]:
            out.append(f"{greenest['label']} is both the fastest and the most frugal exact option{where}.")
        elif _differs(configs, fastest["key"], greenest["key"], metric) \
                and _differs(configs, fastest["key"], greenest["key"], "duration_s"):
            dt = (greenest["duration_s"] / fastest["duration_s"] - 1) * 100
            de = (1 - med(greenest) / med(fastest)) * 100
            out.append(f"Fastest is not greenest{where}: {fastest['label']} finishes first, but "
                       f"{greenest['label']} uses {de:.0f}% less energy while taking {dt:.0f}% longer.")
        else:
            out.append(f"{fastest['label']} (fastest) and {greenest['label']} (most frugal) are statistically "
                       f"tied{where}: the difference between them is within measurement noise.")
        if "storage" in study["factors"]:
            shares = []
            for r in rows:
                phases = configs[r["key"]].get("phases", {})
                total = sum(max(0.0, p.get(metric) or 0.0) for p in phases.values())
                if total > 0:
                    shares.append((max(0.0, (phases.get("load") or {}).get(metric) or 0.0) / total, r["label"]))
            if len(shares) > 1:
                hi, lo = max(shares), min(shares)
                out.append(f"Reading the inputs takes {hi[0] * 100:.0f}% of the energy with {hi[1]} but only "
                           f"{lo[0] * 100:.0f}% with {lo[1]}: the format changes the cost of loading, not of computing.")
        if exact:
            for r in rows:
                if r["exact"]:
                    continue
                ratio = med(r) / med(greenest)
                acc = configs[r["key"]].get("accuracy") or {}
                worst = max(acc.items(), key=lambda kv: kv[1]["mape"], default=None)
                err = f", while erring by {worst[1]['mape'] * 100:.1f}% on {worst[0].replace('_', ' ')}" if worst else ""
                if not _differs(configs, r["key"], greenest["key"], metric):
                    out.append(f"{r['label']} uses no less energy than the best exact option, {greenest['label']}"
                               f"{err}: here approximation buys accuracy loss, not savings.")
                elif ratio > 1:
                    out.append(f"{r['label']} uses {ratio:.1f}× the energy of the exact {greenest['label']}"
                               f"{err}: approximate is not automatically greener.")
                else:
                    out.append(f"{r['label']} uses {(1 - ratio) * 100:.0f}% less energy than the best exact option, "
                               f"{greenest['label']}{err}.")
    out.extend(_break_even(study, configs, metric))
    return out


def _phase_energy(c: dict, phase: str, metric: str) -> float | None:
    p = c.get("phases", {}).get(phase)
    return None if not p else p.get(metric, p.get("energy_pkg_j"))


def _break_even(study: dict, configs: dict, metric: str) -> list[str]:
    """Queries needed before an index repays its build energy.

    Build energy is pooled over every query count (it does not depend on it); per-query energy
    comes from the largest query count, where it is least affected by meter noise.
    """
    if study["id"] not in ("text-search", "indexing") or metric != "energy_dyn_j":
        return []
    scan_v = "regex_scan" if study["id"] == "text-search" else "scan"
    members = [configs[r["key"]] for g in study["groups"] for r in g["rows"]
               if r["key"] in configs and configs[r["key"]].get("phases")]

    def costs(variant: str):
        cs = [c for c in members if c["variant"] == variant and "query" in c["phases"]]
        if not cs:
            return None
        build = float(np.median([_phase_energy(c, "build", metric) or 0.0 for c in cs]))
        big = max(cs, key=lambda c: int(c["params"]["n_queries"]))
        n = int(big["params"]["n_queries"])
        return build, (_phase_energy(big, "query", metric) or 0.0) / n, n

    scan = costs(scan_v)
    if not scan:
        return []
    w = get(study["workload"])
    out = []
    for v in [v for v in w.variants if v != scan_v]:
        idx = costs(v)
        if not idx:
            continue
        extra_build, saving = idx[0] - scan[0], scan[1] - idx[1]
        label = w.variants[v].label
        if saving <= 0:
            out.append(f"{label} never repays its build energy here: an indexed query costs as much as a scan.")
        elif extra_build <= 0:
            out.append(f"{label} is cheaper than scanning from the very first query.")
        else:
            at = f"{scan[2]:,} queries" if scan[2] == idx[2] else f"{scan[2]:,} and {idx[2]:,} queries"
            out.append(f"{label} repays its build energy after about {extra_build / saving:,.0f} queries: "
                       f"building costs {extra_build:.2f} J more than the scan's setup, then each query saves "
                       f"{saving * 1000:.2f} mJ (per-query costs measured at {at}).")
    return out
