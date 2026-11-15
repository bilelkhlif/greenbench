"""CNN inference workload: equivalent convolution algorithms, batching invariance, opt-in studies."""

import json

import numpy as np
import pytest

from greenbench.protocol.plan import STUDIES, default_studies, expand
from greenbench.workloads import get
from greenbench.workloads.base import RunContext, checksum
from greenbench.workloads.cnn import CONV, conv_im2col


@pytest.mark.parametrize("shape", [(2, 3, 32, 32), (3, 16, 16, 16), (1, 5, 8, 6)])
@pytest.mark.parametrize("name", ["direct", "fft", "winograd"])
def test_convolution_algorithms_agree(name, shape):
    rng = np.random.default_rng(1)
    x = rng.normal(size=shape)
    w = rng.normal(size=(7, shape[1], 3, 3))
    # brute-force reference: out[n, o, y, x] = sum_c,dy,dx xp[n, c, y + dy, x + dx] * w[o, c, dy, dx]
    xp = np.pad(x, ((0, 0), (0, 0), (1, 1), (1, 1)))
    ref = np.zeros((shape[0], 7, shape[2], shape[3]))
    for dy in range(3):
        for dx in range(3):
            ref += np.einsum("nchw,oc->nohw", xp[:, :, dy:dy + shape[2], dx:dx + shape[3]], w[:, :, dy, dx])
    np.testing.assert_allclose(conv_im2col(x, w), ref, rtol=1e-10, atol=1e-10)
    np.testing.assert_allclose(CONV[name](x, w), ref, rtol=1e-10, atol=1e-10)


def test_batch_size_does_not_change_predictions(tiny_dir):
    w = get("cnn")
    sums = set()
    for bs in w.knobs["batch_size"]:
        params = w.params({"batch_size": bs})
        res = w.run("im2col", params, RunContext(), w.prepare(tiny_dir, {}, params))
        sums.add(checksum(res))
    assert len(sums) == 1
    info = json.loads((tiny_dir / "cnn" / f"model_{w.n_images(tiny_dir)}.json").read_text())
    assert info["train_accuracy"] > 0.8  # the network really classifies, predictions are not constant
    summary = w.summary_of(res)
    assert summary["classes_predicted"] >= 5


def test_fp32_is_scored_on_changed_labels(tiny_dir):
    w = get("cnn")
    params = w.params()
    prep = w.prepare(tiny_dir, {}, params)
    ref = w.run("im2col", params, RunContext(), prep)
    approx = w.run("im2col_fp32", params, RunContext(), prep)
    acc = w.accuracy_of(approx, ref)
    assert set(acc) == {"labels"} and 0.0 <= acc["labels"]["mape"] <= 0.05
    flipped = {"labels": ref["labels"].copy()}
    flipped["labels"][:4] = (flipped["labels"][:4] + 1) % 10
    assert w.accuracy_of(flipped, ref)["labels"]["mape"] == pytest.approx(4 / ref["labels"].size)


def test_cnn_studies_are_opt_in():
    assert "cnn-convolution" in STUDIES and "cnn-batching" in STUDIES
    assert default_studies() == ["join-algorithms", "storage-formats", "text-search", "streaming-windows",
                                 "indexing"]
    configs, members = expand(["cnn-convolution", "cnn-batching"])
    assert len(configs) == 8  # 5 algorithms + 4 batch sizes, im2col at batch 64 shared
    shared = set(members["cnn-convolution"]) & set(members["cnn-batching"])
    assert shared == {"cnn/im2col/batch_size=64"}


def test_cnn_campaign_end_to_end(tiny_dir):
    from greenbench.protocol.runner import CampaignConfig, Runner

    cfg = CampaignConfig(preset="quick", studies=["cnn-convolution"], scale="tiny", repetitions=2, warmups=0,
                         cooldown_s=0, idle_s=0, campaign_id="pytest-cnn")
    out = Runner(cfg, log=lambda *_: None).run()
    runs = [json.loads(line) for line in (out / "runs.jsonl").read_text().splitlines()]
    assert len(runs) == 10 and all(r["status"] == "ok" for r in runs), [r.get("error") for r in runs]
    fp32 = [r for r in runs if r["variant"] == "im2col_fp32"]
    assert all(set(r["accuracy"]) == {"labels"} for r in fp32)
    analysis = json.loads((out / "analysis.json").read_text())
    assert analysis["quality"]["valid"] == 10
    assert analysis["studies"][0]["groups"][0]["baseline"] == "cnn/im2col/batch_size=64"
