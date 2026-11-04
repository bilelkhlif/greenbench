import numpy as np
import pytest

from greenbench.analysis.stats import cliffs_delta, holm, magnitude, mann_whitney_p, ratio_of_medians


def test_cliffs_delta_extremes_and_symmetry():
    a, b = np.arange(10.0), np.arange(10.0) + 100
    assert cliffs_delta(a, b) == -1.0
    assert cliffs_delta(b, a) == 1.0
    assert cliffs_delta(a, a) == 0.0


def test_magnitude_thresholds():
    assert [magnitude(d) for d in (0.1, 0.2, 0.4, 0.9)] == ["negligible", "small", "medium", "large"]


def test_holm_is_monotone_and_bounded():
    adj = holm([0.01, 0.04, 0.03, 0.5])
    assert adj == pytest.approx([0.04, 0.09, 0.09, 0.5])
    assert all(0 <= p <= 1 for p in adj)


def test_ratio_ci_covers_true_ratio():
    rng = np.random.default_rng(0)
    x = rng.normal(50, 1, 30)
    base = rng.normal(100, 2, 30)
    point, lo, hi = ratio_of_medians(x, base, rng)
    assert lo < 0.5 < hi and abs(point - 0.5) < 0.02


def test_mann_whitney_detects_shift():
    rng = np.random.default_rng(3)
    assert mann_whitney_p(rng.normal(0, 1, 10), rng.normal(5, 1, 10)) < 0.001
