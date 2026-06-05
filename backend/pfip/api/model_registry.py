"""HTTP surface for the model registry.

Endpoints (all under ``/api/v1/models``):

- ``POST /upload``       — multipart upload of a `.pkl` (or `.onnx`).
- ``GET /``              — list with optional task/regime/horizon filters.
- ``GET /{id}``          — fetch a single entry.
- ``POST /{id}/pin``     — pin as champion for (task, regime, horizon).
- ``GET /pinned``        — lookup the current champion for a slot.

The registry storage layer lives in :mod:`pfip.signals.registry`; this
router is just a thin HTTP adapter that respects the same disk layout.

Auth: ``CurrentUser`` dependency — single-user system.
"""

from __future__ import annotations

from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel

from pfip.api.deps import CurrentUser
from pfip.signals.registry import (
    ModelRegistryError,
    get_model,
    get_pinned,
    list_models,
    pin_model,
    upload_model,
)

router = APIRouter(prefix="/models", tags=["models"])


class ModelEntryPayload(BaseModel):
    id: str
    name: str
    kind: str
    task: str
    regime: str | None = None
    horizon: str | None = None
    version: str
    created_at: str
    artefact_relpath: str
    schema_revision: str | None = None
    sha256: str
    metrics: dict[str, float] = {}
    notes: str = ""
    pinned_for: list[str] = []


def _to_payload(e: Any) -> ModelEntryPayload:
    return ModelEntryPayload(
        id=e.id,
        name=e.name,
        kind=e.kind,
        task=e.task,
        regime=e.regime,
        horizon=e.horizon,
        version=e.version,
        created_at=e.created_at,
        artefact_relpath=e.artefact_relpath,
        schema_revision=e.schema_revision,
        sha256=e.sha256,
        metrics=dict(e.metrics),
        notes=e.notes,
        pinned_for=list(e.pinned_for),
    )


@router.get("/", response_model=list[ModelEntryPayload])
async def list_(
    _user: CurrentUser,
    task: str | None = None,
    regime: str | None = None,
    horizon: str | None = None,
) -> list[ModelEntryPayload]:
    return [_to_payload(e) for e in list_models(task=task, regime=regime, horizon=horizon)]


@router.get("/pinned", response_model=ModelEntryPayload | None)
async def pinned_(
    _user: CurrentUser,
    task: str,
    regime: str | None = None,
    horizon: str | None = None,
) -> ModelEntryPayload | None:
    e = get_pinned(task=task, regime=regime, horizon=horizon)
    return _to_payload(e) if e else None


@router.get("/{model_id}", response_model=ModelEntryPayload)
async def get_(model_id: str, _user: CurrentUser) -> ModelEntryPayload:
    try:
        return _to_payload(get_model(model_id))
    except ModelRegistryError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/upload",
    response_model=ModelEntryPayload,
    status_code=status.HTTP_201_CREATED,
)
async def upload(
    _user: CurrentUser,
    file: UploadFile = File(...),
    name: str = Form(...),
    kind: str = Form("pkl"),
    task: str = Form("signal"),
    regime: str | None = Form(None),
    horizon: str | None = Form(None),
    version: str | None = Form(None),
    schema_revision: str | None = Form(None),
    notes: str = Form(""),
) -> ModelEntryPayload:
    """Accept a model file and add it to the registry. Idempotent on SHA."""
    suffix = Path(file.filename or "model").suffix or ".pkl"
    with NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(await file.read())
        tmp_path = Path(tmp.name)
    try:
        entry = upload_model(
            tmp_path,
            name=name,
            kind=kind,
            task=task,
            regime=regime,
            horizon=horizon,
            version=version,
            schema_revision=schema_revision,
            notes=notes,
        )
    finally:
        tmp_path.unlink(missing_ok=True)
    return _to_payload(entry)


class PinRequest(BaseModel):
    task: str
    regime: str | None = None
    horizon: str | None = None


@router.post("/{model_id}/pin", response_model=ModelEntryPayload)
async def pin_(
    model_id: str, body: PinRequest, _user: CurrentUser
) -> ModelEntryPayload:
    try:
        pin_model(
            model_id, task=body.task, regime=body.regime, horizon=body.horizon
        )
        return _to_payload(get_model(model_id))
    except ModelRegistryError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
