"""Reference results: the expected output of each task, computed once per dataset.

Every measured run is validated against them: exact variants must reproduce the reference
checksum (otherwise the run is invalid), approximate variants are scored on their error.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from greenbench.data.generate import load_meta
from greenbench.data.storage import DEFAULT_STORAGE
from greenbench.workloads import get
from greenbench.workloads.base import RunContext, checksum


def reference_key(workload: str, params: dict) -> str:
    w = get(workload)
    parts = [f"{k}-{params[k]}" for k in w.result_knobs]
    return f"{workload}__" + ("_".join(parts) if parts else "default")


def reference_files(data_dir: Path, workload: str, params: dict) -> tuple[Path, Path]:
    base = data_dir / "references" / reference_key(workload, params)
    return base.with_suffix(".npz"), base.with_suffix(".json")


def ensure_reference(data_dir: Path, workload: str, params: dict) -> dict:
    npz, meta_file = reference_files(data_dir, workload, params)
    if meta_file.exists():
        return json.loads(meta_file.read_text(encoding="utf-8"))
    w = get(workload)
    ref_params = w.params({k: params[k] for k in w.result_knobs})
    ref_params["storage"] = DEFAULT_STORAGE
    if "threads" in ref_params:
        ref_params["threads"] = 1
    if hasattr(w, "ensure_inputs"):
        w.ensure_inputs(data_dir, ref_params)
    prep = w.prepare(data_dir, load_meta(data_dir), ref_params)
    result = w.run(w.reference_variant, ref_params, RunContext(), prep)
    npz.parent.mkdir(parents=True, exist_ok=True)
    np.savez(npz, **result)
    info = {"workload": workload, "variant": w.reference_variant, "params": ref_params,
            "checksum": checksum(result), "summary": w.summary_of(result)}
    meta_file.write_text(json.dumps(info, indent=2), encoding="utf-8")
    return info


def load_reference_arrays(data_dir: Path, workload: str, params: dict) -> dict[str, np.ndarray]:
    npz, _ = reference_files(data_dir, workload, params)
    with np.load(npz) as f:
        return {k: f[k] for k in f.files}
