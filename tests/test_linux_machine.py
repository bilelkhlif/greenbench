"""Second reference machine (weeks 8-9): Linux RAPL reader, cpufreq fingerprint, cross-machine comparison.

The RAPL and cpufreq tests use a fake sysfs tree, so they run on any OS.
"""

import json
import shutil
import sys
from pathlib import Path

import pytest

from greenbench.analysis.compare import agreement, compare_campaigns, to_markdown, verdict
from greenbench.environment import linux_cpufreq
from greenbench.meters import MeterUnavailable
from greenbench.meters.rapl import RaplMeter

REPO_RESULTS = Path(__file__).resolve().parents[1] / "results"
# Windows file names cannot contain ":", so the fake tree uses "_" there (and the glob follows).
SEP = "_" if sys.platform == "win32" else ":"


@pytest.fixture(autouse=True)
def _zone_glob(monkeypatch):
    import greenbench.meters.rapl as rapl

    monkeypatch.setattr(rapl, "ZONE_GLOB", f"intel-rapl{SEP}*")


def _zone(root: Path, name: str, label: str, energy_uj: int, max_uj: int = 262143328850) -> Path:
    z = root / name.replace(":", SEP)
    z.mkdir(parents=True)
    (z / "name").write_text(label + "\n")
    (z / "energy_uj").write_text(f"{energy_uj}\n")
    (z / "max_energy_range_uj").write_text(f"{max_uj}\n")
    return z


@pytest.fixture
def powercap(tmp_path):
    root = tmp_path / "powercap"
    _zone(root, "intel-rapl:0", "package-0", 1_000_000)
    _zone(root, "intel-rapl:0:0", "core", 500_000)
    _zone(root, "intel-rapl:0:1", "uncore", 10_000)
    _zone(root, "intel-rapl:0:2", "dram", 200_000)
    _zone(root, "intel-rapl:1", "package-1", 3_000_000)
    _zone(root, "intel-rapl-mmio:0", "package-0", 9_999_999)  # duplicate MMIO view: must be ignored
    return root


def _set(root: Path, zone: str, value: int) -> None:
    (root / zone.replace(":", SEP) / "energy_uj").write_text(f"{value}\n")


def test_rapl_domains_and_multi_socket_sum(powercap):
    m = RaplMeter(base=powercap)
    assert m.domains == ("pkg", "cores", "dram", "gpu")
    assert m.packages == 2
    a = m.read()
    _set(powercap, "intel-rapl:0", 3_000_000)   # +2 J on socket 0
    _set(powercap, "intel-rapl:1", 4_500_000)   # +1.5 J on socket 1
    _set(powercap, "intel-rapl:0:0", 1_500_000)  # +1 J cores
    b = m.read()
    assert b.energy_j["pkg"] - a.energy_j["pkg"] == pytest.approx(3.5)
    assert b.energy_j["cores"] - a.energy_j["cores"] == pytest.approx(1.0)
    assert b.energy_j["dram"] - a.energy_j["dram"] == pytest.approx(0.0)
    info = m.describe()
    assert info["interface"].startswith("Linux powercap") and f"intel-rapl-mmio{SEP}0" not in info["channels"]


def test_rapl_counter_wrap_around(tmp_path):
    root = tmp_path / "powercap"
    _zone(root, "intel-rapl:0", "package-0", 990_000, max_uj=1_000_000)
    m = RaplMeter(base=root)
    a = m.read()
    _set(root, "intel-rapl:0", 20_000)  # wrapped: 10_000 to the top, then 20_000
    b = m.read()
    assert b.energy_j["pkg"] - a.energy_j["pkg"] == pytest.approx(0.03)
    assert b.energy_j["pkg"] >= a.energy_j["pkg"]


def test_rapl_unavailable_cases(tmp_path, monkeypatch):
    with pytest.raises(MeterUnavailable):
        RaplMeter(base=tmp_path / "missing")
    only_core = tmp_path / "core-only"
    _zone(only_core, "intel-rapl:0:0", "core", 1)
    with pytest.raises(MeterUnavailable, match="package"):
        RaplMeter(base=only_core)

    locked = tmp_path / "locked"
    z = _zone(locked, "intel-rapl:0", "package-0", 1)
    real = Path.read_text

    def deny(self, *a, **kw):
        if self == z / "energy_uj":
            raise PermissionError(13, "Permission denied")
        return real(self, *a, **kw)

    monkeypatch.setattr(Path, "read_text", deny)
    with pytest.raises(MeterUnavailable, match="chmod"):
        RaplMeter(base=locked)


