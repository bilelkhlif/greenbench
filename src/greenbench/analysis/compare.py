"""Cross-machine comparison: do the verdicts of one campaign hold on another machine?

Week 9 of the roadmap compares the reference laptop (machine A) with a second machine
(machine B, Linux/Intel). Absolute joules are not comparable across CPUs, so the comparison
works on what the recommendations are made of: for every study comparison present in both
campaigns (same configuration key, same baseline), the energy ratio versus the baseline and
its significance. Each comparison gets a verdict per machine:

    lower   significantly less energy than the baseline (Holm-corrected p < 0.05)
    higher  significantly more energy than the baseline
    tie     no significant difference

and the pair of verdicts is classified as

    agree     same verdict on both machines
    partial   significant on one machine, a tie on the other
    reversal  significant on both, in opposite directions

Campaign files are only read, never rewritten. Usage:

    python -m greenbench.analysis.compare <campaign-A> <campaign-B> [--out comparison.md]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from scipy import stats as sstats


def _load(cdir: Path) -> tuple[dict, dict]:
    cdir = Path(cdir)
    campaign = json.loads((cdir / "campaign.json").read_text(encoding="utf-8"))
    path = cdir / "analysis.json"
    if path.exists():
        analysis = json.loads(path.read_text(encoding="utf-8"))
    else:
        from greenbench.analysis.analyze import analyze_campaign

        analysis = analyze_campaign(cdir, write=False)
    return campaign, analysis


def verdict(row: dict) -> str:
    if not row.get("significant"):
        return "tie"
    return "lower" if row["energy_change_pct"] < 0 else "higher"


def agreement(a: str, b: str) -> str:
    if a == b:
        return "agree"
    if "tie" in (a, b):
        return "partial"
    return "reversal"


def _machine(campaign: dict, analysis: dict) -> dict:
    env = campaign.get("environment", {})
    meter = campaign.get("primary_meter") or {}
    cfg = campaign.get("config", {})
    return {"campaign_id": campaign.get("id"), "cpu": env.get("cpu", {}).get("name"),
            "os": " ".join(str(v) for v in (env.get("os", {}).get("system"), env.get("os", {}).get("release")) if v),
            "logical_cpus": env.get("cpu", {}).get("logical_cpus"), "meter": meter.get("interface", meter.get("name")),
            "power_plan": env.get("power", {}).get("plan"), "virtualized": env.get("virtualization", {}).get("virtualized"),
            "preset": cfg.get("preset"), "scale": cfg.get("scale"), "repetitions": cfg.get("repetitions"),
            "primary_metric": analysis.get("primary_metric"), "idle_w": analysis.get("idle_w")}


def _rows(analysis: dict) -> dict[tuple[str, str], dict]:
    """Comparison rows (non-baseline, measured) keyed by (study id, config key)."""
    out = {}
    for s in analysis.get("studies", []):
        for g in s["groups"]:
            for r in g["rows"]:
                if "energy_change_pct" in r:
                    out[(s["id"], r["key"])] = {**r, "baseline": g["baseline"], "group": g["group"],
                                                "study_title": s["title"]}
    return out


def _best(analysis: dict) -> dict[tuple, str | None]:
    """Recommended exact configuration of each (study, group): the switch target, else the baseline."""
    out = {}
    for rec in analysis.get("recommendations", []):
        if not rec.get("exact"):
            continue
        key = (rec["study"], json.dumps(rec["group"], sort_keys=True))
        out[key] = rec["config"] if rec["kind"] == "switch" else (rec["baseline"] if rec["kind"] == "keep" else None)
    return out


def compare_campaigns(dir_a: Path, dir_b: Path) -> dict:
    camp_a, an_a = _load(dir_a)
    camp_b, an_b = _load(dir_b)
    rows_a, rows_b = _rows(an_a), _rows(an_b)
    shared = [k for k in rows_a if k in rows_b and rows_a[k]["baseline"] == rows_b[k]["baseline"]]

    comparisons = []
    for sid, key in shared:
        ra, rb = rows_a[(sid, key)], rows_b[(sid, key)]
        va, vb = verdict(ra), verdict(rb)
        comparisons.append({
            "study": sid, "study_title": ra["study_title"], "group": ra["group"], "config": key,
            "label": ra["label"], "baseline": ra["baseline"], "exact": ra.get("exact", True),
            "a": {"energy_change_pct": ra["energy_change_pct"], "energy_change_ci_pct": ra.get("energy_change_ci_pct"),
                  "duration_change_pct": ra.get("duration_change_pct"), "p_adj": ra.get("p_adj"), "verdict": va},
            "b": {"energy_change_pct": rb["energy_change_pct"], "energy_change_ci_pct": rb.get("energy_change_ci_pct"),
                  "duration_change_pct": rb.get("duration_change_pct"), "p_adj": rb.get("p_adj"), "verdict": vb},
            "agreement": agreement(va, vb),
        })

    studies = []
    for sid in dict.fromkeys(c["study"] for c in comparisons):
        cs = [c for c in comparisons if c["study"] == sid]
        studies.append({"id": sid, "title": cs[0]["study_title"], "n": len(cs),
                        **{k: sum(c["agreement"] == k for c in cs) for k in ("agree", "partial", "reversal")}})

    best_a, best_b = _best(an_a), _best(an_b)
    recommendations = []
    for k in best_a:
        if k in best_b:
            recommendations.append({"study": k[0], "group": json.loads(k[1]), "a": best_a[k], "b": best_b[k],
                                    "same": best_a[k] == best_b[k]})

    ratios = np.array([[c["a"]["energy_change_pct"], c["b"]["energy_change_pct"]] for c in comparisons])
    rank = None
    if len(ratios) >= 3 and np.ptp(ratios[:, 0]) > 0 and np.ptp(ratios[:, 1]) > 0:
        rank = float(sstats.spearmanr(ratios[:, 0], ratios[:, 1]).statistic)
    n = len(comparisons)
    summary = {"comparisons": n, "only_in_a": len(rows_a) - n, "only_in_b": len(rows_b) - n,
               **{k: sum(c["agreement"] == k for c in comparisons) for k in ("agree", "partial", "reversal")},
               "agreement_rate": (sum(c["agreement"] == "agree" for c in comparisons) / n) if n else None,
               "spearman_energy_change": rank,
               "same_recommendation": sum(r["same"] for r in recommendations),
               "recommendation_groups": len(recommendations)}
    return {"a": _machine(camp_a, an_a), "b": _machine(camp_b, an_b), "summary": summary, "studies": studies,
            "comparisons": comparisons, "recommendations": recommendations}


def _pct(v) -> str:
    return "–" if v is None else f"{v:+.1f}%"


def _ci(ci) -> str:
    return "" if not ci else f" [{ci[0]:+.0f}, {ci[1]:+.0f}]"


def to_markdown(cmp: dict) -> str:
    a, b, s = cmp["a"], cmp["b"], cmp["summary"]
    lines = ["# Cross-machine comparison", "",
             "| | Machine A | Machine B |", "|---|---|---|"]
    for field, label in [("campaign_id", "Campaign"), ("cpu", "CPU"), ("os", "OS"), ("logical_cpus", "Logical CPUs"),
                         ("meter", "Meter"), ("power_plan", "Power plan / governor"), ("virtualized", "Virtualised"),
                         ("preset", "Preset"), ("repetitions", "Repetitions"), ("primary_metric", "Primary metric")]:
        lines.append(f"| {label} | {a.get(field, '–')} | {b.get(field, '–')} |")
    rate = "–" if s["agreement_rate"] is None else f"{s['agreement_rate'] * 100:.0f}%"
    rho = "–" if s["spearman_energy_change"] is None else f"{s['spearman_energy_change']:.2f}"
    lines += ["", f"**{s['comparisons']} comparisons in common**: {s['agree']} agree ({rate}), "
              f"{s['partial']} significant on one machine only, **{s['reversal']} reversed**. "
              f"Rank correlation of the energy changes across machines: Spearman ρ = {rho}. "
              f"Same recommended configuration in {s['same_recommendation']} of {s['recommendation_groups']} groups.", ""]
    if s["only_in_a"] or s["only_in_b"]:
        lines += [f"Not compared: {s['only_in_a']} comparisons only in A, {s['only_in_b']} only in B "
                  "(different studies, skipped or failed configurations).", ""]
    lines += ["| Study | Comparisons | Agree | Partial | Reversal |", "|---|---|---|---|---|"]
    lines += [f"| {st['title']} | {st['n']} | {st['agree']} | {st['partial']} | {st['reversal']} |"
              for st in cmp["studies"]]
    lines += ["", "## Every comparison", "",
              "Energy change versus the study baseline, with its 95 % CI; verdict after Holm correction.", "",
              "| Study | Configuration | Group | A | B | Verdict A / B | |", "|---|---|---|---|---|---|---|"]
    for c in cmp["comparisons"]:
        group = ", ".join(f"{k}={v}" for k, v in c["group"].items()) or "–"
        flag = {"agree": "✔", "partial": "≈", "reversal": "✘ reversal"}[c["agreement"]]
        lines.append(f"| {c['study']} | {c['label']} | {group} | {_pct(c['a']['energy_change_pct'])}"
                     f"{_ci(c['a']['energy_change_ci_pct'])} | {_pct(c['b']['energy_change_pct'])}"
                     f"{_ci(c['b']['energy_change_ci_pct'])} | {c['a']['verdict']} / {c['b']['verdict']} | {flag} |")
    return "\n".join(lines) + "\n"


def _resolve(ref: str) -> Path:
    p = Path(ref)
    if (p / "campaign.json").exists():
        return p
    from greenbench.paths import results_dir

    q = results_dir() / ref
    if (q / "campaign.json").exists():
        return q
    sys.exit(f"campaign {ref!r} not found (give a directory or an id under {results_dir()})")


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="python -m greenbench.analysis.compare",
                                description="Compare the verdicts of two campaigns (e.g. two machines).")
    p.add_argument("a", help="campaign directory or id (machine A)")
    p.add_argument("b", help="campaign directory or id (machine B)")
    p.add_argument("--out", help="write the Markdown comparison to this file (default: print it)")
    p.add_argument("--json", help="also write the full comparison as JSON to this file")
    args = p.parse_args(argv)
    cmp = compare_campaigns(_resolve(args.a), _resolve(args.b))
    md = to_markdown(cmp)
    if args.json:
        Path(args.json).write_text(json.dumps(cmp, indent=1), encoding="utf-8")
    if args.out:
        Path(args.out).write_text(md, encoding="utf-8")
        print(f"comparison written to {args.out}")
    else:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(errors="replace")
        print(md)


if __name__ == "__main__":
    main()
