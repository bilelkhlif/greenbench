"""Where GreenBench keeps datasets (workspace) and campaign results."""

from __future__ import annotations

import os
from pathlib import Path


def project_root() -> Path | None:
    """The source checkout root when running from a clone (pyproject.toml two levels up)."""
    root = Path(__file__).resolve().parents[2]
    return root if (root / "pyproject.toml").exists() else None


def home() -> Path:
    """Root for generated data. Override with GREENBENCH_HOME."""
    env = os.environ.get("GREENBENCH_HOME")
    if env:
        return Path(env).expanduser().resolve()
    root = project_root()
    return (root / "workspace") if root else Path.home() / ".greenbench"


def datasets_dir(scale: str) -> Path:
    return home() / "datasets" / scale


def results_dir() -> Path:
    """Campaign results. Kept in the repository so published results travel with the code."""
    env = os.environ.get("GREENBENCH_RESULTS")
    if env:
        return Path(env).expanduser().resolve()
    root = project_root()
    return (root / "results") if root else home() / "results"


def docs_dir() -> Path | None:
    env = os.environ.get("GREENBENCH_DOCS")
    if env:
        return Path(env).expanduser().resolve()
    root = project_root()
    return (root / "docs") if root else None
