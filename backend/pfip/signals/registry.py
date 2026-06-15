"""Model registry — file-backed pin/catalogue layer.

The registry sits *alongside* MLflow (which we use for experiment
tracking + artefact storage). MLflow's own "model registry" is heavier
than we need and requires the tracking server to be reachable for every
predict-time lookup. Instead we keep a small JSON manifest at
``data/model_registry/manifest.json`` plus the model artefacts under
``data/model_registry/<id>/...``.

Operations:

- :func:`upload_model` — copy a `.pkl` / `.onnx` / HF directory into
  registry storage and add a manifest entry.
- :func:`list_models` — return the manifest entries (optionally filtered).
- :func:`get_model` — return one entry by id.
- :func:`pin_model` — set this model as the champion for a (task, regime)
  slot. The signal layer uses :func:`get_pinned` to find it at runtime.
- :func:`get_pinned` — lookup the pinned model for a slot.
- :func:`load_pickle` — convenience deserializer with schema-version pin.

Schema-version pin (per suggestion #2): every manifest entry stores the
alembic revision that was current when the model was trained. Refusing
to load when the current revision doesn't match closes a subtle silent
failure mode where a model expects schema v1 features but gets v2.
"""

from __future__ import annotations

import hashlib
import json
import pickle
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

REGISTRY_ROOT_DEFAULT = Path("data/model_registry")
_MANIFEST_NAME = "manifest.json"


class ModelRegistryError(RuntimeError):
    """Raised on schema mismatches, missing artefacts, etc."""


@dataclass(slots=True)
class ModelEntry:
    """One catalogue row."""

    id: str
    name: str
    kind: str  # "pkl" / "onnx" / "huggingface"
    task: str  # "signal" / "regime" / "embedding"
    regime: str | None  # "bull_trend" / "sideways" / None for global
    horizon: str | None  # "1d" / "5d" / "21d" / None
    version: str
    created_at: str
    artefact_relpath: str  # relative to registry root
    schema_revision: str | None  # alembic revision at training time
    sha256: str  # of the primary artefact file
    metrics: dict[str, float] = field(default_factory=dict)
    notes: str = ""
    pinned_for: list[str] = field(default_factory=list)  # ["signal/bull_trend/1d", …]


def _slot_key(task: str, regime: str | None, horizon: str | None) -> str:
    """Canonical key for a (task, regime, horizon) pin."""
    return f"{task}/{regime or '_'}/{horizon or '_'}"


def _registry_root(root: Path | None = None) -> Path:
    return Path(root) if root else REGISTRY_ROOT_DEFAULT


def _manifest_path(root: Path) -> Path:
    return root / _MANIFEST_NAME


def _load_manifest(root: Path) -> dict[str, Any]:
    mp = _manifest_path(root)
    if not mp.exists():
        return {"entries": [], "pins": {}}
    return json.loads(mp.read_text(encoding="utf-8"))


def _save_manifest(root: Path, manifest: dict[str, Any]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    _manifest_path(root).write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
    )


