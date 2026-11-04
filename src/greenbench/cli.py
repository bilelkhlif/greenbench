"""Command-line interface: `greenbench <command>` (or `python -m greenbench <command>`)."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from greenbench import __version__


def _campaign_dir(ref: str) -> Path:
    from greenbench.paths import results_dir

    root = results_dir()
    if ref == "latest":
        dirs = sorted((d for d in root.glob("*") if (d / "campaign.json").exists()), key=lambda d: d.name)
        if not dirs:
            sys.exit("no campaign found in " + str(root))
        return dirs[-1]
    path = root / ref
    if not (path / "campaign.json").exists():
        sys.exit(f"campaign {ref!r} not found in {root}")
    return path


def cmd_env(args) -> None:
    from greenbench.environment import fingerprint

    print(json.dumps(fingerprint(), indent=2))


def cmd_meter(args) -> None:
    """Print live package power: a quick way to see the meter react to load."""
    from greenbench.meters import open_meter

    meter = open_meter(args.meter)
    if meter is None:
        sys.exit("no hardware energy meter available on this machine (the software model will be used)")
    print(f"{meter.describe().get('interface', meter.name)}: domains {', '.join(meter.domains)}")
    for _ in range(args.seconds):
        p = meter.power_w(1.0)
        print("  " + "   ".join(f"{d}: {w:6.2f} W" for d, w in p.items()))
    meter.close()


def cmd_datasets(args) -> None:
    from greenbench.data.generate import TABLES, ensure_dataset, storage_sizes
    from greenbench.data.storage import STORAGES

    d = ensure_dataset(args.scale, {(t, s) for t in TABLES for s in STORAGES} if args.all_storages else None)
    for table, sizes in storage_sizes(d).items():
        print(f"{table:10s} " + "  ".join(f"{s}={b / 2**20:.1f}MB" for s, b in sizes.items()))


def cmd_list(args) -> None:
    from greenbench.protocol.plan import PRESETS, STUDIES, expand
    from greenbench.workloads import WORKLOADS

    print("Workloads:")
    for w in WORKLOADS.values():
        print(f"  {w.name:12s} {w.title}: " + ", ".join(w.variants))
    print("Studies:")
    for s in STUDIES.values():
        configs, _ = expand([s.id])
        print(f"  {s.id:18s} {len(configs):2d} configs  {s.question}")
    print("Presets:")
    for p in PRESETS.values():
        print(f"  {p.name:9s} scale={p.scale:6s} reps={p.repetitions:2d} warm-ups={p.warmups}  {p.description}")


def cmd_run(args) -> None:
    from greenbench.protocol.plan import STUDIES
    from greenbench.protocol.runner import CampaignConfig, Runner

    studies = args.studies.split(",") if args.studies else list(STUDIES)
    cfg = CampaignConfig(preset=args.preset, studies=studies, scale=args.scale, repetitions=args.repetitions,
                         warmups=args.warmups, cooldown_s=args.cooldown, meter=args.meter, seed=args.seed,
                         notes=args.notes or "", campaign_id=args.id)
    t0 = time.perf_counter()
    out = Runner(cfg, log=lambda m: print(m, flush=True)).run()
    print(f"done in {(time.perf_counter() - t0) / 60:.1f} min -> {out}")


def cmd_analyze(args) -> None:
    from greenbench.analysis.analyze import analyze_campaign

    a = analyze_campaign(_campaign_dir(args.campaign))
    print(f"primary metric: {a['primary_metric']}, idle {a['idle_w']:.2f} W" if a["idle_w"] else
          f"primary metric: {a['primary_metric']}")
    for rec in a["recommendations"]:
        print(" *", rec["text"])
    for s in a["studies"]:
        for line in s["insights"]:
            print(" -", line)


def cmd_report(args) -> None:
    from greenbench.analysis.report import write_report

    path = write_report(_campaign_dir(args.campaign), Path(args.out) if args.out else None)
    print(f"report written to {path}")


def cmd_serve(args) -> None:
    import uvicorn

    print(f"GreenBench dashboard on http://{args.host}:{args.port}")
    uvicorn.run("greenbench.server.app:app", host=args.host, port=args.port, log_level="warning")


def cmd_export_static(args) -> None:
    from greenbench.server.export import export_static

    try:
        files = export_static(Path(args.out))
    except RuntimeError as exc:
        sys.exit(str(exc))
    print(f"{len(files)} API snapshots written to {args.out}")


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="greenbench", description="Energy benchmarking of data-processing algorithms.")
    p.add_argument("--version", action="version", version=f"greenbench {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("env", help="print the machine fingerprint and available meters").set_defaults(fn=cmd_env)

    s = sub.add_parser("meter", help="print live package power for a few seconds")
    s.add_argument("--seconds", type=int, default=5)
    s.add_argument("--meter", default="auto", choices=["auto", "emi", "rapl"])
    s.set_defaults(fn=cmd_meter)

    s = sub.add_parser("datasets", help="generate the synthetic multi-source datasets")
    s.add_argument("--scale", default="medium", choices=["tiny", "small", "medium"])
    s.add_argument("--all-storages", action="store_true", help="also write every format/compression copy")
    s.set_defaults(fn=cmd_datasets)

    sub.add_parser("list", help="list workloads, studies and presets").set_defaults(fn=cmd_list)

    s = sub.add_parser("run", help="run a measurement campaign")
    s.add_argument("--preset", default="standard", choices=["quick", "standard", "full"])
    s.add_argument("--studies", help="comma-separated study ids (default: all)")
    s.add_argument("--scale", choices=["tiny", "small", "medium"])
    s.add_argument("--repetitions", type=int)
    s.add_argument("--warmups", type=int)
    s.add_argument("--cooldown", type=float)
    s.add_argument("--meter", default="auto", choices=["auto", "emi", "rapl", "model"])
    s.add_argument("--seed", type=int)
    s.add_argument("--id", help="campaign id (default: timestamp-preset)")
    s.add_argument("--notes")
    s.set_defaults(fn=cmd_run)

    s = sub.add_parser("analyze", help="(re)compute the statistics of a campaign")
    s.add_argument("campaign", nargs="?", default="latest")
    s.set_defaults(fn=cmd_analyze)

    s = sub.add_parser("report", help="write a Markdown results report for a campaign")
    s.add_argument("campaign", nargs="?", default="latest")
    s.add_argument("--out")
    s.set_defaults(fn=cmd_report)

    s = sub.add_parser("serve", help="start the dashboard")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)
    s.set_defaults(fn=cmd_serve)

    s = sub.add_parser("export-static", help="write the dashboard's API responses as JSON files (for static hosting)")
    s.add_argument("out", help="output directory, e.g. web/dist-pages/data")
    s.set_defaults(fn=cmd_export_static)

    args = p.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):  # labels use "·" and "⋈"; never crash a cp1252 console
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    args.fn(args)


if __name__ == "__main__":
    main()
