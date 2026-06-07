"""Tests for the file-backed model registry.

Coverage:

- Upload a .pkl, list it back.
- Re-uploading the same bytes is idempotent (returns existing entry).
- Pin / get_pinned roundtrip across slots.
- Schema-revision pin: load_pickle raises when revisions don't match.
- Filtering by task/regime/horizon.
"""

from __future__ import annotations

import pickle
from pathlib import Path

import pytest
from sklearn.linear_model import LogisticRegression

from pfip.signals.registry import (
    ModelRegistryError,
    get_model,
    get_pinned,
    list_models,
    load_pickle,
    pin_model,
    upload_model,
)


@pytest.fixture
def tmp_registry(tmp_path: Path) -> Path:
    """Use a per-test registry directory."""
    return tmp_path / "registry"


@pytest.fixture
def fitted_model() -> LogisticRegression:
    import numpy as np

    rng = np.random.default_rng(0)
    X = rng.normal(0, 1, (50, 3))
    y = (X[:, 0] > 0).astype(int)
    return LogisticRegression().fit(X, y)


def _save_pkl(tmp_path: Path, model: object, name: str = "model.pkl") -> Path:
    out = tmp_path / name
    out.write_bytes(pickle.dumps(model))
    return out


def test_upload_and_list(tmp_registry, fitted_model, tmp_path):
    src = _save_pkl(tmp_path, fitted_model)
    entry = upload_model(
        src,
        name="lr_baseline",
        kind="pkl",
        task="signal",
        regime="bull_trend",
        horizon="1d",
        schema_revision="rev_abc",
        root=tmp_registry,
    )
    assert entry.name == "lr_baseline"
    assert entry.sha256
    assert entry.task == "signal"
    listed = list_models(root=tmp_registry)
    assert len(listed) == 1
    assert listed[0].id == entry.id


def test_upload_is_idempotent_on_sha(tmp_registry, fitted_model, tmp_path):
    src = _save_pkl(tmp_path, fitted_model)
    e1 = upload_model(src, name="a", root=tmp_registry)
    # Upload the same bytes again — should return the existing entry, not create a new id.
    src2 = _save_pkl(tmp_path, fitted_model, name="copy.pkl")
    e2 = upload_model(src2, name="b", root=tmp_registry)
    assert e1.id == e2.id
    assert len(list_models(root=tmp_registry)) == 1


def test_get_model_returns_entry(tmp_registry, fitted_model, tmp_path):
    src = _save_pkl(tmp_path, fitted_model)
    e = upload_model(src, name="lr", root=tmp_registry)
    fetched = get_model(e.id, root=tmp_registry)
    assert fetched.id == e.id


def test_get_model_missing_raises(tmp_registry):
    with pytest.raises(ModelRegistryError):
        get_model("nope", root=tmp_registry)


def test_pin_and_get_pinned(tmp_registry, fitted_model, tmp_path):
    src = _save_pkl(tmp_path, fitted_model)
    e = upload_model(
        src,
        name="lr",
        task="signal",
        regime="bull_trend",
        horizon="1d",
        root=tmp_registry,
    )
    pin_model(e.id, task="signal", regime="bull_trend", horizon="1d", root=tmp_registry)
    pinned = get_pinned(task="signal", regime="bull_trend", horizon="1d", root=tmp_registry)
    assert pinned is not None
    assert pinned.id == e.id
    # The entry's reverse pinned_for list should reflect this.
    refreshed = get_model(e.id, root=tmp_registry)
    assert "signal/bull_trend/1d" in refreshed.pinned_for


def test_pin_missing_model_raises(tmp_registry):
    with pytest.raises(ModelRegistryError):
        pin_model("nope", task="signal", root=tmp_registry)


def test_get_pinned_returns_none_for_unset_slot(tmp_registry):
    assert get_pinned(task="signal", regime="bull_trend", root=tmp_registry) is None


def test_load_pickle_schema_mismatch_raises(tmp_registry, fitted_model, tmp_path):
    src = _save_pkl(tmp_path, fitted_model)
    e = upload_model(src, name="lr", schema_revision="rev_v1", root=tmp_registry)
    with pytest.raises(ModelRegistryError):
        load_pickle(e, current_schema_revision="rev_v2", root=tmp_registry)


def test_load_pickle_matching_revision_loads(tmp_registry, fitted_model, tmp_path):
    src = _save_pkl(tmp_path, fitted_model)
    e = upload_model(src, name="lr", schema_revision="rev_v1", root=tmp_registry)
    loaded = load_pickle(e, current_schema_revision="rev_v1", root=tmp_registry)
    assert isinstance(loaded, LogisticRegression)


def test_load_pickle_no_revision_check_loads(tmp_registry, fitted_model, tmp_path):
    """Passing current_schema_revision=None disables the gate."""
    src = _save_pkl(tmp_path, fitted_model)
    e = upload_model(src, name="lr", schema_revision="rev_v1", root=tmp_registry)
    loaded = load_pickle(e, current_schema_revision=None, root=tmp_registry)
    assert isinstance(loaded, LogisticRegression)


def test_filter_by_task_regime_horizon(tmp_registry, fitted_model, tmp_path):
    # Three uploads, two matching the filter.
    src1 = _save_pkl(tmp_path, fitted_model, "a.pkl")
    src2 = _save_pkl(
        tmp_path, LogisticRegression().fit([[0, 1], [1, 0], [1, 1]], [0, 1, 1]), "b.pkl"
    )
    src3 = _save_pkl(tmp_path, LogisticRegression().fit([[0], [1]], [0, 1]), "c.pkl")
    upload_model(
        src1, name="m1", task="signal", regime="bull_trend", horizon="1d", root=tmp_registry
    )
    upload_model(
        src2, name="m2", task="signal", regime="bull_trend", horizon="5d", root=tmp_registry
    )
    upload_model(src3, name="m3", task="regime", regime=None, horizon=None, root=tmp_registry)
    only_bull_1d = list_models(task="signal", regime="bull_trend", horizon="1d", root=tmp_registry)
    assert len(only_bull_1d) == 1
    assert only_bull_1d[0].name == "m1"
    only_regime = list_models(task="regime", root=tmp_registry)
    assert len(only_regime) == 1
    assert only_regime[0].name == "m3"
