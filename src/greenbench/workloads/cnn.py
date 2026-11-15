"""CNN inference: classify the same images with different convolution algorithms.

A small VGG-style network (3 conv 3x3 layers + global average pooling + a linear head) is run
in NumPy on 32x32 RGB images. The convolution layers dominate the work and are computed by
interchangeable algorithms that are mathematically identical:

    im2col      unfold every 3x3 patch into a matrix, one large GEMM per layer (Caffe-style)
    direct      shift-and-accumulate: 9 small GEMMs per layer, no patch copy
    fft         pointwise products in the frequency domain (rfft2 / irfft2)
    winograd    Winograd F(2x2, 3x3): 16 multiplies per 2x2 outputs instead of 36
    im2col_fp32 im2col in float32: approximate, scored on how many labels change

The exact variants compute in float64, so they return the same predicted labels as the
reference (checked by checksum like every other workload). Batch size does not change the
answer either, only how the work is grouped.

The network is deterministic: convolution weights are seeded He-initialised random features
and the linear head is fitted by ridge regression on a separate training set when the inputs
are prepared (never measured). Images are seeded synthetic textures from 10 classes (oriented
gratings with class-specific orientation, frequency and colour, plus noise), so predictions
are meaningful rather than constant. Inputs live in <dataset>/cnn/.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

from greenbench.workloads.base import Result, RunContext, Variant, Workload

SEED = 20261115
IMG = 32
CLASSES = 10
LAYERS = ((3, 16), (16, 32), (32, 64))  # (in, out) channels; 2x2 max-pool after the first two
N_IMAGES = {"tiny": 32, "small": 256, "medium": 1024}
N_TRAIN = 2000

# Winograd F(2x2, 3x3) transforms (Lavin & Gray, 2016).
_BT = np.array([[1, 0, -1, 0], [0, 1, 1, 0], [0, -1, 1, 0], [0, 1, 0, -1]], dtype=np.float64)
_G = np.array([[1, 0, 0], [0.5, 0.5, 0.5], [0.5, -0.5, 0.5], [0, 0, 1]], dtype=np.float64)
_AT = np.array([[1, 1, 1, 0], [0, 1, -1, -1]], dtype=np.float64)


# ---------------------------------------------------------------- convolution algorithms
# All take x (N, C, H, W) and w (Co, C, 3, 3), "same" padding, stride 1; return (N, Co, H, W).

def conv_im2col(x: np.ndarray, w: np.ndarray) -> np.ndarray:
    n, c, h, wd = x.shape
    co = w.shape[0]
    xp = np.pad(x, ((0, 0), (0, 0), (1, 1), (1, 1)))
    cols = sliding_window_view(xp, (3, 3), axis=(2, 3))            # (N, C, H, W, 3, 3) view
    cols = cols.transpose(0, 2, 3, 1, 4, 5).reshape(n * h * wd, c * 9)  # the 9x patch copy
    out = cols @ w.reshape(co, c * 9).T                              # one GEMM
    return out.reshape(n, h, wd, co).transpose(0, 3, 1, 2)


def conv_direct(x: np.ndarray, w: np.ndarray) -> np.ndarray:
    n, c, h, wd = x.shape
    co = w.shape[0]
    xp = np.pad(x, ((0, 0), (0, 0), (1, 1), (1, 1)))
    out = np.zeros((co, n, h, wd), dtype=x.dtype)
    for dy in range(3):
        for dx in range(3):
            out += np.tensordot(w[:, :, dy, dx], xp[:, :, dy:dy + h, dx:dx + wd], axes=([1], [1]))
    return out.transpose(1, 0, 2, 3)


def conv_fft(x: np.ndarray, w: np.ndarray) -> np.ndarray:
    n, c, h, wd = x.shape
    xp = np.pad(x, ((0, 0), (0, 0), (1, 1), (1, 1)))
    size = (h + 2, wd + 2)  # circular wrap only touches the 2 border rows/cols that are cropped
    xf = np.fft.rfft2(xp, s=size)                                    # (N, C, F1, F2)
    wf = np.fft.rfft2(w[:, :, ::-1, ::-1], s=size)                   # correlation = convolution with flipped kernel
    yf = xf.transpose(2, 3, 0, 1) @ wf.transpose(2, 3, 1, 0)         # (F1, F2, N, Co): sum over channels
    y = np.fft.irfft2(yf.transpose(2, 3, 0, 1), s=size)
    return y[:, :, 2:, 2:]


# Row-major vec(L X R^T) = kron(L, R) vec(X): each transform becomes one GEMM over all tiles at once.
_KB = np.kron(_BT, _BT)   # (16, 16) input transform  B^T d B
_KG = np.kron(_G, _G)     # (16, 9)  kernel transform G g G^T
_KA = np.kron(_AT, _AT)   # (4, 16)  output transform A^T m A


def conv_winograd(x: np.ndarray, w: np.ndarray) -> np.ndarray:
    n, c, h, wd = x.shape
    co = w.shape[0]
    th, tw = h // 2, wd // 2
    xp = np.pad(x, ((0, 0), (0, 0), (1, 1), (1, 1)))
    tiles = sliding_window_view(xp, (4, 4), axis=(2, 3))[:, :, ::2, ::2]  # (N, C, th, tw, 4, 4), overlap 2
    d = tiles.transpose(4, 5, 1, 0, 2, 3).reshape(16, c * n * th * tw)    # tile-major copy
    v = (_KB.astype(x.dtype) @ d).reshape(16, c, n * th * tw)             # input transform
    u = (_KG.astype(x.dtype) @ w.reshape(co * c, 9).T).reshape(16, co, c)  # kernel transform
    m = u @ v                                                              # 16 GEMMs over channels
    y = _KA.astype(x.dtype) @ m.reshape(16, co * n * th * tw)              # output transform
    return y.reshape(2, 2, co, n, th, tw).transpose(3, 2, 4, 0, 5, 1).reshape(n, co, h, wd)


CONV = {"im2col": conv_im2col, "direct": conv_direct, "fft": conv_fft, "winograd": conv_winograd,
        "im2col_fp32": conv_im2col}


# ---------------------------------------------------------------- network

def _maxpool2(x: np.ndarray) -> np.ndarray:
    n, c, h, w = x.shape
    return x.reshape(n, c, h // 2, 2, w // 2, 2).max(axis=(3, 5))


def features(x: np.ndarray, model: dict, conv) -> np.ndarray:
    for i in range(len(LAYERS)):
        x = conv(x, model[f"w{i}"]) + model[f"b{i}"][None, :, None, None]
        np.maximum(x, 0, out=x)
        if i < len(LAYERS) - 1:
            x = _maxpool2(x)
    return x.mean(axis=(2, 3))  # global average pooling -> (N, 64)


def logits(x: np.ndarray, model: dict, conv) -> np.ndarray:
    return features(x, model, conv) @ model["fc_w"] + model["fc_b"]


# ---------------------------------------------------------------- inputs

def synthetic_images(n: int, rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
    """Oriented colour gratings: class k sets orientation (k mod 5), frequency (k // 5) and a colour bias."""
    labels = rng.integers(0, CLASSES, size=n)
    yy, xx = np.mgrid[0:IMG, 0:IMG].astype(np.float64) / IMG
    theta = (labels % 5) * np.pi / 5 + rng.normal(0, 0.08, n)
    freq = np.where(labels < 5, 3.0, 6.0) * rng.uniform(0.9, 1.1, n)
    phase = rng.uniform(0, 2 * np.pi, n)
    proj = np.cos(theta)[:, None, None] * xx + np.sin(theta)[:, None, None] * yy
    grating = np.sin(2 * np.pi * freq[:, None, None] * proj + phase[:, None, None])   # (N, H, W)
    palette = np.random.default_rng(SEED).uniform(0.3, 1.0, (CLASSES, 3))
    colour = palette[labels] * rng.uniform(0.7, 1.3, (n, 3))
    img = colour[:, :, None, None] * grating[:, None] + rng.normal(0, 1.2, (n, 3, IMG, IMG))
    return img.astype(np.float64), labels.astype(np.int64)


def build_model() -> tuple[dict, dict]:
    """Seeded random conv features + a ridge-fitted linear head. Returns (arrays, info)."""
    rng = np.random.default_rng(SEED)
    model = {}
    for i, (ci, co) in enumerate(LAYERS):
        model[f"w{i}"] = rng.normal(0, np.sqrt(2.0 / (ci * 9)), (co, ci, 3, 3))
        model[f"b{i}"] = rng.normal(0, 0.01, co)
    train_x, train_y = synthetic_images(N_TRAIN, np.random.default_rng(SEED + 1))
    f = np.concatenate([features(train_x[i:i + 250], model, conv_im2col) for i in range(0, N_TRAIN, 250)])
    mu, sd = f.mean(axis=0), f.std(axis=0) + 1e-9
    z = np.hstack([(f - mu) / sd, np.ones((N_TRAIN, 1))])
    target = np.eye(CLASSES)[train_y]
    coef = np.linalg.solve(z.T @ z + 1e-2 * np.eye(z.shape[1]), z.T @ target)
    model["fc_w"] = coef[:-1] / sd[:, None]
    model["fc_b"] = coef[-1] - (mu / sd) @ coef[:-1]
    train_acc = float((np.argmax(f @ model["fc_w"] + model["fc_b"], axis=1) == train_y).mean())
    return model, {"seed": SEED, "train_images": N_TRAIN, "train_accuracy": train_acc,
                   "layers": [list(lyr) for lyr in LAYERS], "classes": CLASSES}


class CnnInference(Workload):
    name = "cnn"
    title = "CNN inference"
    summary = "Image classification with interchangeable convolution algorithms"
    description = ("A small convolutional network (3 conv 3×3 layers, global average pooling, linear head) "
                   "classifies 32×32 RGB images. The convolutions are computed with im2col + GEMM, direct "
                   "shift-and-accumulate, FFT or Winograd F(2×2,3×3): every exact variant predicts exactly the "
                   "same labels. A float32 variant trades a few changed labels for cheaper arithmetic.")
    icon = "chart"
    inputs = ()
    variants = {
        "im2col": Variant("im2col", "im2col + GEMM",
                          "Unfold every 3×3 patch into a matrix and run one large matrix product per layer."),
        "direct": Variant("direct", "Direct (shift & accumulate)",
                          "Nine small matrix products per layer on shifted views of the input; no patch copy."),
        "fft": Variant("fft", "FFT convolution",
                       "Transform inputs and kernels with a 2-D real FFT, multiply, transform back."),
        "winograd": Variant("winograd", "Winograd F(2×2,3×3)",
                            "Minimal-filtering algorithm: 16 multiplications per 2×2 output tile instead of 36."),
        "im2col_fp32": Variant("im2col_fp32", "im2col + GEMM, float32",
                               "Same as im2col in single precision; scored on the share of changed labels.",
                               exact=False),
    }
    knobs = {"batch_size": [1, 8, 64, 256]}
    defaults = {"batch_size": 64}
    result_knobs = ()
    reference_variant = "im2col"
    phases = ("load", "infer")

    @staticmethod
    def input_dir(data_dir: Path) -> Path:
        return Path(data_dir) / "cnn"

    def n_images(self, data_dir: Path) -> int:
        return N_IMAGES.get(Path(data_dir).name, N_IMAGES["small"])

    def ensure_inputs(self, data_dir: Path, params: dict) -> None:
        """Write the model and the evaluation images once, outside any measurement."""
        d = self.input_dir(data_dir)
        n = self.n_images(data_dir)
        model_file, images_file = d / "model.npz", d / f"images_{n}.npz"
        if model_file.exists() and images_file.exists():
            return
        d.mkdir(parents=True, exist_ok=True)
        model, info = build_model()
        x, y = synthetic_images(n, np.random.default_rng(SEED + 2))
        pred = np.argmax(logits(x, model, conv_im2col), axis=1)
        info["eval_images"] = n
        info["eval_accuracy"] = float((pred == y).mean())
        np.savez(model_file, **model)
        np.savez(images_file, images=x, labels=y)
        (d / f"model_{n}.json").write_text(json.dumps(info, indent=2), encoding="utf-8")

    def prepare(self, data_dir: Path, meta: dict, params: dict) -> dict:
        self.ensure_inputs(data_dir, params)
        d = self.input_dir(data_dir)
        return {"model": d / "model.npz", "images": d / f"images_{self.n_images(data_dir)}.npz"}

    def run(self, variant: str, params: dict, ctx: RunContext, prep: dict) -> Result:
        dtype = np.float32 if variant == "im2col_fp32" else np.float64
        with ctx.phase("load"):
            with np.load(prep["model"]) as f:
                model = {k: f[k].astype(dtype) for k in f.files}
            with np.load(prep["images"]) as f:
                images = f["images"].astype(dtype)
        conv = CONV[variant]
        bs = int(params["batch_size"])
        with ctx.phase("infer"):
            labels = np.concatenate([np.argmax(logits(images[i:i + bs], model, conv), axis=1)
                                     for i in range(0, images.shape[0], bs)])
        return {"labels": labels.astype(np.int64)}

    def accuracy_of(self, result: Result, reference: Result) -> dict[str, dict[str, float]]:
        """Approximate variants are scored on the share of labels that differ from the reference."""
        changed = float(np.mean(result["labels"] != reference["labels"]))
        return {"labels": {"mape": changed, "p95_ape": changed, "max_ape": changed}}

    def summary_of(self, result: Result) -> dict:
        counts = np.bincount(result["labels"], minlength=CLASSES)
        return {"images": int(result["labels"].size), "classes_predicted": int((counts > 0).sum()),
                "largest_class_share": float(counts.max() / max(1, counts.sum()))}
