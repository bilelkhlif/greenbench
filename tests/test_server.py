import json

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client(tiny_dir):
    """A server over a private results directory holding one tiny, analysed campaign."""
    from greenbench.protocol.runner import CampaignConfig, Runner

    Runner(CampaignConfig(preset="quick", studies=["indexing"], scale="tiny", repetitions=2, warmups=0,
                          cooldown_s=0, idle_s=0, campaign_id="pytest-server"), log=lambda *_: None).run()
    from greenbench.server.app import app

    return TestClient(app)


def test_catalogue_endpoints(client):
    assert {w["name"] for w in client.get("/api/workloads").json()} == {"joins", "text_search", "streaming", "indexing"}
    assert len(client.get("/api/studies").json()) == 5
    assert {p["name"] for p in client.get("/api/presets").json()} == {"quick", "standard", "full"}
    assert client.get("/api/roadmap").json()["current_week"] == 7


def test_campaign_endpoints(client):
    campaigns = client.get("/api/campaigns").json()
    summary = next(c for c in campaigns if c["id"] == "pytest-server")
    assert summary["status"]["state"] == "completed"
    assert summary["n_configs"] == 5  # 6 configurations, the 100,000-query scan is skipped
    analysis = client.get("/api/campaigns/pytest-server/analysis").json()
    assert analysis["quality"]["invalid"] == 0
    assert analysis["studies"][0]["id"] == "indexing"
    runs = client.get("/api/campaigns/pytest-server/runs").json()
    assert len(runs) == 10 and all(r["status"] == "ok" for r in runs)
    assert client.get("/api/campaigns/nope/analysis").status_code == 404


def test_overview_and_docs(client):
    ov = client.get("/api/overview").json()
    assert ov["latest"]["id"] == "pytest-server"
    assert ov["runs_measured"] >= 10
    docs = client.get("/api/docs").json()
    assert {d["slug"] for d in docs} == {"state-of-the-art", "measurement-protocol", "week-7-report"}
    assert client.get("/api/docs/unknown").status_code == 404


def test_export_static(client, tmp_path):
    from greenbench.server.export import export_static

    files = {p.relative_to(tmp_path).as_posix() for p in export_static(tmp_path)}
    for name in ("overview", "environment", "campaigns", "campaigns/pytest-server/analysis", "roadmap", "docs"):
        assert f"{name}.json" in files
    # same payloads as the live API
    assert json.loads((tmp_path / "studies.json").read_text(encoding="utf-8")) == client.get("/api/studies").json()
    assert json.loads((tmp_path / "campaigns" / "pytest-server" / "analysis.json").read_text(encoding="utf-8")) == \
        client.get("/api/campaigns/pytest-server/analysis").json()


def test_launch_validation(client):
    assert client.post("/api/campaigns", content=json.dumps({"preset": "nope"})).status_code == 422
    assert client.post("/api/campaigns", content=json.dumps({"preset": "quick", "studies": ["bogus"]})).status_code == 422