def test_rapl_skips_unreadable_secondary_zone(tmp_path):
    root = tmp_path / "powercap"
    _zone(root, "intel-rapl:0", "package-0", 5)
    bad = _zone(root, "intel-rapl:0:2", "dram", 0)
    (bad / "energy_uj").write_text("not-a-number\n")  # disabled domain
    m = RaplMeter(base=root)
    assert m.domains == ("pkg",)


def test_linux_cpufreq_fingerprint(tmp_path):
    root = tmp_path / "cpu"
    for i in range(2):
        d = root / f"cpu{i}" / "cpufreq"
        d.mkdir(parents=True)
        (d / "scaling_governor").write_text("performance\n")
        (d / "scaling_driver").write_text("intel_pstate\n")
        (d / "energy_performance_preference").write_text("performance\n")
    (root / "intel_pstate").mkdir()
    (root / "intel_pstate" / "no_turbo").write_text("1\n")
    (root / "intel_pstate" / "status").write_text("active\n")
    info = linux_cpufreq(root)
    assert info == {"driver": "intel_pstate", "governor": "performance",
                    "energy_performance_preference": "performance", "turbo": False,
                    "intel_pstate_status": "active"}
    (root / "cpu1" / "cpufreq" / "scaling_governor").write_text("powersave\n")
    assert linux_cpufreq(root)["governor"] == "performance,powersave"
    assert linux_cpufreq(tmp_path / "nothing") is None


def test_verdicts_and_agreement():
    assert verdict({"significant": True, "energy_change_pct": -12}) == "lower"
    assert verdict({"significant": True, "energy_change_pct": 8}) == "higher"
    assert verdict({"significant": False, "energy_change_pct": -30}) == "tie"
    assert agreement("lower", "lower") == "agree"
    assert agreement("lower", "tie") == "partial"
    assert agreement("lower", "higher") == "reversal"


def _committed_campaign() -> Path:
    dirs = sorted(d for d in REPO_RESULTS.glob("*") if (d / "analysis.json").exists())
    if not dirs:
        pytest.skip("no committed campaign with an analysis")
    return dirs[0]


def test_compare_campaign_with_itself_and_a_perturbed_copy(tmp_path):
    src = _committed_campaign()
    a, b = tmp_path / "A", tmp_path / "B"
    for d in (a, b):
        d.mkdir()
        for f in ("campaign.json", "analysis.json"):
            shutil.copy(src / f, d / f)

    same = compare_campaigns(a, a)
    s = same["summary"]
    assert s["comparisons"] > 20 and s["agree"] == s["comparisons"] and s["reversal"] == 0
    assert s["spearman_energy_change"] == pytest.approx(1.0)
    assert s["same_recommendation"] == s["recommendation_groups"] > 0

    # Machine B: flip the first significant comparison and drop significance of another.
    an = json.loads((b / "analysis.json").read_text(encoding="utf-8"))
    sig = [r for st in an["studies"] for g in st["groups"] for r in g["rows"] if r.get("significant")]
    sig[0]["energy_change_pct"] = -sig[0]["energy_change_pct"]
    sig[1]["significant"] = False
    (b / "analysis.json").write_text(json.dumps(an), encoding="utf-8")

    cmp = compare_campaigns(a, b)
    s = cmp["summary"]
    assert s["reversal"] == 1 and s["partial"] == 1 and s["agree"] == s["comparisons"] - 2
    flipped = next(c for c in cmp["comparisons"] if c["agreement"] == "reversal")
    assert flipped["config"] == sig[0]["key"]
    md = to_markdown(cmp)
    assert "Cross-machine comparison" in md and "reversal" in md
    # comparing never writes into the campaign directories
    assert sorted(p.name for p in a.iterdir()) == ["analysis.json", "campaign.json"]
