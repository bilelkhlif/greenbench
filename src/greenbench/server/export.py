"""Static snapshot of the dashboard API, so the UI can be hosted without a server (GitHub Pages).

Every read-only response the dashboard uses is written to `<out>/<api path>.json`; the static build
of the web app reads those files instead of calling `/api`.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.encoders import jsonable_encoder


def export_static(out: Path) -> list[Path]:
    from greenbench.server import app as api

    summaries = api.campaigns()
    active = [s["id"] for s in summaries if s["status"].get("state") in api.ACTIVE_STATES]
    if active:
        raise RuntimeError(f"campaign {active[0]} is still running; export once it has finished")

    written: list[Path] = []

    def put(path: str, payload) -> None:
        target = out / f"{path}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(jsonable_encoder(payload), ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        target.write_text(text, encoding="utf-8")
        written.append(target)

    put("campaigns", summaries)
    for s in summaries:
        put(f"campaigns/{s['id']}", api.campaign(s["id"]))
        if s["quality"]:
            put(f"campaigns/{s['id']}/analysis", api.campaign_analysis(s["id"]))
    put("overview", api.overview())
    # Describe the machine that produced the results, not the one doing the export.
    analysed = [s for s in summaries if s["quality"]]
    put("environment", api.campaign(analysed[0]["id"])["environment"] if analysed else api.environment())
    put("workloads", api.workloads())
    put("studies", api.studies())
    put("presets", api.presets())
    put("roadmap", api.get_roadmap())
    docs = api.docs()
    put("docs", docs)
    for d in docs:
        if d["available"]:
            put(f"docs/{d['slug']}", api.doc(d["slug"]))
    return written
