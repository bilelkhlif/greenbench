import pytest


@pytest.fixture(scope="session")
def tiny_dir(tmp_path_factory):
    """A private workspace with the tiny dataset, so tests never touch real campaign data."""
    import os

    home = tmp_path_factory.mktemp("gb-home")
    os.environ["GREENBENCH_HOME"] = str(home)
    os.environ["GREENBENCH_RESULTS"] = str(home / "results")
    from greenbench.data.generate import TABLES, ensure_dataset

    return ensure_dataset("tiny", {(t, s) for t in TABLES for s in ("parquet-snappy", "csv", "json-zstd")},
                          log=lambda *_: None)