def _sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fp:
        for chunk in iter(lambda: fp.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def upload_model(
    source_path: Path,
    *,
    name: str,
    kind: str = "pkl",
    task: str = "signal",
    regime: str | None = None,
    horizon: str | None = None,
    version: str | None = None,
    schema_revision: str | None = None,
    metrics: dict[str, float] | None = None,
    notes: str = "",
    root: Path | None = None,
) -> ModelEntry:
    """Copy a model artefact into the registry; append a manifest entry.

    Returns the new ``ModelEntry``. Idempotent on ``sha256`` — if a file
    with the same hash is already in the registry, the existing entry is
    returned (no double-upload).
    """
    src = Path(source_path)
    if not src.exists():
        raise FileNotFoundError(src)
    if kind not in ("pkl", "onnx", "huggingface"):
        raise ValueError(f"Unsupported kind: {kind!r}")

    root = _registry_root(root)
    manifest = _load_manifest(root)

    # Hash first to dedupe.
    if src.is_file():
        sha = _sha256_of(src)
    else:
        # For huggingface directories: hash the concatenated SHAs of files.
        h = hashlib.sha256()
        for f in sorted(src.rglob("*")):
            if f.is_file():
                h.update(_sha256_of(f).encode())
        sha = h.hexdigest()

    for e in manifest["entries"]:
        if e["sha256"] == sha:
            return _entry_from_dict(e)

    model_id = uuid.uuid4().hex[:12]
    dest_dir = root / model_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    artefact_relpath: str
    if src.is_file():
        dest_file = dest_dir / src.name
        shutil.copy2(src, dest_file)
        artefact_relpath = str(dest_file.relative_to(root))
    else:
        # Copy the whole HF directory.
        dest_dir2 = dest_dir / src.name
        shutil.copytree(src, dest_dir2)
        artefact_relpath = str(dest_dir2.relative_to(root))

    entry = ModelEntry(
        id=model_id,
        name=name,
        kind=kind,
        task=task,
        regime=regime,
        horizon=horizon,
        version=version or "1.0",
        created_at=datetime.now(tz=timezone.utc).isoformat(),
        artefact_relpath=artefact_relpath,
        schema_revision=schema_revision,
        sha256=sha,
        metrics=dict(metrics or {}),
        notes=notes,
    )
    manifest["entries"].append(_entry_to_dict(entry))
    _save_manifest(root, manifest)
    return entry


def list_models(
    *,
    task: str | None = None,
    regime: str | None = None,
    horizon: str | None = None,
    root: Path | None = None,
) -> list[ModelEntry]:
    """Return manifest entries matching the optional filters."""
    manifest = _load_manifest(_registry_root(root))
    out: list[ModelEntry] = []
    for e in manifest["entries"]:
        if task and e.get("task") != task:
            continue
        if regime and e.get("regime") != regime:
            continue
        if horizon and e.get("horizon") != horizon:
            continue
        out.append(_entry_from_dict(e))
    return out


def get_model(model_id: str, *, root: Path | None = None) -> ModelEntry:
    """Lookup by id; raises ModelRegistryError if missing."""
    manifest = _load_manifest(_registry_root(root))
    for e in manifest["entries"]:
        if e["id"] == model_id:
            return _entry_from_dict(e)
    raise ModelRegistryError(f"model id {model_id!r} not found in registry")


def pin_model(
    model_id: str,
    *,
    task: str,
    regime: str | None = None,
    horizon: str | None = None,
    root: Path | None = None,
) -> None:
    """Pin ``model_id`` as the champion for ``(task, regime, horizon)``."""
    root = _registry_root(root)
    manifest = _load_manifest(root)
    found = None
    for e in manifest["entries"]:
        if e["id"] == model_id:
            found = e
            break
    if found is None:
        raise ModelRegistryError(f"model id {model_id!r} not in registry")
    slot = _slot_key(task, regime, horizon)
    manifest.setdefault("pins", {})[slot] = model_id
    # Update reverse list.
    pins = set(found.get("pinned_for", []))
    pins.add(slot)
    found["pinned_for"] = sorted(pins)
    _save_manifest(root, manifest)


def get_pinned(
    *,
    task: str,
    regime: str | None = None,
    horizon: str | None = None,
    root: Path | None = None,
) -> ModelEntry | None:
    """Return the pinned model for the slot, or None."""
    root = _registry_root(root)
    manifest = _load_manifest(root)
    slot = _slot_key(task, regime, horizon)
    model_id = manifest.get("pins", {}).get(slot)
    if not model_id:
        return None
    try:
        return get_model(model_id, root=root)
    except ModelRegistryError:
        return None


def load_pickle(
    entry: ModelEntry,
    *,
    current_schema_revision: str | None = None,
    root: Path | None = None,
) -> Any:
    """Deserialize a `.pkl` model with optional schema-revision check.

    Raises ``ModelRegistryError`` if the current schema revision doesn't
    match the one recorded at training time. Pass
    ``current_schema_revision=None`` to skip the check (not recommended).
    """
    if entry.kind != "pkl":
        raise ModelRegistryError(f"load_pickle called on kind={entry.kind!r}")
    if (
        current_schema_revision is not None
        and entry.schema_revision is not None
        and entry.schema_revision != current_schema_revision
    ):
        raise ModelRegistryError(
            f"schema mismatch: model trained at revision "
            f"{entry.schema_revision!r}, current is "
            f"{current_schema_revision!r}. Refusing to load."
        )
    path = _registry_root(root) / entry.artefact_relpath
    if not path.exists():
        raise ModelRegistryError(f"artefact missing on disk: {path}")
    with path.open("rb") as fp:
        return pickle.load(fp)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _entry_to_dict(e: ModelEntry) -> dict[str, Any]:
    return {
        "id": e.id,
        "name": e.name,
        "kind": e.kind,
        "task": e.task,
        "regime": e.regime,
        "horizon": e.horizon,
        "version": e.version,
        "created_at": e.created_at,
        "artefact_relpath": e.artefact_relpath,
        "schema_revision": e.schema_revision,
        "sha256": e.sha256,
        "metrics": dict(e.metrics),
        "notes": e.notes,
        "pinned_for": list(e.pinned_for),
    }


def _entry_from_dict(d: dict[str, Any]) -> ModelEntry:
    return ModelEntry(
        id=d["id"],
        name=d["name"],
        kind=d["kind"],
        task=d["task"],
        regime=d.get("regime"),
        horizon=d.get("horizon"),
        version=d.get("version", "1.0"),
        created_at=d["created_at"],
        artefact_relpath=d["artefact_relpath"],
        schema_revision=d.get("schema_revision"),
        sha256=d["sha256"],
        metrics=dict(d.get("metrics", {})),
        notes=d.get("notes", ""),
        pinned_for=list(d.get("pinned_for", [])),
    )


__all__ = [
    "ModelEntry",
    "ModelRegistryError",
    "REGISTRY_ROOT_DEFAULT",
    "get_model",
    "get_pinned",
    "list_models",
    "load_pickle",
    "pin_model",
    "upload_model",
]
