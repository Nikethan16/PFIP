"""Tests for the CPCV (Combinatorial Purged Cross-Validation) fold generator
following López de Prado, "Advances in Financial Machine Learning" ch. 7.

Invariants we pin:

- Returns exactly ``n_splits`` (fold, test_idx) pairs.
- Test sets partition the full index (no overlap, full coverage).
- Train sets exclude the embargo band around their test set.
- Train sets contain no test indices.
- Embargo of 0 means train ∪ test == full index for each fold.
"""

from __future__ import annotations

import numpy as np
import pytest

from pfip.backtest.vectorbt_engine import cpcv_folds


def test_returns_requested_number_of_folds():
    folds = cpcv_folds(n_obs=100, n_splits=5, embargo=0)
    assert len(folds) == 5


def test_test_sets_partition_full_index():
    """Union of test sets covers [0, n) with no overlap."""
    n = 100
    folds = cpcv_folds(n_obs=n, n_splits=4, embargo=0)
    all_test = np.concatenate([t for _, t in folds])
    assert sorted(all_test.tolist()) == list(range(n))


def test_train_and_test_are_disjoint():
    folds = cpcv_folds(n_obs=200, n_splits=8, embargo=3)
    for train, test in folds:
        # Use intersection; must be empty.
        assert len(np.intersect1d(train, test)) == 0


def test_embargo_excludes_neighbours_from_train():
    """For embargo=5, the 5 indices on each side of the test set must NOT be in train."""
    n = 200
    folds = cpcv_folds(n_obs=n, n_splits=4, embargo=5)
    for train, test in folds:
        lo = max(0, int(test.min()) - 5)
        hi = min(n, int(test.max()) + 1 + 5)
        # Embargo band intersected with train must be empty.
        embargo_band = set(range(lo, hi))
        train_set = set(train.tolist())
        assert embargo_band.isdisjoint(train_set - set(test.tolist()))


def test_invalid_n_splits_raises():
    with pytest.raises(ValueError):
        cpcv_folds(n_obs=100, n_splits=1)


def test_too_few_obs_raises():
    """n_splits=10 over 3 obs is infeasible."""
    with pytest.raises(ValueError):
        cpcv_folds(n_obs=3, n_splits=10)


def test_last_fold_extends_to_end():
    """When n_obs isn't divisible by n_splits, the last fold absorbs the remainder."""
    folds = cpcv_folds(n_obs=23, n_splits=4, embargo=0)
    last_test = folds[-1][1]
    # The last test set must reach the final index.
    assert int(last_test.max()) == 22


def test_zero_embargo_yields_full_partition():
    """train ∪ test == full index when embargo=0."""
    n = 100
    folds = cpcv_folds(n_obs=n, n_splits=5, embargo=0)
    for train, test in folds:
        assert sorted(np.concatenate([train, test]).tolist()) == list(range(n))
