import numpy as np

from src.tiering import jenks_auto_labels


def test_two_clear_clusters_split_cleanly():
    vals = np.array([1, 2, 3, 50, 51, 52], dtype=float)
    labels, k, widest = jenks_auto_labels(vals, max_classes=5, max_spread_fraction=0.5)
    assert k == 2
    assert labels[0] == labels[1] == labels[2]
    assert labels[3] == labels[4] == labels[5]
    assert labels[0] != labels[3]


def test_spread_cap_is_never_exceeded_unless_max_classes_binds():
    """The core guarantee: every returned class's spread is <= the cap,
    as long as max_classes was large enough to actually achieve it."""
    rng = np.random.default_rng(42)
    vals = rng.uniform(0, 1000, size=60)
    labels, k, widest = jenks_auto_labels(vals, max_classes=40, max_spread_fraction=0.05)
    value_range = vals.max() - vals.min()
    cap = value_range * 0.05
    for lbl in np.unique(labels):
        spread = vals[labels == lbl].max() - vals[labels == lbl].min()
        assert spread <= cap + 1e-9
    assert widest <= cap + 1e-9


def test_max_classes_caps_fragmentation_when_cap_unreachable():
    """A very tight spread cap combined with a low max_classes ceiling
    should stop at max_classes rather than exceed it, even if the cap
    itself isn't satisfied."""
    vals = np.linspace(0, 1000, 50)  # smooth ladder, no real clusters
    labels, k, widest = jenks_auto_labels(vals, max_classes=4, max_spread_fraction=0.001)
    assert k == 4
    assert len(np.unique(labels)) == 4


def test_wide_gradual_pool_gets_split_even_without_a_single_outlier_gap():
    """Regression for the original 'too wide' bug report: a large,
    smoothly-declining pool (no single dominant cliff) must still get
    split into multiple tiers once its overall range exceeds the spread
    cap -- this is exactly what a pure gap-outlier detector (this
    module's earlier design) failed to do."""
    vals = np.linspace(800, 590, 30)  # ~7.2 pt steps, no outlier gap anywhere
    labels, k, widest = jenks_auto_labels(vals, max_classes=15, max_spread_fraction=0.08)
    assert k > 1
    value_range = vals.max() - vals.min()
    assert widest <= value_range * 0.08 + 1e-9


def test_all_identical_values_is_one_class():
    vals = np.array([5.0] * 10)
    labels, k, widest = jenks_auto_labels(vals, max_classes=10)
    assert k == 1
    assert widest == 0.0
    assert (labels == 0).all()


def test_single_value():
    labels, k, widest = jenks_auto_labels(np.array([7.0]), max_classes=10)
    assert k == 1
    assert labels.tolist() == [0]


def test_empty_input():
    labels, k, widest = jenks_auto_labels(np.array([]), max_classes=10)
    assert len(labels) == 0
    assert k == 0
