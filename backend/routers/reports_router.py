"""Executive reporting APIs."""

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.database_domain import get_ecosystem_session
from backend.models_domain import ExecutiveDigest, ExecutiveDigestRun, SavedView
from backend.services.executive_reporting_service import (
    delete_digest,
    delete_saved_view,
    render_executive_report,
    resolve_view_config,
    run_digest,
    serialize_digest,
    serialize_digest_run,
    serialize_saved_view,
    upsert_digest,
    upsert_saved_view,
)

router = APIRouter(prefix="/api/reports", tags=["reports"])


class SavedViewPayload(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    view_type: str = "executive_report"
    config: dict[str, Any] = Field(default_factory=dict)


class DigestPayload(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    saved_view_id: int | None = None
    recipients: list[str] = Field(default_factory=list)
    include_pulse: bool = True
    frequency: Literal["daily", "weekly"] = "weekly"
    weekday: int | None = Field(default=0, ge=0, le=6)
    hour_utc: int = Field(default=8, ge=0, le=23)
    active: bool = True


@router.get("/executive")
def get_executive_report(
    view_id: int | None = Query(default=None),
    include_pulse: bool | None = Query(default=None),
    db: Session = Depends(get_ecosystem_session),
):
    config = resolve_view_config(db, view_id, fallback_include_pulse=True)
    if include_pulse is not None:
        config["include_pulse"] = include_pulse
    report = render_executive_report(db, include_pulse=bool(config.get("include_pulse", True)))
    return {
        "view_id": view_id,
        "config": config,
        **report,
    }


@router.get("/views")
def list_saved_views(
    view_type: str | None = Query(default=None),
    db: Session = Depends(get_ecosystem_session),
):
    query = db.query(SavedView)
    if view_type:
        query = query.filter_by(view_type=view_type)
    views = query.order_by(SavedView.updated_at.desc()).all()
    return {"views": [serialize_saved_view(view) for view in views]}


@router.post("/views")
def create_saved_view(
    payload: SavedViewPayload,
    db: Session = Depends(get_ecosystem_session),
):
    row = upsert_saved_view(
        db,
        name=payload.name,
        view_type=payload.view_type,
        config=payload.config,
    )
    return serialize_saved_view(row)


@router.put("/views/{view_id}")
def update_saved_view(
    view_id: int,
    payload: SavedViewPayload,
    db: Session = Depends(get_ecosystem_session),
):
    if db.query(SavedView).filter_by(id=view_id).first() is None:
        raise HTTPException(status_code=404, detail="Saved view not found")
    row = upsert_saved_view(
        db,
        name=payload.name,
        view_type=payload.view_type,
        config=payload.config,
        view_id=view_id,
    )
    return serialize_saved_view(row)


@router.delete("/views/{view_id}")
def remove_saved_view(
    view_id: int,
    db: Session = Depends(get_ecosystem_session),
):
    if not delete_saved_view(db, view_id):
        raise HTTPException(status_code=404, detail="Saved view not found")
    return {"deleted": True}


@router.get("/digests")
def list_digests(db: Session = Depends(get_ecosystem_session)):
    digests = db.query(ExecutiveDigest).order_by(ExecutiveDigest.updated_at.desc()).all()
    runs = (
        db.query(ExecutiveDigestRun)
        .order_by(ExecutiveDigestRun.generated_at.desc())
        .limit(20)
        .all()
    )
    return {
        "digests": [serialize_digest(digest) for digest in digests],
        "runs": [serialize_digest_run(run) for run in runs],
    }


@router.post("/digests")
def create_digest(
    payload: DigestPayload,
    db: Session = Depends(get_ecosystem_session),
):
    row = upsert_digest(db, **payload.model_dump())
    return serialize_digest(row)


@router.put("/digests/{digest_id}")
def update_digest(
    digest_id: int,
    payload: DigestPayload,
    db: Session = Depends(get_ecosystem_session),
):
    if db.query(ExecutiveDigest).filter_by(id=digest_id).first() is None:
        raise HTTPException(status_code=404, detail="Digest not found")
    row = upsert_digest(db, digest_id=digest_id, **payload.model_dump())
    return serialize_digest(row)


@router.delete("/digests/{digest_id}")
def remove_digest(
    digest_id: int,
    db: Session = Depends(get_ecosystem_session),
):
    if not delete_digest(db, digest_id):
        raise HTTPException(status_code=404, detail="Digest not found")
    return {"deleted": True}


@router.post("/digests/{digest_id}/run")
def run_digest_now(
    digest_id: int,
    db: Session = Depends(get_ecosystem_session),
):
    digest = db.query(ExecutiveDigest).filter_by(id=digest_id).first()
    if digest is None:
        raise HTTPException(status_code=404, detail="Digest not found")
    run = run_digest(db, digest)
    return {"run": serialize_digest_run(run), "digest": serialize_digest(digest)}
