import json
from collections import Counter

from greenbench.protocol.plan import STUDIES, expand, schedule


def test_shared_configurations_are_measured_once():
    configs, members = expand(["join-algorithms", "storage-formats"])
    keys = [c.key for c in configs]
    assert len(keys) == len(set(keys))
    shared = set(members["join-algorithms"]) & set(members["storage-formats"])
    assert len(shared) == 1  # hash join, 1 thread, Parquet + Snappy
    (key,) = shared
    cfg = next(c for c in configs if c.key == key)
    assert cfg.labels["join-algorithms"] != cfg.labels["storage-formats"]


def test_schedule_is_balanced_randomised_and_skips_inapplicable():
    configs, _ = expand(list(STUDIES))
    plan = schedule(configs, repetitions=3, warmups=1, seed=42)
    runnable = [c.key for c in configs if not c.skipped]
    measured = Counter(p["config"] for p in plan if not p["warmup"])
    assert set(measured) == set(runnable) and set(measured.values()) == {3}
    rounds = [[p["config"] for p in plan if p["round"] == r] for r in range(3)]
    assert rounds[0] != rounds[1]  # fresh order every round
    assert any(c.skipped for c in configs)


def test_tiny_campaign_end_to_end(tiny_dir):
    from greenbench.protocol.runner import CampaignConfig, Runner

    cfg = CampaignConfig(preset="quick", studies=["streaming-windows"], scale="tiny", repetitions=2, warmups=0,
                         cooldown_s=0, idle_s=0, campaign_id="pytest-e2e")
    out = Runner(cfg, log=lambda *_: None).run()
    runs = [json.loads(line) for line in (out / "runs.jsonl").read_text().splitlines()]
    assert len(runs) == 8 and all(r["status"] == "ok" for r in runs)
    analysis = json.loads((out / "analysis.json").read_text())
    assert analysis["quality"]["valid"] == 8
    study = analysis["studies"][0]
    assert study["groups"][0]["baseline"].startswith("streaming/batch_recompute")
    assert (out / "status.json").exists()
